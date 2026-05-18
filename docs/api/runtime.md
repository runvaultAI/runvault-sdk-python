# Identity & Run

`Identity` and `Run` are the two runtime primitives the SDK exposes.

- **`Identity`** is long-lived. It owns the Ed25519 private key, the CA-signed certificate, and the proxy URL. Build wired LLMs from it. Open runs from it.
- **`Run`** is short-lived. A context manager that defines an execution scope and tags every outbound LLM call with a fresh `run_id`.

```python
identity = rv.register_agent(agent_id="research-v1", name="Research Agent")

with identity.run() as run:
    print(run.run_id)
    llm.invoke("...")
```

---

## `Identity`

You never construct an `Identity` directly — `rv.register_agent(...)` returns one.

### Attributes

| Attribute | Type | Notes |
|---|---|---|
| `agent_id` | `str` | Stable external identifier (e.g. `"research-v1"`). |
| `name` | `str` | Human-readable label. |
| `proxy_url` | `str` | Base proxy URL returned by the backend. |
| `security_policy` | `"hard" \| "soft"` | Default cross-identity guard mode. |

### Methods

#### `identity.run(security_policy=None)`

Returns a context manager that activates a fresh `Run`. Pure local operation — no backend round-trip.

`security_policy` (optional) overrides the identity's default for this scope only.

```python
with identity.run() as run:
    ...

async with identity.run() as run:
    ...
```

#### `identity.build_llm(BaseClass)`

Returns a dynamic subclass of `BaseClass` wired through the RunVault proxy. See [LLM Clients](../guides/llm-clients.md) for supported classes.

```python
RVChat = identity.build_llm(ChatOpenAI)
llm = RVChat(model="gpt-4o-mini")
```

Raises `TypeError` if `BaseClass` is not in the dispatch table.

#### `identity.refresh_credentials()`

Force a credential refresh. The transport calls this automatically on `401 CERTIFICATE_REVOKED`; you rarely need to call it yourself. See [Credential Rotation](../guides/credential-rotation.md).

Raises `AgentSuspendedError` if the agent has been suspended.

---

## `Run`

Created by `identity.run()`. The active `Run` is read from a `ContextVar` by the transport on every outbound request.

### Attributes

| Attribute | Type | Notes |
|---|---|---|
| `run_id` | `str` | Fresh UUID, generated on `__enter__`. |
| `agent_id` | `str` | Convenience accessor — pulls from the owning identity. |
| `identity` | `Identity` | The identity that opened this run. |
| `started_at` | `datetime` | UTC timestamp when the run was constructed. |

### Nesting

Nested runs are allowed and produce **independent** runs (each with its own `run_id`). The inner run shadows the outer; the outer resumes on exit, even on exception. There is no `parent_run_id` today.

```python
with identity.run() as outer:
    with identity.run() as inner:
        ...                # uses inner.run_id
    ...                    # uses outer.run_id
```

---

## `current_run()`

Module-level function that returns the active `Run` from the `ContextVar`.

```python
from runvault import current_run

def my_tool(query: str) -> str:
    run = current_run()           # raises NoActiveRunError outside a run
    log.info("tool fired in run %s", run.run_id)
    ...
```

| Spawning mechanism | Inherits `current_run()`? |
|---|---|
| `asyncio.create_task` | yes (PEP 567) |
| `threading.Thread` | **no** — copy the context manually |
| `concurrent.futures` pools | **no** — copy the context manually |

For threads:

```python
import contextvars, threading
ctx = contextvars.copy_context()
threading.Thread(target=lambda: ctx.run(worker)).start()
```

---

## Reference

::: runvault.identity.Identity
    options:
      show_source: false
      show_root_heading: true
      show_signature: true

::: runvault.identity.Run
    options:
      show_source: false
      show_root_heading: true
      show_signature: true

::: runvault.identity.current_run
    options:
      show_source: false
      show_root_heading: true
      show_signature: true
