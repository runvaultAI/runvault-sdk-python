# Configuration

The SDK reads `RUNVAULT_BE_URL` and `RV_CA_PUBLIC_KEY` from the environment when present. All other options are passed explicitly to `RunVault(...)` or `rv.register_agent(...)`.

## RunVault client

```python
from runvault import RunVault

rv = RunVault(
    api_key=os.environ["RUNVAULT_API_KEY"],
    timeout=10,                     # optional; seconds
)
```

| Parameter | Required | Default | Notes |
|---|---|---|---|
| `api_key` | yes | — | Project API key (`rv_live_…`). Used only at registration. |
| `be_url` | no | `RUNVAULT_BE_URL` env, else baked-in production URL | Override the backend base URL. Only set for staging or self-hosted deployments. |
| `timeout` | no | `10` | Applies to connect / write / pool phases of backend calls. Read timeout is unbounded. |

## `register_agent`

```python
identity = rv.register_agent(
    agent_id="research-v1",
    name="Research Agent",
    budget=1.0,
    budget_alert_threshold=80,
    security_policy="hard",
)
```

| Parameter | Required | Default | Notes |
|---|---|---|---|
| `agent_id` | yes | — | External agent identifier. Idempotent — same `agent_id` returns the same identity. |
| `name` | yes | — | Human-readable label. |
| `budget` | no | `None` | Hard spending cap in USD. Dashboard is authoritative after first registration. |
| `budget_alert_threshold` | no | `None` | Alert percentage (0–100). Dashboard is authoritative after first registration. |
| `security_policy` | no | `None` (server default `"hard"`) | Cross-identity guard mode. See [Authentication](authentication.md#cross-identity-guard). |

## Per-run override

`identity.run(security_policy=...)` overrides the identity's default for one execution scope:

```python
with identity.run(security_policy="soft"):
    ...
```

## Environment variables

| Variable | Purpose |
|---|---|
| `RUNVAULT_API_KEY` | Convention only — the SDK does not read this directly. Pass the value as `api_key`. |
| `RUNVAULT_BE_URL` | **Read directly by the SDK** when no `be_url` argument is supplied. Override the baked-in production backend URL for staging or self-hosted deployments. |
| `RV_CA_PUBLIC_KEY` | **Read directly by the SDK.** Base64-encoded Ed25519 RunVault CA public key. When set, every certificate is verified against this key on receipt. Strongly recommended in production. |

