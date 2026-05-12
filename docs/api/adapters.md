# Adapters

The `runvault.adapters` package is the SDK's extension point for agent frameworks. Each adapter teaches the SDK how to "wrap" a particular framework's runtime object so that the active `Agent` is bound to the `ContextVar` for every invocation. Today the package ships with one adapter — LangGraph — but the structure is designed to grow without changes to the rest of the SDK.

This page describes the registry, the contract a `wrap_*` function must satisfy, the LangGraph implementation that exists today, and how to read it as a template for adding new framework support.

---

## What this package is

The package consists of two things:

- A **registry** — `runvault.adapters.ADAPTERS` — that maps framework-name strings (the same strings users pass to `RunVault.init(framework=...)`) to their `wrap_*` callables.
- One adapter per supported framework, currently `runvault.adapters.langgraph`, which exposes a single `wrap_langgraph(agent, app)` function and a private `_LangGraphWrapper` class.

That is the entire package. There is no `Adapter` base class, no plugin loader, no entry-point discovery — adding a framework is two files of code and one line of registry mutation.

---

## The problem it solves

The SDK is built on a deliberate split: provider transports (`runvault.http.transport`) read the active `Agent` from a `ContextVar` at request time, but they do not know how to *set* that `ContextVar`. Setting it has to happen around every public invocation of the framework's runtime, because that is the only window during which a request might fire.

The exact shape of "the framework's runtime" varies. LangGraph's compiled `StateGraph` exposes `invoke`, `ainvoke`, `stream`, `astream`. Other frameworks have different method names, different async conventions, different streaming protocols. The SDK does not know in advance — and should not have to know — how to call any of them generically.

The adapter pattern resolves this by inverting the responsibility: the **framework adapter** knows the framework, and its job is to produce an opaque wrapper object that the runtime `Agent` can delegate to. The `Agent` itself stays framework-agnostic; the transport stays framework-agnostic; only the adapter holds the framework-specific knowledge.

The registry then turns the user's framework name (a stable, ergonomic string) into the right adapter at `init(...)` time, with a clear failure mode when a name is unknown.

---

## How it works internally

### The registry

```python
# runvault/adapters/__init__.py
from runvault.adapters.langgraph import wrap_langgraph

ADAPTERS: dict[str, callable] = {
    "langgraph": wrap_langgraph,
}
```

That is the full content of the package's `__init__.py`. `ADAPTERS` is the integration point with `RunVault.init(...)`:

```python
try:
    wrap = ADAPTERS[framework]
except KeyError:
    raise ValueError(
        f"Unknown framework {framework!r}. Supported: {sorted(ADAPTERS)}"
    )
```

Importantly, the lookup happens *before* any registration round-trip. A typo in the framework name fails fast, without minting an unused certificate or burning a `run_id`.

### The `wrap_*` contract

Every adapter function must satisfy three behavioural requirements:

1. **Signature.** Accepts exactly `(agent: Agent, app: Any) -> None`. The `agent` is the freshly constructed `Agent` returned by `_register_agent(...)`; the `app` is whatever the user passed for `app=` in `init(...)`.
2. **Side effect.** Calls `agent._bind_adapter(wrapper)` exactly once with a framework-specific wrapper object. After this call, `agent.invoke / ainvoke / stream / astream` route to `wrapper.invoke / ainvoke / stream / astream`.
3. **Return value.** Returns `None`. The wrapper's job is to mutate the `Agent`; `init(...)` will then return that same `Agent` to the caller.

The wrapper object itself must expose four methods (`invoke`, `ainvoke`, `stream`, `astream`) that:

- Wrap each call in a `_current_agent.set(...)` / `_current_agent.reset(token)` pair, using `try / finally` so the context is unwound even on error.
- Forward `*args` and `**kwargs` to the underlying framework runnable.
- Yield correctly in the streaming methods (a sync `yield from` for `stream`, an `async for ... yield` for `astream`).

### The LangGraph adapter

`runvault.adapters.langgraph` is the reference implementation. It does three things worth pointing out as a template:

**1. Each public method follows the same set/reset pattern.**

```python
def invoke(self, *args, **kwargs):
    token = _current_agent.set(self._agent)
    try:
        return self._graph.invoke(*args, **kwargs)
    except Exception as exc:
        rv_error = _unwrap_rv_error(exc)
        if rv_error is not None:
            raise rv_error
        raise
    finally:
        _current_agent.reset(token)
```

The four methods (`invoke`, `ainvoke`, `stream`, `astream`) repeat this shape. The `try` body is the only thing that differs between them.

**2. Exception unwrapping.**

LLM SDKs (especially OpenAI's) catch exceptions thrown inside `httpx.send` and wrap them in their own types — `openai.APIConnectionError` is the most common. That hides the underlying `RunVaultError` (`BudgetExceededError`, `TokenExpiredError`, …) the transport raised. The adapter walks the exception's `__cause__` / `__context__` chain (up to ten links to avoid pathological cycles) looking for the original `RunVaultError`, and re-raises that one if found. The result is that user code can catch `BudgetExceededError` directly even when the LangGraph call surface wraps it in a connection error.

**3. The `wrap_langgraph` entry point is tiny.**

```python
def wrap_langgraph(agent: Agent, app: Any) -> None:
    wrapper = _LangGraphWrapper(agent=agent, graph=app)
    agent._bind_adapter(wrapper)
```

Two lines. Everything else is in `_LangGraphWrapper`. This is the shape every future adapter should follow: a small entry-point function that satisfies the registry contract, plus a private wrapper class that owns the per-method set/reset and error-unwrapping logic.

---

## How developers use it

In normal code, you do not touch this package directly. You select an adapter implicitly by passing `framework="langgraph"` to `RunVault.init(...)`:

```python
agent = rv.init(
    framework="langgraph",
    app=compiled_graph,
    agent_id="research-v1",
    name="Research Agent",
)
```

The cases where you would interact with the package directly are uncommon but worth knowing:

**Adding a new framework.** Create `src/runvault/adapters/<framework>.py` following `langgraph.py` as the template: define a `_<Framework>Wrapper` class with the four context-managed methods, and a public `wrap_<framework>(agent, app)` function that constructs it and calls `agent._bind_adapter(...)`. Then add one entry to the `ADAPTERS` dict:

```python
from runvault.adapters.my_framework import wrap_my_framework

ADAPTERS: dict[str, callable] = {
    "langgraph": wrap_langgraph,
    "my_framework": wrap_my_framework,
}
```

That is the only mutation needed in the rest of the codebase. The `RunVault.init(...)` lookup, the typed exceptions, the transports, and the runtime `Agent` are all unchanged.

**Inspecting the registry at runtime.** Reading `ADAPTERS.keys()` is the supported way to discover which frameworks the installed SDK supports. The `ValueError` raised by `init(...)` for an unknown framework already produces a sorted list of supported names, so for user-facing errors you do not need to read the registry yourself.

**Wrapping an existing `Agent` after the fact.** The `Agent` class exposes a `.langgraph(app)` convenience that wraps a graph onto an already-registered `Agent`. It uses the same `wrap_langgraph` function under the hood. This pattern is rarer than the single-call `rv.init(framework=..., app=...)` form but is useful when registration and graph compilation are separated in time.

---

## Reference

::: runvault.adapters
    options:
      show_source: false
      show_root_heading: true
      show_signature: true
