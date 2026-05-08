from __future__ import annotations


class RunVaultError(Exception):
    """Base class for all RunVault SDK exceptions.

    Attributes:
        status_code:  HTTP status code from the backend or proxy, if available.
        error_code:   Machine-readable code (e.g. ``BUDGET_CAP_REACHED``).
        user_string:  Human-readable message safe to display to end users.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        user_string: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.user_string = user_string if user_string is not None else message
