# Runtime

The `runvault.runtime` package contains a single class — `Agent` — and that class is what `RunVault.init(...)` returns. Everything you do at runtime, from invoking a graph to checking the budget remaining, happens through an `Agent` instance.

This page describes what an `Agent` actually holds, why it owns more state than you might expect for a "thin handle," and the lifecycle that runs the moment its credentials become stale.

---

## What this module is

`Agent` is the runtime context object for a single registered agent. After `RunVault.init(framework=..., app=...)` returns, an `Agent` instance carries enough state to:

- Mint signed requests to the RunVault proxy (private key, certificate, proxy URL, identity claims).
- Refresh those credentials on its own when the proxy reports they have been revoked.
- Delegate `invoke` / `stream` / `ainvoke` / `astream` calls to the framework adapter that was bound during `init(...)`.
- Round-trip back to the backend's credential refresh endpoint without requiring `RunVault` to be re-instantiated (which is why it stores the original API key and external agent ID).

The class is **not** a connection pool, a budget cache, or a long-lived runtime — it is a per-run handle. A new `Agent` is created on every `RunVault.init(...)` call, even if the same `agent_id` is reused (the underlying DB row is the same; the `Agent` instance and its `run_id` are not).

---

## The problem it solves

The transport layer (`runvault.http.transport`) needs to mint a fresh JWT and inject a certificate on every outbound LLM request. To do that, it needs four things at request time:

1. The agent's **private key bytes** (to sign the JWT).
2. The agent's **certificate** (to put in the `X-RV-Certificate` header).
3. The agent's **identity claims** — `agent_id` and `run_id` — to embed in the JWT payload.
4. The **proxy URL** to rewrite the request's URL.

All four come from the registration response, and all four need to survive across the entire lifetime of the run — across many invocations of many graph nodes, possibly across coroutine context switches and thread boundaries. The `Agent` is where they live.

At the same time, when the proxy reports `401 CERTIFICATE_REVOKED`, the SDK has to **mutate those credentials in place** (so the next request, possibly already mid-flight, uses the new keys) and re-persist them to disk, without losing the identity claims that are not affected by rotation (`agent_id`, `name`, the project's `api_key`). That mutation has to happen on a single owner. `Agent` is that owner.

If you split this state across the transport, the registration module, and a separate cache, every credential refresh becomes a multi-step coordination problem. Centralising it on `Agent` makes the refresh path one method call, which is exactly what `runvault.http.transport` does today.

---

## How it works internally

### Construction

`Agent` is constructed only by `RunVault._register_agent(...)`. You never instantiate it yourself. The constructor takes everything needed to operate **and** everything needed to recover:

| Field | Purpose |
|---|---|
| `info: AgentInfo` | Immutable identity for this run — agent UUID, run UUID, proxy URL, provider, budget caps. |
| `_http: BackendClient` | The same backend client the parent `RunVault` is using. Reused for `/credentials/refresh`. |
| `_api_key`, `_external_agent_id`, `_name` | Stored so `refresh_credentials()` can rebuild the same payload `register()` would have used. |
| `private_key_bytes: bytes \| None` | Raw 32-byte Ed25519 private key — read on every request by the transport. |
| `certificate_b64: str \| None` | Base64-encoded canonical-JSON certificate, ready to drop into `X-RV-Certificate`. |
| `_adapter: Any` | Bound later by `_bind_adapter(...)`. The framework wrapper that intercepts `invoke` / `stream` / `ainvoke` / `astream`. |

`certificate_b64` is precomputed at construction time by `_encode_cert(...)` rather than re-encoded per request: the canonical JSON form (`sort_keys=True, separators=(",", ":")`) is what the proxy expects, and turning it into the base64-encoded header value is exactly the same on every call. Encoding it once saves a small but per-request cost on the hot path.

### Framework binding

`_bind_adapter(adapter)` attaches a framework wrapper (currently only `runvault.adapters.langgraph._LangGraphWrapper`) to the `Agent`. After this call, the public delegation methods route to the wrapper:

- `Agent.invoke(...)` → `wrapper.invoke(...)` → sets `_current_agent` → calls `graph.invoke(...)` → resets `_current_agent`.
- Same shape for `stream`, `ainvoke`, `astream`.

If you call `Agent.invoke(...)` before any adapter is bound, `_assert_adapter()` raises a `RuntimeError` that points you at `runvault.init(framework=..., app=...)`. There is no implicit fallback or "raw passthrough" — an unbound `Agent` is not a useful thing.

The `langgraph(app)` method is a convenience for the rarer pattern where registration and framework binding are separated in time: you call `_register_agent` once at startup, then later bind a graph. It is a thin wrapper around `wrap_langgraph(self, app)` that returns `self` for chaining.

### Credential refresh

`refresh_credentials()` is what closes the loop with the transport layer. The flow is:

1. The transport detects `401 CERTIFICATE_REVOKED` on an outbound LLM request.
2. It calls `agent.refresh_credentials()`.
3. `refresh_credentials` calls `runvault.auth.registration.refresh(...)` with the stored `api_key`, `external_agent_id`, `name`, and current budget caps.
4. The backend returns a fresh `AgentInfo`, fresh private key bytes, and a fresh certificate.
5. `refresh_credentials` does an **atomic in-place swap**: `self.info`, `self.private_key_bytes`, and `self.certificate_b64` are all updated.
6. The transport reads the new values when it builds the retry request.

The atomicity is important. The transport reads `private_key_bytes` and `certificate_b64` on every request without locking; the assumption is that either the full old pair or the full new pair is observed, never half. Because the swap is three simple attribute assignments on a single object in a CPython interpreter, that assumption holds. The credentials on disk are also updated as a side effect of the refresh call (via `save_credentials` inside `registration._persist_fresh_credentials`).

If the refresh itself fails because the agent has been suspended, `refresh_credentials` raises `AgentSuspendedError` and the transport propagates it without retrying. This is the one failure mode the SDK cannot recover from automatically.

### Context manager support and `close()`

`Agent` supports the context manager protocol:

```python
with rv.init(framework="langgraph", app=graph, ...) as agent:
    result = agent.invoke({"input": "..."})
```

`__exit__` calls `close()`, which today is a deliberate no-op. The hook exists so that future versions can attach explicit run-shutdown behavior (flush pending spend records, signal end-of-run to the backend, etc.) without changing the public API surface.

---

## How developers use it

In normal code, you treat the `Agent` returned by `init(...)` as a slightly richer drop-in for your compiled framework graph:

```python
agent = rv.init(framework="langgraph", app=graph,
                agent_id="research-v1", name="Research Agent")

# Sync
result = agent.invoke({"input": "..."})
for chunk in agent.stream({"input": "..."}):
    print(chunk)

# Async
result = await agent.ainvoke({"input": "..."})
async for chunk in agent.astream({"input": "..."}):
    print(chunk)
```

Identity-aware code inside a node reads the same `Agent` via [`get_rv()`](context.md). The handful of properties on `agent.info` (especially `info.id`, `info.run_id`, `info.budget`, `info.proxy_url`) are the right places to look for run-scoped facts.

A few practical guidelines that follow directly from the implementation:

- **Use one `Agent` per run.** Calling `init(...)` again with the same `agent_id` is a *new* `Agent` with a *new* `run_id`. Don't reach for the old one after re-initialising.
- **Do not mutate `info`, `private_key_bytes`, or `certificate_b64` yourself.** They are written by `refresh_credentials` and read on every outbound request — outside writes would race against the transport.
- **Catch `AgentSuspendedError` if you want a graceful exit path.** It is the only exception the SDK refuses to retry through and the only one that signals a genuine administrative decision. All other errors are either transient (network) or already typed for branching (`BudgetExceededError`, `TokenExpiredError`, …).

---

## Reference

::: runvault.runtime.Agent
    options:
      show_source: false
      show_root_heading: true
      show_signature: true
