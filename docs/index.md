# RunVault Python SDK

[![PyPI](https://img.shields.io/pypi/v/runvault.svg)](https://pypi.org/project/runvault/)
[![Python](https://img.shields.io/pypi/pyversions/runvault.svg)](https://pypi.org/project/runvault/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/runvaultAI/runvault-sdk-python/blob/main/LICENSE)

**Financial identity infrastructure for AI agents.**
Website: <https://runvault.to>

---

## What is RunVault?

RunVault gives each AI agent a verifiable cryptographic identity, a budget, and a way to spend it. An agent registers once with the RunVault platform and receives a short-lived, CA-signed certificate plus an Ed25519 keypair. Every LLM call the agent makes is signed with a fresh EdDSA JWT and routed through the RunVault proxy, which checks the certificate, enforces the budget, forwards the request to the underlying provider (OpenAI, Anthropic, Google, …), and records the cost.

The agent never holds a long-lived provider API key. The platform sees every call, can revoke the agent instantly, and bills exactly what was spent.

---

## What is this package?

`runvault` is the Python SDK that an agent imports to integrate with the platform. It is built around three primitives:

| Primitive | Lifetime | What it does |
|---|---|---|
| **`RunVault`** | per process | Holds the project API key. Registers agents. |
| **`Identity`** | per agent | Holds the Ed25519 key + CA-signed certificate. Builds LLM clients. Opens runs. |
| **`Run`** | per execution | A `ContextVar`-scoped block that tags every outbound call with a fresh `run_id`. |

Core is framework-agnostic — `pip install runvault` is enough to call the proxy from your own code. Framework support (LangChain, LangGraph, CrewAI, …) is opt-in via extras. The SDK never wraps the framework's runner; it only wires the LLM.

---

## Install

```bash
pip install runvault                     # core SDK
pip install "runvault[langchain-openai]" # + LangChain ChatOpenAI wiring
pip install "runvault[crewai]"           # + CrewAI BaseLLM wiring
pip install "runvault[all]"              # everything
```

Requires **Python 3.9+**. Full matrix on [Installation](getting-started/installation.md).

---

## A first look

```python
from runvault import RunVault
from langchain_openai import ChatOpenAI

rv = RunVault(api_key="rv_live_...", be_url="https://your-runvault-backend")

identity = rv.register_agent(agent_id="research-v1", name="Research Agent")
RVChat = identity.build_llm(ChatOpenAI)
llm = RVChat(model="gpt-4o-mini")

with identity.run():
    answer = llm.invoke("What is the capital of France?")
    print(answer.content)
```

Four lines of RunVault-specific code give your agent a verifiable identity, a spending cap that the proxy enforces, and a full audit trail. Your graph code, your prompts, and your provider SDKs stay unchanged.

[Get started](getting-started/quickstart.md){ .md-button .md-button--primary }
[Install](getting-started/installation.md){ .md-button }

---

## Documentation

<div class="grid cards" markdown>

-   **[Quickstart](getting-started/quickstart.md)**

    ---

    Register an agent and route your first call through the proxy in under twenty lines.

-   **[LLM Clients](guides/llm-clients.md)**

    ---

    `identity.build_llm(...)` for LangChain, OpenAI, Anthropic, Google, and CrewAI.

-   **[Frameworks: LangGraph](guides/frameworks-langgraph.md)**

    ---

    Drop a wired LLM into any LangGraph node — no graph wrapping required.

-   **[Authentication](guides/authentication.md)**

    ---

    The PKI flow: certificates, EdDSA JWTs, and how credentials rotate automatically.

-   **[Credential Rotation](guides/credential-rotation.md)**

    ---

    How the SDK refreshes credentials transparently on `401 CERTIFICATE_REVOKED`.

-   **[Configuration](guides/configuration.md)**

    ---

    Parameters, environment variables, and the cross-identity guard.

</div>

---

## Links

- **Source** — <https://github.com/runvaultAI/runvault-sdk-python>
- **PyPI** — <https://pypi.org/project/runvault/>
- **Website** — <https://runvault.to>
- **Issues** — <https://github.com/runvaultAI/runvault-sdk-python/issues>
