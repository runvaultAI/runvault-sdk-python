# Client

The `runvault.client` module exposes a single class — `RunVault` — and that class is the only entry point you ever import to start using the SDK. Everything else in `runvault.*` exists to support what happens inside one call to `RunVault.init(...)`.

This page explains what the class is, what it is **not**, what each of its methods does internally, and how you are expected to use it from your own code.

---

## What this module is

`RunVault` is a thin coordinator. It holds two pieces of state — your project API key and your backend's base URL — and it knows how to combine them with a framework name and a compiled application object to produce a fully wired `Agent`.

It does **not**:

- read environment variables on your behalf (you pass `api_key` and `be_url` explicitly),
- cache or pool agents (each `init(...)` call yields a fresh `Agent` bound to a fresh `run_id`),
- own an event loop, retry policy, or background task,
- do any network I/O at construction time.

The class is therefore safe to construct at module import: nothing happens on the wire until you call `init(...)`.

---

## The problem it solves

A RunVault-aware agent has to do four things before its first LLM call can succeed:

1. Authenticate to the backend with the project API key.
2. Register itself as an agent (and obtain a stable identity + a per-run `run_id`).
3. Receive an Ed25519 keypair and a CA-signed certificate, persist them with safe filesystem permissions, and verify the certificate against the deployment's CA public key.
4. Make sure that the agent's identity is present in the `ContextVar` for the rest of the SDK to read, *for every code path inside the framework graph* — without the developer having to thread an `Agent` object through every node, every tool function, every LLM constructor.

Doing any of these incorrectly produces failures that are subtle, intermittent, and security-sensitive (forged JWTs, leaked private keys, missing run scoping, runaway spend). The `RunVault` class collapses all four into a single named method — `init` — so that there is exactly one correct way to start an agent. If `init` returns, you have a usable `Agent`. If it raises, none of the partial state escapes.

---

## How it works internally

### Construction

`RunVault(api_key, be_url, timeout=10)` stores the API key on the instance and constructs a `BackendClient` (see [HTTP](http.md)) configured with the supplied base URL and timeout. Both arguments are required positional-keyword: there is no default backend.

`timeout` is forwarded to `BackendClient` and applies to the *connect*, *write*, and *pool* phases of every backend request. The *read* phase is intentionally left unbounded, because a small number of backend operations can take seconds.

Construction performs no network calls, so any backend reachability problem will surface on the first call to `init(...)` — never at import time.

### `init(framework, app, agent_id, name, budget=None, budget_alert_threshold=None)`

`init` is the only public method besides `__init__`. It performs three steps in order, and short-circuits on the first one that fails.

**1. Resolve the framework adapter.**
The `framework` string is looked up in the `runvault.adapters.ADAPTERS` dict, which maps framework names to their `wrap_*` functions. If the name is not present, `init` raises `ValueError` immediately — before any network call — with a message that lists the supported frameworks. No agent is registered, no credentials are minted, no on-disk state changes.

**2. Register the agent.**
`init` then calls the internal `_register_agent(...)` helper, which delegates to `runvault.auth.registration.register(...)`. That function is responsible for the actual `POST /auth/agents/runs` round-trip and for handling the four distinct response shapes the backend may return (fresh registration, idempotent re-registration, certificate rotation, suspension). It returns `(AgentInfo, private_key_bytes, certificate_dict)`.

`_register_agent` then constructs an `Agent` from those return values. The `Agent` is given more than just the `AgentInfo`: it also receives the project API key, the original `agent_id` string, and the `name`, because the `Agent` itself may need to call `/auth/agents/credentials/refresh` later (when the proxy reports `CERTIFICATE_REVOKED`), and that endpoint takes the same payload shape as registration.

`_register_agent` is deliberately private. It is currently marked as not part of the public API in v1 — callers are expected to go through `init`.

**3. Bind the framework adapter.**
With an `Agent` in hand, `init` invokes the resolved `wrap` function, passing it both the `Agent` and your `app`. The `wrap` function does not return anything: it **mutates the `Agent` in place** by calling `agent._bind_adapter(...)` with a framework-specific wrapper object. After this call, `agent.invoke(...)`, `agent.stream(...)`, `agent.ainvoke(...)`, and `agent.astream(...)` are all wired to delegate through the adapter, which sets the `_current_agent` `ContextVar` for the duration of each invocation.

`init` then returns the now-bound `Agent`.

### Idempotency

Two calls to `init` with the same `agent_id` will return two different `Agent` instances backed by the **same** durable agent identity (same DB row, same long-lived `agent.info.id`) but with **different** `run_id`s. The `run_id` is what scopes spend tracking, so each call represents a logically separate execution even if the agent identity is the same.

This matters in two common situations:

- A long-running process restarts. The on-disk credentials in `~/.runvault/<agent_id>/` are reused; only the `run_id` and the live JWT mint cycle restart.
- An ephemeral worker spins up to handle one task. It registers, runs, exits — the next worker registers again under the same `agent_id` and gets a fresh `run_id`.

### Errors that surface from `init`

`init` itself only raises `ValueError` directly, and only for an unknown framework name. Every other failure mode bubbles up from the calls underneath it:

| From | Raises | Meaning |
|---|---|---|
| `_register_agent` → `register(...)` | `RegistrationError` | Backend rejected the request (network, 5xx, validation). |
| `_register_agent` → `register(...)` | `AgentSuspendedError` | An administrator has suspended this agent. The SDK will not retry. |
| `_register_agent` → `register(...)` | `CertificateVerificationError` | `RV_CA_PUBLIC_KEY` is set and the returned certificate failed CA-signature or expiry checks. |
| `wrap(agent, app)` | Framework-specific | The adapter rejected `app` (e.g. not a compiled graph). |

These types are documented on the [Exceptions](exceptions.md) page.

---

## How developers use it

The intended pattern is **one `RunVault` per process, one `init` per agent**. Both are usually done at startup.

```python
from runvault import RunVault, ChatOpenAI

rv = RunVault(
    api_key="rv_live_...",
    be_url="https://your-runvault-backend",
)

llm = ChatOpenAI(model="gpt-4o-mini")
graph = build_graph(llm)

agent = rv.init(
    framework="langgraph",
    app=graph,
    agent_id="research-v1",
    name="Research Agent",
    budget=1.0,
    budget_alert_threshold=80,
)

result = agent.invoke({"input": "..."})
```

A few practical notes that follow directly from the implementation:

- **Construct `RunVault` once.** A second instance would only duplicate the underlying `BackendClient`. There is no shared cache or pool that benefits from sharing.
- **Construct `ChatOpenAI` (and other LLM clients) before `init` if you like.** The provider transports look up the active `Agent` from the `ContextVar` at request time, not at construction time. Module-level LLM instances are fine.
- **Pass `budget` only when you want a hard cap.** Omitting the argument means the backend's project-level rules apply. Setting it scopes the cap to this run.
- **`init` is the right method to retry.** If the network is flaky, retry the whole `init(...)` call rather than poking at `_register_agent` — the framework binding step needs to happen on the `Agent` instance that the retry produced.

---

## Reference

::: runvault.client.RunVault
    options:
      show_source: false
      show_root_heading: true
      show_signature: true
