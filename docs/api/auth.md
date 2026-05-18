# Auth

The `runvault.auth` package implements the cryptographic identity layer that turns a project API key into a per-agent, per-request, verifiable presence on the wire. It is split into three modules — `registration`, `credentials`, and `signer` — that map to the three phases of an agent's lifetime: getting an identity, keeping it on disk, and using it on every outbound call.

This page explains why the layer is split that way, what each module is responsible for, and where the code that you (the developer) actually call sits inside it. Most of `runvault.auth` runs silently behind `RunVault.init(...)` and the provider transports; you only touch it directly for verification, debugging, or when writing tests.

---

## What this package is

The package is the SDK side of a two-step PKI flow:

1. **Registration** turns a long-lived RunVault project API key plus an agent ID into a *short-lived* Ed25519 keypair and a CA-signed certificate. The keypair lives on the agent's disk; the certificate is what proves to the RunVault proxy that this keypair is allowed to act on behalf of the agent.
2. **Per-request signing** uses that keypair to mint a fresh EdDSA-signed JWT for every single outbound LLM call. The JWT carries the agent ID, the run ID, a fresh `jti`, and an `exp` 5 minutes in the future. The certificate goes along for the ride in a header.

The three modules implement those phases:

| Module | Phase | Public symbols |
|---|---|---|
| `runvault.auth.registration` | Obtain or recover credentials from the backend. | `register`, `refresh`, `AgentInfo` |
| `runvault.auth.credentials` | Persist, load, and verify the credentials on disk. | `save_credentials`, `load_credentials`, `verify_certificate` |
| `runvault.auth.signer` | Mint per-request EdDSA JWTs from the loaded private key. | `create_agent_jwt` |

---

## The problem it solves

A traditional pattern would give the agent a long-lived API key — either the RunVault key directly, or a bearer token derived from it — and let it call providers on its own. That has three structural failures:

- **A leaked key compromises the entire agent's budget forever.** There is no rotation horizon.
- **There is no way to scope a single execution.** Spending tracking has to be inferred from request metadata rather than carried in the credential itself.
- **Revocation is eventually-consistent at best.** Once a long-lived token is in flight, cancelling it requires the proxy to consult a denylist on every request.

The RunVault auth package replaces the long-lived bearer model with three short-lived artefacts:

- A **private key**, scoped to one agent, stored locally with `0600` permissions, never transmitted.
- A **certificate**, signed by the RunVault CA, that asserts "this public key belongs to this agent, in this scope, until this expiry."
- A **per-request JWT**, signed with the private key and valid for five minutes, that links a specific call to a specific run.

The proxy verifies the CA signature on the certificate (proof of identity), then verifies the JWT signature using the public key inside that certificate (proof of liveness). Nothing the agent sends over the wire is reusable: the JWT expires within minutes, and revoking the certificate disables future signatures within the proxy's cache TTL (≤ 30 seconds).

---

## How it works internally

### `registration` — obtaining and recovering credentials

`register(http, api_key, agent_id, name, budget, budget_alert_threshold)` is the entry point used by `RunVault.init(...)`. It performs a single `POST /auth/agents/runs`, but it has to handle four distinct backend response shapes:

| HTTP / code | Meaning | What `register` does |
|---|---|---|
| `200` with `agent_private_key` + `certificate` | First-time registration. | Verify CA signature (if `RV_CA_PUBLIC_KEY` is set), persist to disk, return raw bytes. |
| `200` without `agent_private_key` | Idempotent re-registration; backend says "you already have valid credentials." | Load credentials from disk. If the disk is empty (lost volume), fall back to `refresh(...)`. |
| `410 CERT_ROTATION_REQUIRED` | Admin rotated the certificate. | Call `refresh(...)` and return its result. |
| `403 AGENT_SUSPENDED` | Admin suspended the agent. | Raise `AgentSuspendedError` — no automatic recovery. |

The `refresh(...)` function exists as a peer to `register(...)` rather than a private helper because the SDK calls it from **two** places: from inside `register` when the backend reports rotation, and directly from `runvault.runtime.agent.Agent.refresh_credentials()` when the **proxy** later returns `401 CERTIFICATE_REVOKED` on a live request. Both call sites hand it the same payload shape, both want the same return value, and both want the same `AgentSuspendedError` semantics — so it is one function.

`AgentInfo` is the small dataclass returned alongside the raw key/cert pair. It carries every immutable fact about this run: the agent's DB UUID, the `run_id` (fresh on every call), the proxy URL, the LLM provider, and the budget caps that scope the run.

### `credentials` — disk persistence and CA verification

The credentials module is responsible for **the only durable, on-disk state the SDK creates.** It lives at `~/.runvault/<agent_id>/` and contains two files:

| File | Contents | Permissions |
|---|---|---|
| `private.key` | Raw 32-byte Ed25519 private key (binary). | `0600` |
| `certificate.json` | The signed certificate dict, JSON-encoded. | `0600` |

The directory itself is `0700`. These match the convention used by SSH (`~/.ssh/id_ed25519`) and exist for the same reason: anyone who reads the private key can impersonate the agent, mint JWTs, spend its budget, and sign fraudulent statements. The OS-level permission bit is the last line of defense.

`save_credentials(...)` writes both files atomically (within the limits of POSIX) and is called only from `_persist_fresh_credentials` inside `registration.py`. `load_credentials(...)` is the lookup used during idempotent re-registration. It returns `None` (rather than raising) when the files are missing, because callers — especially `register()` — want to *decide* whether absence is an error or a signal to call `refresh`.

`verify_certificate(certificate, ca_public_key_b64)` is the one credentials function that you might call manually. It performs two checks:

1. The certificate's `signature` field is a valid Ed25519 signature, made by the CA's private key, over the canonical JSON form of the rest of the certificate (`json.dumps(payload, sort_keys=True, separators=(",", ":"))`).
2. The certificate's `expires_at` is in the future when measured against `datetime.now(timezone.utc)`.

Either failure raises `CertificateVerificationError`. The function is invoked automatically by `_persist_fresh_credentials` after every registration **when `RV_CA_PUBLIC_KEY` is set in the environment**. When the variable is absent, registration logs a warning and proceeds without verification — acceptable for local development, never for production.

### `signer` — per-request EdDSA JWT minting

`create_agent_jwt(agent_id, run_id, private_key_bytes)` is the smallest module in the package and the most performance-sensitive: it is called once for **every** outbound LLM request, by the `RunVaultProviderTransport` in `runvault.http.transport`.

The implementation does not use a third-party JWT library. It builds the three base64url segments manually:

```
header  = base64url({"alg":"EdDSA","typ":"JWT"})        # precomputed at module load
payload = base64url({                                   # fresh on every call
    "aud":      "runvault-proxy",
    "iat":      now,
    "exp":      now + 300,
    "jti":      uuid4(),
    "agent_id": <agent UUID>,
    "run_id":   <run UUID>,
})
sig     = base64url(Ed25519_sign(private_key, header + "." + payload))
token   = f"{header}.{payload}.{sig}"
```

Three design choices worth knowing:

- **Fixed audience `runvault-proxy`.** The proxy rejects tokens that don't carry this audience, so a JWT minted for one tenant cannot be replayed against another.
- **Five-minute lifetime.** Long enough to survive normal request latency; short enough that a captured token is rapidly useless.
- **Fresh `jti` per call.** Lets the proxy or an auditor de-duplicate requests if needed, and is the right shape for any future replay-protection cache.

The function is pure: same inputs produce the same `header.payload.signature` triple within the same second. Callers do not (and must not) cache the output — call it once per outbound request.

---

## How developers use it

In the vast majority of agent code, you never import from `runvault.auth` at all. `RunVault.init(...)` calls `register(...)`, the transport calls `create_agent_jwt(...)`, and the runtime `Agent.refresh_credentials(...)` calls `refresh(...)`. Three situations bring you to this layer directly:

**Verifying credentials already on disk.** Useful in deployments where you want to confirm the agent's identity is well-formed before it serves traffic:

```python
import os
from runvault.auth.credentials import load_credentials, verify_certificate

creds = load_credentials("research-v1")
if creds is None:
    raise SystemExit("no credentials on disk — register first")

_, certificate = creds
verify_certificate(certificate, os.environ["RV_CA_PUBLIC_KEY"])
print("certificate is valid")
```

**Forcing a credential refresh out-of-band.** If your operational runbook calls for rotating credentials on a schedule rather than waiting for the proxy to detect revocation, you can call `refresh` directly with the same `BackendClient` the SDK already uses. In practice this is rarely needed — the transport-layer recovery in `runvault.http.transport` handles rotation transparently.

**Testing.** Both `verify_certificate` and `create_agent_jwt` are pure and have no I/O. They are easy to call from unit tests with a fixture keypair to validate that your downstream code accepts the credentials shape correctly.

In all three cases, treat the private key bytes returned by `load_credentials` as you would treat any other private key: never log it, never serialize it across a process boundary, never check it into version control.

---

## Reference

### Registration

::: runvault.auth.registration
    options:
      show_source: false
      show_root_heading: true
      show_signature: true

### Credentials

::: runvault.auth.credentials
    options:
      show_source: false
      show_root_heading: true
      show_signature: true

### Signer

::: runvault.auth.signer
    options:
      show_source: false
      show_root_heading: true
      show_signature: true
