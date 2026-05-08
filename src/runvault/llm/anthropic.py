"""Anthropic LLM factories.

Each factory returns a real instance of the underlying LangChain or Anthropic
class, configured with a RunVaultProviderTransport so all requests are routed
through the RunVault proxy. The active Agent is looked up from the ContextVar
at request time — not at construction time — so module-level construction
works before runvault.init() is called.
"""

from __future__ import annotations

from typing import Any

import httpx

from runvault.http.transport import (
    DEFAULT_TIMEOUT,
    PLACEHOLDER_BASE,
    RunVaultProviderAsyncTransport,
    RunVaultProviderTransport,
)


def ChatAnthropic(**kwargs: Any) -> Any:
    """Return a langchain_anthropic.ChatAnthropic routed through the RunVault proxy.

    Drop-in replacement for langchain_anthropic.ChatAnthropic. Change the import
    line — nothing else in the agent code needs to change.

    Raises:
        ImportError: If langchain-anthropic is not installed.
    """
    try:
        from langchain_anthropic import ChatAnthropic as _ChatAnthropic
    except ImportError as exc:
        raise ImportError(
            "ChatAnthropic requires langchain-anthropic. "
            "Install with: pip install langchain-anthropic"
        ) from exc

    client = httpx.Client(
        transport=RunVaultProviderTransport(provider="anthropic"),
        timeout=DEFAULT_TIMEOUT,
    )
    async_client = httpx.AsyncClient(
        transport=RunVaultProviderAsyncTransport(provider="anthropic"),
        timeout=DEFAULT_TIMEOUT,
    )
    return _ChatAnthropic(
        api_key="rv-placeholder",
        base_url=f"{PLACEHOLDER_BASE}/anthropic",
        http_client=client,
        http_async_client=async_client,
        **kwargs,
    )


def Anthropic(**kwargs: Any) -> Any:
    """Return an anthropic.Anthropic client routed through the RunVault proxy.

    Drop-in replacement for the bare anthropic.Anthropic client.

    Raises:
        ImportError: If anthropic is not installed.
    """
    try:
        from anthropic import Anthropic as _Anthropic
    except ImportError as exc:
        raise ImportError(
            "Anthropic requires the anthropic package. "
            "Install with: pip install anthropic"
        ) from exc

    client = httpx.Client(
        transport=RunVaultProviderTransport(provider="anthropic"),
        timeout=DEFAULT_TIMEOUT,
    )
    return _Anthropic(
        api_key="rv-placeholder",
        base_url=f"{PLACEHOLDER_BASE}/anthropic",
        http_client=client,
        **kwargs,
    )


def AsyncAnthropic(**kwargs: Any) -> Any:
    """Return an anthropic.AsyncAnthropic client routed through the RunVault proxy.

    Raises:
        ImportError: If anthropic is not installed.
    """
    try:
        from anthropic import AsyncAnthropic as _AsyncAnthropic
    except ImportError as exc:
        raise ImportError(
            "AsyncAnthropic requires the anthropic package. "
            "Install with: pip install anthropic"
        ) from exc

    async_client = httpx.AsyncClient(
        transport=RunVaultProviderAsyncTransport(provider="anthropic"),
        timeout=DEFAULT_TIMEOUT,
    )
    return _AsyncAnthropic(
        api_key="rv-placeholder",
        base_url=f"{PLACEHOLDER_BASE}/anthropic",
        http_client=async_client,
        **kwargs,
    )
