# Authentication

RunVault uses a two-step PKI flow. The long-lived **project API key** is used **only** at registration. After that, every outbound LLM call is authenticated with a fresh **EdDSA-signed JWT** plus a **CA-signed certificate** — neither of which can be replayed for more than five minutes.

## The flow at a glance

```
┌──────────────┐ rv.register_agent()  ┌──────────────┐
│   Project    │ ───── api_key ─────► │   Backend    │
│  API key     │                      │  signs cert  │
└──────────────┘ ◄── cert + keypair ──┴──────────────┘

┌──────────────┐  every LLM call      ┌──────────────┐
│   Identity   │ ── X-RV-Certificate ►│  RunVault    │
│ priv key in  │ ── X-RV-Agent-JWT  ──►│    proxy     │
│  memory      │ ◄────── response ────┴──────────────┘
```

## Step 1 — registration

`rv.register_agent(...)` performs a single `POST /auth/agents/runs`:

1. The backend mints an **Ed25519 keypair** and signs a **certificate** with the project CA.
2. The SDK persists both to `~/.runvault/<agent_id>/` with `0600` permissions.
3. If `RV_CA_PUBLIC_KEY` is set, the SDK verifies the certificate's CA signature before trusting it. (Absent ⇒ logs a warning and proceeds; acceptable for local dev, never for production.)

Registration is **idempotent**: a second call for the same `agent_id` reuses the on-disk credentials. If the backend reports the cert was rotated (`410 CERT_ROTATION_REQUIRED`), the SDK transparently calls `/credentials/refresh`.

## Step 2 — per-request signing

Every outbound LLM call goes through a custom `httpx` transport that:

1. Reads the active `Run` from a `ContextVar`. No run ⇒ `NoActiveRunError`.
2. Verifies the request is aimed at the configured proxy host (see [Host allowlist](#host-allowlist)).
3. Mints a fresh JWT with these claims:
    - `aud: "runvault-proxy"`
    - `iat` / `exp` — 5-minute TTL
    - `jti` — fresh UUID, lets the proxy de-duplicate
    - `agent_id`, `run_id`
4. Signs it with the agent's private key using EdDSA.
5. Attaches:
    - `X-RV-Certificate` — base64-encoded certificate (CA-signed)
    - `X-RV-Agent-JWT` — the JWT
6. Forwards the request.

The proxy verifies the CA signature on the certificate, then verifies the JWT signature using the public key inside that certificate, then checks the budget and forwards to the upstream provider.

## Credential rotation

When an administrator rotates an agent's certificate, the proxy's revocation cache picks up the change within ≤30 s and starts returning `401 CERTIFICATE_REVOKED` to in-flight requests. The transport handles this transparently:

1. Detect the exact code.
2. Drain the response body.
3. Call `identity.refresh_credentials()` — round-trips to `/auth/agents/credentials/refresh`, mints a new keypair + cert, updates the identity in place, and re-persists to disk.
4. Re-sign and retry the request **once**.

The retry is deliberately one-shot. If the second attempt also fails, the error propagates normally. If the agent has been suspended, `refresh_credentials()` raises `AgentSuspendedError` and no retry is attempted.

## Host allowlist

A wired `httpx.Client` could in principle be aimed at any URL by user code, exfiltrating valid signed JWTs. The transport refuses to attach RunVault credentials to any host other than the bound identity's proxy. Requests to other hosts raise `UntrustedHostError` before any signing happens.

## Cross-identity guard

Each wired LLM is bound to the identity that built it. On every outbound request, the transport compares the bound identity to the active run's identity:

```python
identity_a = rv.register_agent(agent_id="a", name="A")
identity_b = rv.register_agent(agent_id="b", name="B")

llm_a = identity_a.build_llm(ChatOpenAI)(model="gpt-4o-mini")
llm_b = identity_b.build_llm(ChatOpenAI)(model="gpt-4o-mini")

with identity_a.run():
    llm_b.invoke("...")     # ← bound to B, run owned by A ⇒ CrossIdentityError
```

Set the policy at registration (`security_policy="hard" | "soft"`, default `"hard"`) and override per run if you need to:

```python
with identity_a.run(security_policy="soft"):
    ...
```

In `"soft"` mode the SDK emits `CrossIdentityWarning` and proceeds — the **bound** identity is billed (the transport can only sign with the key it holds).

## What's on disk

```
~/.runvault/<agent_id>/
├── private.key          0600  raw 32-byte Ed25519 private key
└── certificate.json     0600  CA-signed cert (JSON)
```

The directory is `0700`. Anyone who can read `private.key` can impersonate the agent and spend its budget — treat the file like an SSH private key.

## Threat model in brief

The SDK is best-effort against accidents, not a security boundary against in-process adversaries. Python has no module-level isolation: any dependency in the process can read the private key, monkey-patch the transport, or bypass the guards. Defenses are layered:

| Threat | Caught at |
|---|---|
| Accidental cross-wiring | SDK — cross-identity guard |
| Exfiltration to attacker URL | SDK — host allowlist |
| JWT replay | Proxy — 5-min `exp` + `jti` window |
| Compromised dependency reads the private key | **Not defendable in-process.** Damage capped by the per-agent budget at the proxy. |

For hostile multi-tenancy, use process isolation. One identity = one trust zone.
