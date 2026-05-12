# RunVault Python SDK

**Financial identity infrastructure for AI agents.**

RunVault gives every AI agent a verifiable cryptographic identity, an enforced budget, and a way to spend it — all without ever holding a long-lived OpenAI, Anthropic, or Google API key. Each agent registers once with the RunVault platform, receives a short-lived certificate, and from then on every LLM call is signed, audited, and routed through the RunVault proxy.

This site documents the **Python SDK** that AI agents use to integrate with the platform. Change one import line, call `RunVault.init(...)` once at startup, and the rest of your agent code stays exactly as it was.

---

## What this SDK gives you

| Capability | What it means in practice |
|---|---|
| **Cryptographic identity** | Your agent registers with the backend and receives a CA-signed Ed25519 certificate. The certificate proves the agent is who it says it is, scoped to a specific project, with an expiry the proxy enforces. |
| **Per-request signing** | Every outbound LLM call carries a freshly minted, five-minute EdDSA JWT signed locally with the agent's private key. Nothing reusable ever crosses the network. |
| **Spend control** | Set a USD budget cap at registration time. The proxy enforces it on every request. Catch `BudgetExceededError` and decide how to recover. |
| **Drop-in LLM clients** | `ChatOpenAI`, `ChatAnthropic`, `ChatGoogleGenerativeAI` (and raw `OpenAI`, `Anthropic`, `AsyncOpenAI`, `AsyncAnthropic`) — real instances of the upstream classes, routed through the RunVault proxy. Streaming, tool use, `.bind(...)`, and `isinstance` checks all behave exactly as they would normally. |
| **Framework adapters** | Wrap a compiled LangGraph graph and the SDK propagates the active agent into every node automatically — no parameter threading. |
| **Transparent credential rotation** | When an administrator rotates an agent's certificate, the SDK detects it, mints fresh credentials, and retries the in-flight request once. Your code does not need to handle this manually. |

---

## A 60-second example

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
)

result = agent.invoke({"input": "What is...?"})
```

That is the entire integration. One import change, one `init` call. The remaining pages on this site explain what each of those moving parts actually does and why.

---

## What each section teaches

The documentation is organised around the SDK's internal architecture. Each page is a short read on its own; together they form a complete mental model of how an agent interacts with the RunVault platform.

### [Client →](api/client.md)
The entry point. The `RunVault` class, its constructor, and the `init(...)` method that registers an agent, fetches credentials, and binds your framework graph — all in one call. Start here if you want to know what happens between `rv = RunVault(...)` and `agent.invoke(...)`.

### [Context →](api/context.md)
How the active `Agent` is made available to every layer of the SDK — and to your own node code — without being passed around explicitly. Explains the `ContextVar` model, the per-task / per-thread isolation guarantees, and the `get_rv()` accessor you can use inside nodes that need identity-aware behavior.

### [Runtime (Agent) →](api/runtime.md)
The `Agent` class returned by `init(...)`. What state it holds, why it owns the credential-refresh flow, and how its `invoke` / `stream` / `ainvoke` / `astream` methods delegate to the framework adapter you bound at startup.

### [Auth & Credentials →](api/auth.md)
The cryptographic identity layer. Three modules in one package: how registration obtains a keypair and a CA-signed certificate, how the SDK stores and verifies them on disk with safe permissions, and how a fresh EdDSA JWT is minted for every outbound request.

### [HTTP & Transports →](api/http.md)
The two network boundaries the SDK speaks across: the typed `BackendClient` used for registration and refresh, and the `RunVaultProviderTransport` that sits invisibly inside every LLM client to sign requests, route them through the proxy, and recover transparently from certificate rotation.

### [Adapters →](api/adapters.md)
The framework extension point. The `ADAPTERS` registry, the contract a framework wrapper must satisfy, and a walk-through of the LangGraph implementation as a template for adding support for other agent frameworks.

---

## How the pieces fit together

```
              ┌────────────────────────────────┐
              │ Your agent code                │
              │    rv = RunVault(...)          │
              │    agent = rv.init(...)        │
              │    agent.invoke({...})         │
              └───────────────┬────────────────┘
                              │
              ┌───────────────▼────────────────┐
              │ Adapter (LangGraph)            │  ← sets ContextVar
              │   _current_agent.set(agent)    │
              └───────────────┬────────────────┘
                              │
              ┌───────────────▼────────────────┐
              │ Your graph runs                │
              │   nodes call ChatOpenAI(...)   │
              └───────────────┬────────────────┘
                              │
              ┌───────────────▼────────────────┐
              │ Provider transport              │  ← reads ContextVar
              │   • mint fresh EdDSA JWT       │
              │   • inject X-RV-Certificate    │
              │   • rewrite URL → proxy        │
              └───────────────┬────────────────┘
                              │
                              ▼
                  RunVault proxy → LLM provider
```

If you want the architectural tour in reading order, the path is:
**[Client](api/client.md) → [Runtime](api/runtime.md) → [Context](api/context.md) → [Auth](api/auth.md) → [HTTP](api/http.md) → [Adapters](api/adapters.md)**.

---

## Requirements

- Python **3.9 or newer**.
- A reachable RunVault backend (the `be_url` you pass to `RunVault(...)`).
- A RunVault project API key (`rv_live_…`).
- Optionally, the `RV_CA_PUBLIC_KEY` environment variable — recommended in production so the SDK can verify the CA signature on certificates it receives.

LLM provider support is opt-in via pip extras (`runvault[openai]`, `runvault[anthropic]`, `runvault[langgraph]`, `runvault[all]`, …). See the [installation guide](getting-started/installation.md) for the full matrix.

---

## Links

- **Source code** — <https://github.com/runvaultAI/runvault-sdk-python>
- **PyPI** — <https://pypi.org/project/runvault/>
- **Website** — <https://runvault.to>
- **Issues** — <https://github.com/runvaultAI/runvault-sdk-python/issues>
