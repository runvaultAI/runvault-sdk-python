# Context

The `runvault.context` module is the smallest module in the SDK and the one that the rest of the SDK depends on most heavily. It does exactly one thing: it makes the active `Agent` available as an ambient value for the duration of a graph invocation, so that no code in the SDK or in your application has to pass an `Agent` argument around explicitly.

---

## What this module is

The entire module is a single `ContextVar` and a single accessor function:

- `_current_agent: ContextVar[Agent]` — the storage slot, defined at module load time with no default value.
- `get_rv() -> Agent` — reads the slot and returns the current `Agent`, or raises `RuntimeError` if no agent is bound.

There are no classes, no decorators, no setup steps. The `ContextVar` is set by framework adapters (currently the LangGraph wrapper) on the way *into* every invocation method, and reset on the way *out* via `try / finally`.

---

## The problem it solves

When an agent runs, three different layers of code need access to the same `Agent` object:

1. **The HTTP transport** wrapping every outbound LLM call needs the agent's private key (to mint a fresh JWT for each request), its certificate (for the `X-RV-Certificate` header), and its proxy URL (to rewrite the request URL).
2. **The framework adapter** itself, which wraps your compiled graph.
3. **Your own node code** may want to inspect `agent.info.run_id`, log `agent.info.id`, or read other identity state.

The naive solution — threading an `Agent` parameter through every node, tool function, and LLM constructor — is exactly the kind of intrusive wiring the SDK is designed to avoid. You imported `ChatOpenAI` from `runvault` so you would not have to change your code; making you re-thread an argument would defeat that goal.

`runvault.context` makes the `Agent` ambient for the duration of a graph invocation. Code that needs it asks; code that doesn't is unaffected.

---

## How it works internally

The choice of `contextvars.ContextVar` (and not a module global, or a thread-local) is deliberate:

| Property | What it gives you |
|---|---|
| **Per-`asyncio`-task isolation** | Two coroutines running concurrently on the same thread see independent `Agent` values. |
| **Per-thread isolation** | A multithreaded server (FastAPI sync handlers, worker pools, …) gets independent `Agent` values per thread without any locking. |
| **Stack-discipline via `set` / `reset` tokens** | Setting a `ContextVar` returns a `Token` that the caller uses to restore the previous value, even if the previous value was "unset". This is what lets the adapter's `try / finally` safely unwind nested invocations. |

The set/reset is owned entirely by the framework adapter — for LangGraph, see `runvault.adapters.langgraph._LangGraphWrapper`. Each of its public methods (`invoke`, `ainvoke`, `stream`, `astream`) follows the same shape:

```python
token = _current_agent.set(self._agent)
try:
    return self._graph.invoke(*args, **kwargs)
finally:
    _current_agent.reset(token)
```

The `try / finally` matters: even if the graph raises, the context is unwound. A subsequent unrelated invocation can never see a stale `Agent`.

`get_rv()` is the read side. It calls `_current_agent.get()` and converts the standard-library `LookupError` (raised when no value has been set for the current context) into a `RuntimeError` whose message tells the developer how to fix it ("wrap your graph with `runvault.init(...)` before invoking it"). No fallback, no implicit None — if you forgot to call `init`, the SDK refuses to operate on an unset agent.

The provider transports (`runvault.http.transport`) read the same `_current_agent` directly rather than going through `get_rv()`, because they want a `None` return on the "no agent" path so they can raise their own error message ("Call `runvault.init(...)` before invoking this `<provider>` LLM client"). Both paths end in the same place; only the messaging differs.

---

## How developers use it

In the common case, you never touch this module yourself — the adapter sets the value, the transport reads it, and your node code is unaware. The one situation where you call into it directly is when a node needs identity-aware behavior:

```python
from runvault import get_rv

def my_node(state):
    agent = get_rv()
    if agent.info.budget is not None and agent.budget_remaining() < 0.05:
        return {"warning": "low budget"}
    return run_normally(state)
```

A few practical notes:

- **`get_rv()` only works inside an invocation.** Calling it at module import, before `rv.init(...)`, or from a process-level callback that runs outside any graph will raise `RuntimeError`. That is intentional — there is genuinely no active agent at those points.
- **`ContextVar` propagates into spawned tasks** (`asyncio.create_task`, `loop.run_in_executor`, etc.) as of Python 3.7+. Async sub-tasks launched from inside a node automatically see the same `Agent`. Bare threads created with `threading.Thread(target=...)` do **not** inherit the context; if you spawn raw threads, you are responsible for propagating the value yourself.
- **Do not call `_current_agent.set(...)` from your own code.** It is named with a leading underscore for a reason — the adapter's set/reset discipline depends on owning both ends of the lifetime, and a stray `set` from your code will leak the agent into unrelated invocations.

---

## Reference

::: runvault.context
    options:
      show_source: false
      show_root_heading: true
      show_signature: true
