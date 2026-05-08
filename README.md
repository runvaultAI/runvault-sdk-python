# RunVault Python SDK

[![PyPI](https://img.shields.io/pypi/v/runvault.svg)](https://pypi.org/project/runvault/)
[![Python](https://img.shields.io/pypi/pyversions/runvault.svg)](https://pypi.org/project/runvault/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**Financial identity infrastructure for AI agents.**
Website: <https://runvault.to>

---

## What is RunVault?

RunVault gives AI agents a verifiable identity, a budget, and a way to spend
it. Each agent registers once with the RunVault platform and is issued a
short-lived cryptographic certificate. From then on, every LLM call the agent
makes flows through the RunVault proxy, which verifies the agent's identity,
checks its remaining budget, forwards the request to the underlying provider
(OpenAI / Anthropic / Google / …), and records the cost — all without the
agent ever holding a long-lived provider API key.

For platform operators this means: real per-agent spending caps, per-call
audit, instant revocation, and BYOK provider keys that never leave the
backend. For agent authors it means: change the import line, get a JWT,
keep building.

## What is this package?

`runvault` is the **Python SDK** that AI agents use to integrate with the
platform. It handles:

- **Registration** — `POST /auth/agents/runs` with your project API key,
  receiving back an Ed25519 keypair and a CA-signed certificate that
  authenticates the agent to the proxy.
- **Per-request signing** — every outbound LLM call is signed with a fresh
  short-lived EdDSA JWT minted by the SDK (no replay window, no shared
  secrets in transit).
- **Drop-in LLM clients** — `ChatOpenAI`, `ChatAnthropic`,
  `ChatGoogleGenerativeAI`, etc. that route through the RunVault proxy
  with no other code change.
- **Framework adapters** — wrap a compiled LangGraph graph and the SDK
  propagates agent context to every node automatically.
- **Recovery flows** — auto-fall-back to `/credentials/refresh` when the
  admin rotates an agent's certificate, with one transparent retry on
  the in-flight request.

## Related projects

| Repository | Purpose |
|---|---|
| [runvaultAI/runvault-sdk-python](https://github.com/runvaultAI/runvault-sdk-python) | This package — Python SDK for AI agents. |
| [runvaultAI/runvault-identity-sdk-go](https://github.com/runvaultAI/runvault-identity-sdk-go) | Go identity SDK. Proxies and other RunVault-aware services import it to verify the certificate + agent JWT presented on each request, without depending on the rest of the RunVault platform. |

The Python SDK *issues* the credentials your agent presents; the Go identity
SDK is the corresponding *verifier* used by anything sitting on the receive
side of the connection.

---

## Install

The base package is small. LLM provider support is opt-in via extras:

```bash
pip install runvault                                    # SDK only
pip install runvault[openai]                            # OpenAI raw client
pip install runvault[anthropic]                         # Anthropic raw client
pip install runvault[langgraph,langchain-openai]        # LangGraph + LangChain OpenAI
pip install runvault[all]                               # everything
```

Available extras: `openai`, `anthropic`, `google`, `langchain-openai`,
`langchain-anthropic`, `langchain-google`, `langgraph`, `all`.

Requires **Python 3.9+**.

---

## Quick start

```python
from runvault import RunVault, ChatOpenAI

rv = RunVault(
    api_key="rv_live_...",                # your RunVault project API key
    be_url="https://your-runvault-backend",
)

llm = ChatOpenAI(model="gpt-4o-mini")     # routes through the RunVault proxy
graph = build_graph(llm)                  # any compiled LangGraph graph

agent = rv.init(
    framework="langgraph",
    app=graph,
    agent_id="research-v1",
    name="Research Agent",
    budget=1.0,                           # optional USD cap
    budget_alert_threshold=80,            # optional alert at 80% spent
)

result = agent.invoke({"input": "What is..."})
```

Behind the scenes `rv.init()`:

1. **Registers** the agent with the backend (idempotent — calling again
   with the same `agent_id` returns the existing record plus a fresh
   `run_id`).
2. **Persists the keypair** to `~/.runvault/<agent_id>/` with
   `0600` / `0700` permissions.
3. **Verifies** the CA signature on the certificate, when
   `RV_CA_PUBLIC_KEY` is set.
4. **Wraps** your compiled LangGraph app so every LLM call inside it is
   signed and routed through the RunVault proxy with the correct
   identity and run context.

---

## How authentication works

RunVault uses a two-step PKI flow rather than long-lived bearer tokens.

```
┌──────────────────────────┐   ┌──────────────────────────┐   ┌──────────────────────────┐
│       Your agent         │   │   RunVault backend       │   │   RunVault proxy         │
│       (this SDK)         │   │   (issues credentials)   │   │   (verifies on every     │
│                          │   │                          │   │    LLM request)          │
└────────────┬─────────────┘   └────────────┬─────────────┘   └────────────┬─────────────┘
             │                              │                              │
             │  POST /auth/agents/runs      │                              │
             │  { rv_api_key, agent_id }    │                              │
             ├─────────────────────────────▶│                              │
             │  Ed25519 private key +       │                              │
             │  CA-signed certificate       │                              │
             │◀─────────────────────────────┤                              │
             │                              │                              │
             │  POST /openai/v1/chat/...    │                              │
             │  X-RV-Certificate: <cert>    │                              │
             │  X-RV-Agent-JWT: <fresh JWT> │                              │
             ├──────────────────────────────┼─────────────────────────────▶│
             │                              │                              │ 1. Verify CA
             │                              │                              │    signature
             │                              │                              │ 2. Verify EdDSA
             │                              │                              │    JWT signature
             │                              │                              │    with the cert's
             │                              │                              │    embedded pubkey
             │                              │                              │ 3. Budget check
             │                              │                              │ 4. Forward to LLM
             │                              │                              │
             │  LLM response (streamed)     │                              │
             │◀─────────────────────────────┴──────────────────────────────┤
             │                                                             │
```

- **Certificate** (`X-RV-Certificate`) — issued once at registration, signed
  by the RunVault CA, embeds the agent's public key + scope + expiry.
- **Agent JWT** (`X-RV-Agent-JWT`) — minted **per request** by the SDK, signed
  with the agent's private key, valid for 5 minutes, carries a fresh
  `jti` for replay protection.
- **The agent's private key never leaves disk.** The SDK signs locally; only
  the JWT signature crosses the network.
- **No long-lived bearer token.** If a JWT leaks it's already expiring; if a
  certificate is revoked the proxy detects it within ~30 seconds and the
  SDK transparently calls `/credentials/refresh` to mint a fresh one.

---

## Configuration

| Variable | Required | Purpose |
|---|---|---|
| `RUNVAULT_API_KEY` | yes (recommended) | Your project API key. Pass to `RunVault(api_key=…)` or read from env. |
| `RV_CA_PUBLIC_KEY` | recommended | Base64-encoded Ed25519 RunVault CA public key. When set, the SDK verifies the CA signature on certificates returned by registration. When absent the SDK warns and proceeds — fine for dev, never for production. |
| `BE_URL` / `RUNVAULT_BE_URL` | no | Backend base URL. Pass to `RunVault(be_url=…)` or read from env. |

The `RV_CA_PUBLIC_KEY` value is published by your RunVault deployment.
Self-hosted operators generate it once with `scripts/generate_rv_keys.sh`
in the platform repo and distribute it to agent containers. Verify Python-side
manually:

```python
import os
from runvault.auth.credentials import load_credentials, verify_certificate

priv, cert = load_credentials("research-v1")
verify_certificate(cert, os.environ["RV_CA_PUBLIC_KEY"])
print("certificate valid")
```

---

## Supported LLM clients

Drop-in factories that return real upstream instances configured to route
through the RunVault proxy:

| Factory | Underlying class | Extra |
|---|---|---|
| `runvault.ChatOpenAI` | `langchain_openai.ChatOpenAI` | `langchain-openai` |
| `runvault.OpenAI` / `AsyncOpenAI` | `openai.OpenAI` / `AsyncOpenAI` | `openai` |
| `runvault.ChatAnthropic` | `langchain_anthropic.ChatAnthropic` | `langchain-anthropic` |
| `runvault.Anthropic` / `AsyncAnthropic` | `anthropic.Anthropic` / `AsyncAnthropic` | `anthropic` |
| `runvault.ChatGoogleGenerativeAI` | `langchain_google_genai.ChatGoogleGenerativeAI` | `langchain-google` |

Streaming, `.bind(...)`, `.with_retry(...)`, tool use, and `isinstance`
checks all behave like the underlying class — the only difference is
that traffic flows through your RunVault proxy.

## Supported frameworks

- **LangGraph** — pass a compiled graph to `rv.init(framework="langgraph", app=graph, …)`.

Adding a new framework adapter is a small file under
`runvault.adapters` plus an entry in `ADAPTERS`. PRs welcome.

---

## Error handling

The SDK raises typed exceptions so you can branch on the failure mode:

```python
from runvault.exceptions import (
    AgentSuspendedError,            # admin suspended this agent — permanent
    BudgetExceededError,            # 402 — agent has hit its spend cap
    CertificateVerificationError,   # CA signature failed
    LLMProviderError,               # upstream provider returned an error
    ProxyError,                     # RunVault proxy rejected the request
    RegistrationError,              # backend registration failure
    TokenExpiredError,              # JWT or certificate is invalid/expired
)
```

`AgentSuspendedError` is the only one your code probably wants to catch
specifically — it indicates an admin has clicked "Suspend" in the
dashboard and only an admin can re-enable the agent. The SDK will not
auto-retry through it.

---

## License

Apache 2.0. The full text is bundled inside every release wheel at
`runvault-<version>.dist-info/licenses/LICENSE`, and the canonical copy
lives at
[LICENSE on GitHub](https://github.com/runvaultAI/runvault-sdk-python/blob/main/LICENSE).

---

## Links

- **Website** — <https://runvault.to>
- **PyPI** — <https://pypi.org/project/runvault/>
- **Source** — <https://github.com/runvaultAI/runvault-sdk-python>
- **Go identity SDK** — <https://github.com/runvaultAI/runvault-identity-sdk-go>
- **Issues** — <https://github.com/runvaultAI/runvault-sdk-python/issues>
