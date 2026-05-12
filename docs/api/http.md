# HTTP

The `runvault.http` package contains the two pieces of code that touch the network on behalf of the SDK. They sit on different sides of the agent and talk to different services — but they share enough error-handling structure to live in the same package.

| Module | Talks to | Used by |
|---|---|---|
| `runvault.http.backend` | The RunVault **backend** (`POST /auth/agents/runs`, `POST /auth/agents/credentials/refresh`, etc.). | Registration, refresh, future SDK-to-backend REST calls. |
| `runvault.http.transport` | The RunVault **proxy** (the per-provider endpoints like `/openai/v1/chat/completions`). | Every outbound LLM request, transparently, via the provider transports installed by the `runvault.llm.*` factories. |

Everything in this package is invoked indirectly. You construct a `RunVault(...)`; that constructs a `BackendClient`. You call `rv.init(framework="langgraph", ...)`; the LangGraph adapter sets the `ContextVar`; the next time your `ChatOpenAI` instance fires an HTTP request, it runs through a `RunVaultProviderTransport`. You never instantiate either class directly in normal code.

---

## What this package is

Two thin layers, both built on `httpx`:

- **`BackendClient`** is a single typed wrapper around an `httpx.Client`. It exposes `post(path, body)` and `get(path)` that return parsed JSON, and converts any non-200 response into a typed `RunVaultError` subclass before the caller ever sees it. There is no retry logic, no auth header injection, no streaming — just one round-trip per call.
- **`RunVaultProviderTransport` / `RunVaultProviderAsyncTransport`** are `httpx.BaseTransport` subclasses installed inside the `httpx.Client` that each `runvault.llm.*` factory hands to OpenAI/Anthropic/Google's own clients. They intercept every outbound LLM request, rewrite the URL, sign the request with a fresh per-request JWT, and own the only piece of runtime self-healing in the SDK: a one-shot retry on `401 CERTIFICATE_REVOKED` after refreshing credentials.

The two layers do not share code — they sit at different boundaries — but they share the same error-classification philosophy: every 4xx and 5xx is converted into a typed exception (`BudgetExceededError`, `TokenExpiredError`, `ProxyError`, `LLMProviderError`, …) before propagating up. Callers never see raw HTTP status codes.

---

## The problem it solves

There are two distinct integration challenges between an AI agent and the RunVault platform, and they look very different:

1. **The agent needs to talk to the backend a small number of times per process.** Registration, credential refresh, future budget queries. This is plain JSON-over-HTTP, sync, low frequency, and the response shapes are stable. The right abstraction is a typed REST client with structured error parsing.

2. **The agent needs to talk to the proxy on every single LLM call.** This traffic must be indistinguishable to the underlying LLM SDK from a direct call to OpenAI/Anthropic/Google. Streaming must work. `client.with_options(...)`, `.bind(...)`, `.with_retry(...)`, tool use, and `isinstance` checks must all still work. The agent author should not have to change a single line of code after switching the import. The right abstraction here is **not** a wrapper — it is an `httpx` transport, installed deep enough that the LLM SDK is unaware of it.

`runvault.http` chooses the right abstraction at each boundary, and keeps them separate so that a developer reading the code can tell which side of the network they are looking at.

---

## How it works internally

### `BackendClient`

The class is constructed by `RunVault.__init__` with the backend URL and a timeout. Internally it builds a single `httpx.Client` with:

- **Asymmetric timeouts.** `connect`, `write`, and `pool` are all set to the user-supplied timeout (10 seconds by default). `read` is left unlimited — some backend operations (card issuance on Lithic, slow cold-start backends) can legitimately take many seconds, and we never want a healthy slow response classified as a timeout.
- **A pinned `User-Agent`** (`runvault-python/2.0`) so backend operators can see SDK traffic in their logs.

`post(path, body)` and `get(path)` do exactly what their names say. The interesting code is `_handle(response)`, which is shared between both:

| Status | Exception | Notes |
|---|---|---|
| 200 | — | Return `response.json()`. |
| 401 | `AuthenticationError` | `error_code` defaults to `INVALID_API_KEY` if the backend did not supply one. |
| 400 | `AuthenticationError` | Validation failures get the backend's `user_string` as the user-facing message. |
| Any other non-200 | `RegistrationError` | Carries the original status code and parsed `error_code` for callers to branch on. |

The `_parse_error` helper accepts both the structured RunVault error envelope (`{"detail": {"detail": "...", "code": "...", "user_string": "..."}}`) and a fallback shape where `detail` is a string. Whichever shape comes back, the caller sees three fields: an internal `message`, a machine-readable `code`, and a human-friendly `user_string` suitable for displaying in a UI.

Two design choices to be aware of:

- **No retries.** A flaky network is the caller's problem, not `BackendClient`'s. `register(...)` and `refresh(...)` are themselves idempotent enough that retrying the whole call at the next layer up is safe.
- **`ConnectionError` vs everything else.** Connection failures and timeouts are wrapped in the SDK's `ConnectionError` (distinct from Python's built-in `ConnectionError`) with a human-friendly `user_string`. HTTP-level errors are wrapped in `AuthenticationError` or `RegistrationError`. The two paths are mutually exclusive and easy to branch on in callers.

### `RunVaultProviderTransport`

This is the more subtle of the two classes. It is an `httpx.BaseTransport` — meaning it slots into an `httpx.Client` and replaces the network layer. Every request the LLM SDK builds flows through `handle_request`.

A single request goes through five steps:

1. **Look up the active `Agent`** from `runvault.context._current_agent`. If there is none, raise `RuntimeError` immediately with a message telling the developer to call `runvault.init(...)`. The transport never stores an `Agent` on itself — there is exactly one source of truth, and it is the `ContextVar`.
2. **Mint a fresh JWT** with `runvault.auth.signer.create_agent_jwt(...)`, using the agent's current private key and `run_id`. A new token, with a new `jti` and `iat`/`exp`, is generated for every request.
3. **Rewrite the request.** The factories in `runvault.llm.*` construct LLM clients with a placeholder base URL of `http://runvault.internal`. The transport rewrites that prefix to the agent's actual proxy URL (from `agent.info.proxy_url`), drops any upstream `Authorization` or `x-goog-api-key` headers, and injects:
    - `X-RV-Certificate` — the base64-encoded certificate.
    - `X-RV-Agent-JWT` — the freshly minted JWT.
4. **Send the request** via the inner `httpx.HTTPTransport`.
5. **Handle the response.** On 2xx the response is returned untouched (this is what makes streaming work — the transport never touches the body). On 4xx/5xx, the response body is read and `_raise_for_error` converts it into a typed exception.

The single piece of self-healing the SDK does at the transport layer is the **one-shot credential refresh on `401 CERTIFICATE_REVOKED`.** When an administrator rotates an agent's certificate, the proxy's revocation cache picks up the change within about 30 seconds. In-flight requests start failing with `401 CERTIFICATE_REVOKED`. Rather than surfacing that as an error, the transport:

1. Detects the exact code (`_is_cert_revoked_response`).
2. Drains the response body so the connection can be reused.
3. Calls `agent.refresh_credentials()` — which round-trips to `/auth/agents/credentials/refresh`, mints a new keypair and certificate, updates the agent in place, and persists the new files to disk.
4. Builds a fresh signed request with the new credentials.
5. Sends it once.

The retry is **deliberately one-shot**. If the second attempt also fails, the error propagates normally. There is no exponential backoff, no retry storm, no second `refresh_credentials()` call. If the refresh call itself raises `AgentSuspendedError`, the transport propagates it without retrying — admin suspension is permanent and cannot be recovered by signing harder.

`RunVaultProviderAsyncTransport` mirrors the sync class exactly, with one note: `refresh_credentials` is currently a sync call (because `BackendClient` is sync). The async transport still calls it synchronously inside an `async` method. The call is fast — a single backend round-trip — and the small block in the event loop is acceptable. If `BackendClient` ever grows an async variant, the async transport should switch to it.

### Error classification

`_raise_for_error` is the funnel through which every non-2xx response on the LLM path passes. It picks the most informative classification available in this order:

1. **Header-first.** If the response has `X-RunVault-Code: BUDGET_CAP_REACHED`, raise `BudgetExceededError` immediately — even if the response body is in the upstream provider's native error format. (The proxy uses this when it wants to deny a request but forward a provider-shaped body so SDKs don't choke on the structure.)
2. **RunVault error envelope.** Otherwise, try to parse the body as a RunVault structured error (`{"code": "...", "user_string": "...", "detail": "..."}` or `{"detail": {...}}`). If a `code` is present, choose the exception:
   - `402` or `BUDGET_CAP_REACHED` → `BudgetExceededError`
   - `401`, `INVALID_TOKEN`, `TOKEN_EXPIRED`, `JWT_EXPIRED` → `TokenExpiredError`
   - `503` or `PROXY_VERSION_MISMATCH` → `ProxyError`
   - Anything else with a code → generic `ProxyError`
3. **Provider-native error.** If there is no RunVault envelope, treat the body as the upstream provider's error and raise `LLMProviderError` with the message extracted from `error.message` / `message` / `detail`.

Every branch produces an exception that carries the original HTTP status, a machine code, and a `user_string` that is safe to show to an end user.

---

## How developers use it

The short answer is: indirectly. You do not import `BackendClient` or the transports in agent code. The patterns that **do** matter for developers are the consequences of how the layers behave:

- **Streaming "just works."** Because the transports never read the response body on the 2xx path, every streaming construct in the underlying SDK (OpenAI's `stream=True`, Anthropic's `messages.stream(...)`, LangChain's `astream`) flows through unchanged.
- **`isinstance` checks pass.** The factories return real instances of `langchain_openai.ChatOpenAI`, `openai.OpenAI`, etc. — the transport is installed *inside* the underlying class, not around it. Type checks, `Runnable` protocols, and framework integration all behave normally.
- **Catch the typed exceptions, not the status codes.** Calling code that wants to react to budget caps writes `except BudgetExceededError`, not `except httpx.HTTPStatusError`. The classification has already been done.
- **Credential rotation is transparent.** You do not need to wrap LLM calls in retry logic for the certificate-revoked case. The transport already does exactly one retry, exactly when it should, and only that.

---

## Reference

### Backend Client

::: runvault.http.backend
    options:
      show_source: false
      show_root_heading: true
      show_signature: true

### Provider Transports

::: runvault.http.transport
    options:
      show_source: false
      show_root_heading: true
      show_signature: true
