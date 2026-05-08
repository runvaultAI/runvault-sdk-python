"""BackendClient — single httpx transport for all SDK→backend REST calls.

All modules that need to talk to the RunVault backend (registration,
budget queries, spending records, payments) use this client.  Error
parsing and typed exception raising are centralised here so callers
never have to touch raw HTTP.
"""

from __future__ import annotations

import httpx

from runvault.exceptions import AuthenticationError, ConnectionError, RegistrationError


class BackendClient:
    """Thin httpx wrapper for the RunVault backend.

    Args:
        be_url:  Backend base URL (e.g. http://backend:30080).
        timeout: Request timeout in seconds applied to connect + write.
                 Read timeout is left unlimited because some backend
                 calls (e.g. Lithic card issuance) may be slow.
    """

    def __init__(self, be_url: str, timeout: int = 10) -> None:
        self._be_url = be_url.rstrip("/")
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=float(timeout), read=None,
                                  write=float(timeout), pool=float(timeout)),
            headers={"User-Agent": "runvault-python/2.0"},
        )

    def post(self, path: str, body: dict) -> dict:
        """POST to the backend and return the parsed JSON body.

        Raises a typed RunVaultError on any non-200 response, connection
        failure, or timeout.
        """
        try:
            resp = self._client.post(f"{self._be_url}{path}", json=body)
        except httpx.ConnectError as exc:
            raise ConnectionError(
                f"Cannot reach RunVault backend at {self._be_url}: {exc}",
                user_string="Cannot reach the RunVault backend. Check your network connection.",
            ) from exc
        except httpx.TimeoutException as exc:
            raise ConnectionError(
                f"Request to RunVault backend timed out: {exc}",
                user_string="Request to RunVault backend timed out. Try again in a moment.",
            ) from exc
        return self._handle(resp)

    def get(self, path: str) -> dict:
        """GET from the backend and return the parsed JSON body."""
        try:
            resp = self._client.get(f"{self._be_url}{path}")
        except httpx.ConnectError as exc:
            raise ConnectionError(
                f"Cannot reach RunVault backend at {self._be_url}: {exc}",
                user_string="Cannot reach the RunVault backend. Check your network connection.",
            ) from exc
        except httpx.TimeoutException as exc:
            raise ConnectionError(
                f"Request to RunVault backend timed out: {exc}",
                user_string="Request to RunVault backend timed out. Try again in a moment.",
            ) from exc
        return self._handle(resp)

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle(self, resp: httpx.Response) -> dict:
        if resp.status_code == 200:
            return resp.json()
        msg, code, user_str = self._parse_error(resp)
        if resp.status_code == 401:
            raise AuthenticationError(
                msg or "Invalid or expired API key.",
                status_code=401,
                error_code=code or "INVALID_API_KEY",
                user_string=user_str or "Invalid or expired API key.",
            )
        if resp.status_code == 400:
            raise AuthenticationError(
                msg or "Bad request.",
                status_code=400,
                error_code=code,
                user_string=user_str or msg or "Bad request.",
            )
        raise RegistrationError(
            msg or f"Backend error (HTTP {resp.status_code}).",
            status_code=resp.status_code,
            error_code=code,
            user_string=user_str or f"RunVault backend returned an unexpected error.",
        )

    @staticmethod
    def _parse_error(resp: httpx.Response) -> tuple[str, str | None, str | None]:
        """Extract (internal_message, error_code, user_string) from an error response."""
        try:
            body = resp.json()
            detail = body.get("detail", {})
            if isinstance(detail, dict):
                return (
                    detail.get("detail", resp.text),
                    detail.get("code"),
                    detail.get("user_string", resp.text),
                )
            return str(detail) or resp.text, None, str(detail) or resp.text
        except Exception:
            return resp.text, None, resp.text
