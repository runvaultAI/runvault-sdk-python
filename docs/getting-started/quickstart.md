# Quickstart

This page takes you from "I have `runvault` installed" to "an LLM call has flowed through the RunVault proxy under a cryptographic identity" in roughly fifteen lines of code.

The example uses **LangGraph** as the agent framework and **ChatOpenAI** as the LLM. Both are opt-in extras:

```bash
pip install runvault[langgraph,langchain-openai]
```

Make sure your RunVault backend is reachable and you have a project API key (`rv_live_…`) before you begin.

## A minimal LangGraph graph

Start with the smallest possible graph — one node that calls an LLM and returns the answer. The `ChatOpenAI` import comes from `runvault`, not from `langchain_openai`: it is a real instance of the upstream class, but the underlying HTTP transport has been replaced so every request flows through the RunVault proxy.

```python
from typing import TypedDict

from langgraph.graph import StateGraph, END

from runvault import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini")


class State(TypedDict):
    question: str
    answer: str


def call_model(state: State) -> dict:
    response = llm.invoke(state["question"])
    return {"answer": response.content}


builder = StateGraph(State)
builder.add_node("model", call_model)
builder.set_entry_point("model")
builder.add_edge("model", END)
graph = builder.compile()
```

At this point you have an ordinary compiled LangGraph graph. It is not yet runnable — the `ChatOpenAI` instance is configured to route through the RunVault proxy, but no agent has registered, so the transport has nothing to authenticate with.

## Initialize RunVault

Construct a `RunVault` client. This does no I/O — it stores your credentials and prepares the internal HTTP layer.

```python
from runvault import RunVault

rv = RunVault(
    api_key="rv_live_...",
    be_url="https://your-runvault-backend",
)
```

A common production pattern is to read both values from the environment:

```python
import os

from runvault import RunVault

rv = RunVault(
    api_key=os.environ["RUNVAULT_API_KEY"],
    be_url=os.environ["RUNVAULT_BE_URL"],
)
```

## Register the agent and wrap the graph

`rv.init(...)` is the only call that crosses the network. It registers the agent with the backend, persists the credentials it receives, and wires up the LangGraph adapter so the active agent is propagated automatically into every node.

```python
agent = rv.init(
    framework="langgraph",
    app=graph,
    agent_id="quickstart-agent",
    name="Quickstart Agent",
    budget=1.0,                  # optional USD cap on this run
    budget_alert_threshold=80,   # optional alert at 80% spent
)
```

`init` is idempotent on `agent_id`: running this script twice reuses the same agent identity and only issues a fresh `run_id` for the new execution.

## Invoke the graph

Use `agent` exactly as you would use the original compiled graph:

```python
result = agent.invoke({"question": "What is the capital of France?"})
print(result["answer"])
```

Expected output (model output will vary):

```
The capital of France is Paris.
```

Async and streaming behave the same way:

```python
# async
result = await agent.ainvoke({"question": "..."})

# streaming
for chunk in agent.stream({"question": "..."}):
    print(chunk)
```

## What just happened

When `agent.invoke(...)` was called, four things happened that did not require any code from you:

1. The LangGraph adapter set the active `Agent` on a `ContextVar` for the duration of the call.
2. Your node called `llm.invoke(...)`, which fired an HTTP request through the RunVault transport installed inside `ChatOpenAI`.
3. The transport read the `Agent` from the `ContextVar`, minted a fresh five-minute EdDSA JWT signed with the agent's private key, attached the CA-signed certificate, rewrote the request URL to point at the proxy, and forwarded the call.
4. The proxy verified the certificate's CA signature, verified the JWT against the public key embedded in the certificate, checked the budget, forwarded the request to OpenAI, and returned the response.

Your agent now has a verifiable identity, a spending cap that the proxy enforces, and no long-lived OpenAI API key anywhere in its process — without changing the shape of your application code.

## Next

- [Client](../api/client.md) — what `RunVault.init(...)` does step by step.
- [Runtime](../api/runtime.md) — the `Agent` object returned by `init`, and how it refreshes credentials in flight.
- [Auth & Credentials](../api/auth.md) — the PKI flow and on-disk credential layout.
- [Adapters](../api/adapters.md) — how the LangGraph wrapper works and how to add support for another framework.
