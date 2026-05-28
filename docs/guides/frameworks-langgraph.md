# LangGraph

The SDK does not wrap LangGraph's `StateGraph` or `compile()`. You own the graph; the SDK only wires the LLM and defines the run boundary.

```bash
pip install "runvault[langgraph,langchain-openai]"
```

## Minimal example

```python
from typing import TypedDict
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

from runvault import RunVault

rv = RunVault(api_key="rv_live_...")
identity = rv.register_agent(agent_id="research-v1", name="Research")

RVChat = identity.build_llm(ChatOpenAI)


class State(TypedDict):
    question: str
    answer: str


def call_model(state: State) -> dict:
    llm = RVChat(model="gpt-4o-mini")
    return {"answer": llm.invoke(state["question"]).content}


builder = StateGraph(State)
builder.add_node("answer", call_model)
builder.set_entry_point("answer")
builder.add_edge("answer", END)
graph = builder.compile()

with identity.run():
    result = graph.invoke({"question": "What is the capital of France?"})
    print(result["answer"])
```

The pattern is the same for every framework: build the LLM with `identity.build_llm(...)`, then call your graph inside `with identity.run():`.

## Why no graph wrapper

The active `Run` is held in a `ContextVar`. PEP 567 propagates it automatically to:

- every node in the graph,
- every `asyncio.create_task` spawned inside the graph,
- every callback `langgraph` invokes during execution.

So a single `with identity.run():` at the boundary covers the entire invocation — whether it's `invoke`, `ainvoke`, `stream`, or `astream`.

## Streaming

```python
with identity.run():
    for event in graph.stream({"question": "..."}):
        print(event)
```

Streams are forwarded transparently — the transport never reads response bodies on the 2xx path, so LangGraph's streaming behaves exactly as it does without RunVault.

## Reusing the LLM across nodes

Build the wired class once, instantiate inside nodes (or once at module scope — both are fine):

```python
RVChat = identity.build_llm(ChatOpenAI)
llm = RVChat(model="gpt-4o-mini")

def node_a(state): return {"a": llm.invoke(state["x"]).content}
def node_b(state): return {"b": llm.invoke(state["y"]).content}
```

A single client serves any number of runs and any number of concurrent nodes — the active `Run` is read fresh on each request.

## Async

```python
async with identity.run():
    result = await graph.ainvoke({"question": "..."})
```

`asyncio.create_task` inherits the active `Run`, so concurrent async fan-out within a single `with` block shares one `run_id`.

## Accessing the run inside a node

When you need `run_id` or `agent_id` inside a node or a tool function, use `current_run()`:

```python
from runvault import current_run

def tool_node(state):
    run = current_run()
    log.info("tool fired in run %s", run.run_id)
    ...
```
