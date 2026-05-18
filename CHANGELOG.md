# Changelog

All notable changes to the RunVault Python SDK are documented in this
file. The format follows [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

Pre-1.0 minor version bumps may contain breaking changes.

## [0.3.0] — 2026-05-18

### Added

- **Cross-identity guard.** The transport now verifies that the
  `Identity` an LLM was built from matches the active run's identity.
  Mismatches raise `CrossIdentityError` (`security_policy="hard"`,
  default) or emit `CrossIdentityWarning` (`security_policy="soft"`).
  Soft mode bills the *bound* identity — the only key the transport
  holds.
- **Host allowlist.** The transport refuses to attach
  `X-RV-Certificate` / `X-RV-Agent-JWT` to any request whose host
  isn't the configured proxy. Raises `UntrustedHostError`. Closes
  off accidental JWT exfiltration via a user-held `http_client()`.
- **`security_policy` parameter** on `RunVault.register_agent(...)`
  and per-run override on `identity.run(security_policy="soft")`.
  Honoured only on first registration; the backend is authoritative
  thereafter.
- **`Identity.security_policy`** and **`Run.identity`** /
  **`Run.effective_security_policy`** attributes.
- **CrewAI structured-output support.** `RunVaultCrewLLM.call()` and
  `.acall()` now accept `response_model=<PydanticClass>` and route
  through OpenAI's `chat.completions.parse()` API. Unknown kwargs are
  absorbed (`**kwargs`) so future CrewAI argument additions don't
  break the call.
- New public exceptions: `CrossIdentityError`, `UntrustedHostError`,
  `NoActiveRunError`. New `Warning` subclass: `CrossIdentityWarning`.

### Changed

- **Transport bound to the building Identity.**
  `RunVaultProviderTransport` / `RunVaultProviderAsyncTransport` now
  require a `bound_identity` constructor argument and sign every JWT
  with that identity's key (regardless of which run is active). This
  is what makes the cross-identity guard observable; it also fixes a
  silent mis-attribution bug where a mis-wired LLM would bill the
  wrong agent's budget.
- **`current_run()` raises `NoActiveRunError`** instead of bare
  `RuntimeError`. Catch-clauses that targeted `RuntimeError` need
  updating, or catch `RunVaultError` for broad handling.
- **Dependency floors tightened.** `openai>=1.40` (for `.parse()`)
  and `crewai>=0.130` (for the post-restructure module layout) on the
  matching extras. Older versions will fail at import time.

### Removed

- No public-API removals in this release.

### Known issues

- `langchain_anthropic.ChatAnthropic` does not yet accept an
  `http_client` constructor parameter the way `langchain_openai` does.
  Until it does, the Anthropic LangChain wrapper relies on
  `anthropic_api_url` only — same effective routing, slightly less
  precise interception surface than the OpenAI path.

### Migration notes

- If your code constructs the transport directly (most callers don't —
  it's normally built for you via `identity.build_llm(...)`), pass
  `bound_identity=identity` to the constructor.
- If you catch `RuntimeError` around `current_run()` calls, switch to
  `NoActiveRunError` or `RunVaultError`.
- No backend changes are required to upgrade the SDK alone; the SDK
  falls back to `security_policy="hard"` if the backend's registration
  response doesn't include the field.

## [0.2.1] — 2026-05-08

Earlier history not tracked here.
