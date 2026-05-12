# RunVault Python SDK

[![PyPI](https://img.shields.io/pypi/v/runvault.svg)](https://pypi.org/project/runvault/)
[![Python](https://img.shields.io/pypi/pyversions/runvault.svg)](https://pypi.org/project/runvault/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/runvaultAI/runvault-sdk-python/blob/main/LICENSE)

**Financial identity infrastructure for AI agents.**
Website: <https://runvault.to>

---

## What is RunVault?

RunVault gives AI agents a verifiable identity, a budget, and a way to spend it. Each agent registers once with the RunVault platform and is issued a short-lived cryptographic certificate. From then on, every LLM call the agent makes flows through the RunVault proxy, which verifies the agent's identity, checks its remaining budget, forwards the request to the underlying provider (OpenAI / Anthropic / Google / …), and records the cost — all without the agent ever holding a long-lived provider API key.

**For platform operators** this means: real per-agent spending caps, per-call audit, instant revocation, and BYOK provider keys that never leave the backend.

**For agent authors** it means: change the import line, get a JWT, keep building.

## What is this package?

`runvault` is the Python SDK that AI agents use to integrate with the platform. It handles:

- **Registration** — `rv.init(...)` registers your agent with the platform using your project API key and receives back an Ed25519 keypair and a CA-signed certificate that authenticates the agent to the proxy.
- **Per-request signing** — every outbound LLM call is signed with a fresh short-lived EdDSA JWT minted by the SDK (no replay window, no shared secrets in transit).
- **Drop-in LLM clients** — `ChatOpenAI`, `ChatAnthropic`, `ChatGoogleGenerativeAI`, etc. that route through the RunVault proxy with no other code change.
- **Framework adapters** — wrap a compiled LangGraph graph and the SDK propagates agent context to every node automatically.
- **Recovery flows** — auto-fall-back to `/credentials/refresh` when the admin rotates an agent's certificate, with one transparent retry on the in-flight request.

---

## Install

The base package is small. LLM provider support is opt-in via extras:

```bash
pip install runvault                                # SDK only
pip install runvault[openai]                        # OpenAI raw client
pip install runvault[anthropic]                     # Anthropic raw client
pip install runvault[langgraph,langchain-openai]    # LangGraph + LangChain OpenAI
pip install runvault[all]                           # everything
```

Available extras: `openai`, `anthropic`, `google`, `langchain-openai`, `langchain-anthropic`, `langchain-google`, `langgraph`, `all`.

Requires **Python 3.9+**.

---

## A first look

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

Three RunVault-specific lines — the `RunVault(...)` constructor, the `ChatOpenAI` import, and the `rv.init(...)` call — give your agent a verifiable identity, a $1 spending cap, and a full audit trail. The rest is your existing code.

[Get started](getting-started/quickstart.md){ .md-button .md-button--primary }
[Install](getting-started/installation.md){ .md-button }

---

## Documentation

<div class="grid cards" markdown>

-   **[Client](api/client.md)**

    ---

    The `RunVault` entry point and what its `init(...)` method does step by step.

-   **[Context](api/context.md)**

    ---

    How the active `Agent` is made available everywhere without parameter threading.

-   **[Runtime](api/runtime.md)**

    ---

    The `Agent` object returned by `init` and how it refreshes credentials in flight.

-   **[Auth & Credentials](api/auth.md)**

    ---

    Registration, on-disk credential storage, CA verification, and JWT signing.

-   **[HTTP & Transports](api/http.md)**

    ---

    The typed backend client and the per-request signing transport.

-   **[Adapters](api/adapters.md)**

    ---

    The framework extension point and a walk-through of the LangGraph adapter.

</div>

---

## Links

- **Source** — <https://github.com/runvaultAI/runvault-sdk-python>
- **PyPI** — <https://pypi.org/project/runvault/>
- **Website** — <https://runvault.to>
- **Issues** — <https://github.com/runvaultAI/runvault-sdk-python/issues>
