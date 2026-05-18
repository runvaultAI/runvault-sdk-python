# Changelog

The authoritative changelog lives in the repository root:
<https://github.com/runvaultAI/runvault-sdk-python/blob/main/CHANGELOG.md>

## 0.3.0 — current

- **New three-primitive API.** `RunVault` → `rv.register_agent(...)` → `Identity` → `with identity.run():`. The old `rv.init(framework=..., app=...)` flow has been removed.
- **`identity.build_llm(BaseClass)`** replaces the per-provider import factories. One method, dispatch on base class, supports LangChain / OpenAI / Anthropic / Google / CrewAI.
- **Cross-identity guard.** Transport now verifies the LLM's bound identity matches the active run's identity. Mismatches raise `CrossIdentityError` (`security_policy="hard"`, default) or emit `CrossIdentityWarning` (`"soft"`).
- **Host allowlist.** The transport refuses to attach RunVault credentials to any host other than the configured proxy. Raises `UntrustedHostError`.
- **`current_run()`** replaces `get_rv()`. Raises `NoActiveRunError` outside a `with identity.run():` block.
- **New public exceptions:** `CrossIdentityError`, `CrossIdentityWarning`, `UntrustedHostError`, `NoActiveRunError`.

See the [in-repo CHANGELOG](https://github.com/runvaultAI/runvault-sdk-python/blob/main/CHANGELOG.md) for the full history.
