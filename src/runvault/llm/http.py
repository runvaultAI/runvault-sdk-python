"""HTTP client helpers shared across LLM wirings.

Each wired LLM class is **bound to the Identity that built it** — the
transport receives the Identity at construction and uses its proxy URL
(for the host allowlist) and its key material (for signing). The bound
identity is fixed for the lifetime of the wired client; the active Run
is still read fresh from the ContextVar on every request so a single
client serves many runs.

Centralising client construction here keeps each wiring function
(``langchain.py``, ``crewai.py``) thin and avoids duplicating the
transport setup at four call sites.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from runvault.http.transport import (
    DEFAULT_TIMEOUT,
    RunVaultProviderAsyncTransport,
    RunVaultProviderTransport,
)

if TYPE_CHECKING:
    from runvault.identity import Identity


def make_sync_client(provider: str, bound_identity: "Identity") -> httpx.Client:
    """Return an ``httpx.Client`` whose transport routes through the proxy."""
    return httpx.Client(
        transport=RunVaultProviderTransport(
            provider=provider, bound_identity=bound_identity,
        ),
        timeout=DEFAULT_TIMEOUT,
    )


def make_async_client(provider: str, bound_identity: "Identity") -> httpx.AsyncClient:
    """Return an ``httpx.AsyncClient`` whose transport routes through the proxy."""
    return httpx.AsyncClient(
        transport=RunVaultProviderAsyncTransport(
            provider=provider, bound_identity=bound_identity,
        ),
        timeout=DEFAULT_TIMEOUT,
    )
