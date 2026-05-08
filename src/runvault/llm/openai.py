"""OpenAI LLM factories.

Each factory returns a real instance of the underlying LangChain or OpenAI
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


def ChatOpenAI(**kwargs: Any) -> Any:
    """Return a langchain_openai.ChatOpenAI routed through the RunVault proxy.

    Drop-in replacement for langchain_openai.ChatOpenAI. Change the import
    line — nothing else in the agent code needs to change.

    All constructor kwargs are forwarded verbatim to the underlying class,
    preserving .bind(), .with_retry(), streaming, and tool use.

    Raises:
        ImportError: If langchain-openai is not installed.
    """
    try:
        from langchain_openai import ChatOpenAI as _ChatOpenAI
    except ImportError as exc:
        raise ImportError(
            "ChatOpenAI requires langchain-openai. "
            "Install with: pip install langchain-openai"
        ) from exc

    client = httpx.Client(
        transport=RunVaultProviderTransport(provider="openai"),
        timeout=DEFAULT_TIMEOUT,
    )
    async_client = httpx.AsyncClient(
        transport=RunVaultProviderAsyncTransport(provider="openai"),
        timeout=DEFAULT_TIMEOUT,
    )
    return _ChatOpenAI(
        api_key="rv-placeholder",
        base_url=f"{PLACEHOLDER_BASE}/openai/v1",
        http_client=client,
        http_async_client=async_client,
        **kwargs,
    )


def OpenAI(**kwargs: Any) -> Any:
    """Return an openai.OpenAI client routed through the RunVault proxy.

    Drop-in replacement for the bare openai.OpenAI client.

    Raises:
        ImportError: If openai is not installed.
    """
    try:
        from openai import OpenAI as _OpenAI
    except ImportError as exc:
        raise ImportError(
            "OpenAI requires the openai package. "
            "Install with: pip install openai"
        ) from exc

    client = httpx.Client(
        transport=RunVaultProviderTransport(provider="openai"),
        timeout=DEFAULT_TIMEOUT,
    )
    return _OpenAI(
        api_key="rv-placeholder",
        base_url=f"{PLACEHOLDER_BASE}/openai/v1",
        http_client=client,
        **kwargs,
    )


def AsyncOpenAI(**kwargs: Any) -> Any:
    """Return an openai.AsyncOpenAI client routed through the RunVault proxy.

    Raises:
        ImportError: If openai is not installed.
    """
    try:
        from openai import AsyncOpenAI as _AsyncOpenAI
    except ImportError as exc:
        raise ImportError(
            "AsyncOpenAI requires the openai package. "
            "Install with: pip install openai"
        ) from exc

    async_client = httpx.AsyncClient(
        transport=RunVaultProviderAsyncTransport(provider="openai"),
        timeout=DEFAULT_TIMEOUT,
    )
    return _AsyncOpenAI(
        api_key="rv-placeholder",
        base_url=f"{PLACEHOLDER_BASE}/openai/v1",
        http_client=async_client,
        **kwargs,
    )
