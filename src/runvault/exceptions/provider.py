from __future__ import annotations

from .base import RunVaultError


class LLMProviderError(RunVaultError):
    """The upstream LLM provider returned an error response.

    This wraps provider HTTP errors so agents can catch all LLM failures
    from a single exception type without importing provider-specific SDKs.

    Attributes:
        provider:  Name of the provider (e.g. ``"openai"``, ``"anthropic"``).
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(message, **kwargs)
        self.provider = provider
