# Credential Rotation

Certificates expire and may be rotated by an administrator at any time. The SDK handles rotation transparently — you should not need to write any code for it.

## How it works

1. An administrator rotates an agent's certificate (or its scope changes, which triggers a rotation).
2. The proxy's revocation cache picks up the change within ≤30 seconds.
3. The next in-flight LLM request gets back `401 CERTIFICATE_REVOKED`.
4. The transport detects the exact code, drains the response, and calls `identity.refresh_credentials()`.
5. `refresh_credentials()` round-trips to `POST /auth/agents/credentials/refresh`, gets a fresh keypair + certificate, updates the identity **in place**, and re-persists to `~/.runvault/<agent_id>/`.
6. The transport re-signs the same request with the new credentials and sends it once.

The retry is deliberately **one-shot**. There is no backoff loop and no second refresh.

## What you see from user code

Nothing. The original `llm.invoke(...)` call returns normally after the transparent retry. Your code never observes the `401` and never sees the refresh round-trip.

## When the SDK gives up

| Situation | Result |
|---|---|
| The second attempt also fails | The error propagates normally. |
| The refresh itself returns `403 AGENT_SUSPENDED` | `AgentSuspendedError` is raised. Admin action — the SDK will not retry. |

## Forcing a refresh manually

This is rarely needed because the transport handles rotation automatically, but you can force a refresh out-of-band:

```python
identity.refresh_credentials()
```

After this call returns, every subsequent outbound request from any LLM bound to this identity uses the new credentials. The swap is atomic — concurrent requests either see the full old or the full new keypair, never a half-rotated state.

## On-disk lifecycle

After a successful refresh, the files in `~/.runvault/<agent_id>/` are overwritten with the new key and certificate. The old material is not retained.
