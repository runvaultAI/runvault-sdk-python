from __future__ import annotations

from .base import RunVaultError


class BudgetExceededError(RunVaultError):
    """Agent's spending budget is exhausted — the proxy denied the request.

    Attributes:
        remaining_usd:  Balance remaining at time of denial (may be 0 or
                        slightly negative due to estimation rounding).
    """

    def __init__(
        self,
        message: str,
        *,
        remaining_usd: float | None = None,
        **kwargs,
    ) -> None:
        super().__init__(message, **kwargs)
        self.remaining_usd = remaining_usd


class TokenExpiredError(RunVaultError):
    """Proxy JWT has expired — call RunVault.init() again to get a new one."""


class ProxyError(RunVaultError):
    """Generic proxy-level error (e.g. version mismatch, proxy misconfiguration)."""
