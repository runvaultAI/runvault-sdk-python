# Exceptions

Every error the SDK raises is a subclass of `RunVaultError`.

| Exception | Meaning |
|---|---|
| `RunVaultError` | Base class for every SDK exception. |
| `NoActiveRunError` | An LLM call fired outside `with identity.run():`. |
| `CrossIdentityError` | LLM bound to one identity invoked under another identity's run (hard mode). |
| `CrossIdentityWarning` | Same situation, soft mode — emitted as a warning, not raised. |
| `UntrustedHostError` | Attempted to attach signed credentials to a non-proxy URL. |
| `BudgetExceededError` | Agent has spent its budget cap. |
| `TokenExpiredError` | Proxy rejected the JWT (`401`, `JWT_EXPIRED`, …). |
| `ProxyError` | Proxy returned a structured error not mapped to a more specific type. |
| `LLMProviderError` | Upstream provider (OpenAI, Anthropic, …) returned an error. |
| `AuthenticationError` | Backend rejected the API key. |
| `AgentSuspendedError` | Administrator suspended the agent. SDK will not retry. |
| `RegistrationError` | Backend registration / refresh failed for another reason. |
| `ConfigurationError` | Misconfigured SDK or environment. |
| `ConnectionError` | Network failure talking to the backend. (Distinct from Python's built-in `ConnectionError`.) |

Every `RunVaultError` carries three optional attributes:

| Attribute | Meaning |
|---|---|
| `status_code` | Original HTTP status from the backend or proxy, if any. |
| `error_code` | Machine-readable error code (e.g. `BUDGET_CAP_REACHED`). |
| `user_string` | A short, UI-friendly message safe to display. |

---

## Reference

::: runvault.exceptions.RunVaultError
    options:
      show_source: false
      show_root_heading: true

::: runvault.exceptions.NoActiveRunError
    options:
      show_source: false
      show_root_heading: true

::: runvault.exceptions.CrossIdentityError
    options:
      show_source: false
      show_root_heading: true

::: runvault.exceptions.CrossIdentityWarning
    options:
      show_source: false
      show_root_heading: true

::: runvault.exceptions.UntrustedHostError
    options:
      show_source: false
      show_root_heading: true

::: runvault.exceptions.BudgetExceededError
    options:
      show_source: false
      show_root_heading: true

::: runvault.exceptions.TokenExpiredError
    options:
      show_source: false
      show_root_heading: true

::: runvault.exceptions.ProxyError
    options:
      show_source: false
      show_root_heading: true

::: runvault.exceptions.LLMProviderError
    options:
      show_source: false
      show_root_heading: true

::: runvault.exceptions.AuthenticationError
    options:
      show_source: false
      show_root_heading: true

::: runvault.exceptions.AgentSuspendedError
    options:
      show_source: false
      show_root_heading: true

::: runvault.exceptions.RegistrationError
    options:
      show_source: false
      show_root_heading: true

::: runvault.exceptions.ConfigurationError
    options:
      show_source: false
      show_root_heading: true

::: runvault.exceptions.ConnectionError
    options:
      show_source: false
      show_root_heading: true
