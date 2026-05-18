# Quickstart

This page takes you from "I have `runvault` installed" to "a real LLM call has been signed and routed through the RunVault proxy" in about twenty lines of code.

The example uses LangChain's `ChatOpenAI`. The flow is identical for any other supported LLM class — only the import changes.

```bash
pip install "runvault[langchain-openai]"
```

## 1. Create the SDK client

`RunVault(...)` holds your project API key and the backend URL. Construction does not touch the network.

```python
import os
from runvault import RunVault

rv = RunVault(
    api_key=os.environ["RUNVAULT_API_KEY"],
    be_url=os.environ["RUNVAULT_BE_URL"],
)
```

## 2. Register an agent

`rv.register_agent(...)` is the only call that crosses the network at startup. On first use the backend provisions an Ed25519 keypair and a CA-signed certificate; both are cached to `~/.runvault/<agent_id>/`. Subsequent runs of the same `agent_id` reuse the on-disk material.

```python
identity = rv.register_agent(
    agent_id="research-v1",
    name="Research Agent",
    budget=1.0,                   # optional USD cap
    budget_alert_threshold=80,    # optional alert at 80% spent
)
```

The returned `Identity` is a long-lived object. You typically build it once at startup and reuse it for the life of the process.

## 3. Build an LLM that routes through the proxy

`identity.build_llm(BaseClass)` returns a dynamic subclass of the framework's LLM class with the RunVault transport pre-wired. Inherited methods (`.invoke()`, `.stream()`, `.bind_tools()`, …) continue to work unchanged.

```python
from langchain_openai import ChatOpenAI

RVChat = identity.build_llm(ChatOpenAI)
llm = RVChat(model="gpt-4o-mini")
```

`RVChat` is a real subclass of `ChatOpenAI` — `isinstance` checks, LangChain Runnables, tool binding, and streaming all behave as upstream.

## 4. Wrap the call in a `Run`

Every outbound LLM request must happen inside `with identity.run():`. The block defines an execution scope, generates a fresh `run_id` locally (no backend round-trip), and tags every JWT minted inside it with that `run_id`.

```python
with identity.run():
    answer = llm.invoke("What is the capital of France?")
    print(answer.content)
```

Async usage is symmetric:

```python
async with identity.run():
    answer = await llm.ainvoke("...")
```

## What just happened

When `llm.invoke(...)` fired, four things happened that did not require any code from you:

1. The active `Run` was looked up from a `ContextVar`. (No active run → `NoActiveRunError` before any network call.)
2. The transport refused to attach RunVault credentials to anything other than your proxy host. ([Host allowlist](../guides/authentication.md#host-allowlist).)
3. A fresh, 5-minute-TTL EdDSA JWT was signed with the identity's private key, embedding `agent_id`, `run_id`, and a fresh `jti`. The certificate went along in the `X-RV-Certificate` header.
4. The proxy verified the certificate's CA signature, verified the JWT against the public key inside the certificate, checked the budget, forwarded the request to OpenAI, and returned the response.

Your agent now has a verifiable identity, a spending cap enforced at the proxy, and no OpenAI API key anywhere in its process — without changing the shape of your application code.

## Next

- [LLM Clients](../guides/llm-clients.md) — every LLM class `build_llm` can wire.
- [Frameworks: LangGraph](../guides/frameworks-langgraph.md) — using a wired LLM inside a compiled graph.
- [Authentication](../guides/authentication.md) — the PKI flow in detail.
