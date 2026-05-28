# RunVault

`RunVault` is the SDK entry point. It holds the project API key and a small backend HTTP client, and produces `Identity` objects via `register_agent(...)`.

```python
from runvault import RunVault

rv = RunVault(api_key="rv_live_...")
```

Construction does no I/O. The first network call happens on `register_agent(...)`.

## Constructor

```python
RunVault(
    api_key: str,
    be_url: str | None = None,
    timeout: int = 10,
)
```

| Parameter | Required | Notes |
|---|---|---|
| `api_key` | yes | Project API key (`rv_live_…`). Used only at registration. |
| `be_url` | no | Override the backend base URL. Defaults to the `RUNVAULT_BE_URL` environment variable if set, otherwise the production endpoint baked into the SDK. Most users should leave this unset. |
| `timeout` | no | Seconds. Applies to connect / write / pool phases of backend calls. Read timeout is unbounded. |

## `register_agent(...)`

```python
identity = rv.register_agent(
    agent_id: str,
    name: str,
    budget: float | None = None,
    budget_alert_threshold: float | None = None,
    security_policy: Literal["hard", "soft"] | None = None,
) -> Identity
```

Registers an agent (or loads it if already registered) and returns a long-lived [`Identity`](runtime.md). Idempotent on `agent_id`.

On first registration the backend mints an Ed25519 keypair and signs a certificate with the project CA; both are cached to `~/.runvault/<agent_id>/`. On re-registration the existing material is loaded from disk.

**Dashboard precedence.** `budget`, `budget_alert_threshold`, and `security_policy` are honoured only on first registration. The dashboard is authoritative thereafter.

### Raises

| Exception | When |
|---|---|
| `AgentSuspendedError` | An administrator has suspended this agent. |
| `RegistrationError` | Backend rejected the request (network, 5xx, validation). |
| `AuthenticationError` | The project API key was rejected. |

---

## Reference

::: runvault.client.RunVault
    options:
      show_source: false
      show_root_heading: true
      show_signature: true
