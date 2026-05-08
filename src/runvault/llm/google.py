"""Google LLM factories.

ChatGoogleGenerativeAI does not expose http_client/http_async_client constructor
parameters like OpenAI does. Instead, the underlying google-genai SDK accepts
HttpOptions.client_args / async_client_args which are forwarded verbatim to
httpx.Client() / httpx.AsyncClient(). We build a google.genai.Client with our
transport injected there, then overwrite the ChatGoogleGenerativeAI .client
field (which is None by default and settable on the Pydantic model).
"""

from __future__ import annotations

from typing import Any

from runvault.http.transport import (
    DEFAULT_TIMEOUT,
    PLACEHOLDER_BASE,
    RunVaultProviderAsyncTransport,
    RunVaultProviderTransport,
)


def ChatGoogleGenerativeAI(**kwargs: Any) -> Any:
    """Return a langchain_google_genai.ChatGoogleGenerativeAI routed through the RunVault proxy.

    Drop-in replacement for langchain_google_genai.ChatGoogleGenerativeAI.
    Change the import line — nothing else in the agent code needs to change.

    Raises:
        ImportError: If langchain-google-genai or google-genai is not installed.
    """
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI as _ChatGoogleGenerativeAI
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise ImportError(
            "ChatGoogleGenerativeAI requires langchain-google-genai and google-genai. "
            "Install with: pip install langchain-google-genai google-genai"
        ) from exc

    http_options = types.HttpOptions(
        base_url=f"{PLACEHOLDER_BASE}/google",
        client_args={
            "transport": RunVaultProviderTransport(provider="google"),
            "timeout": DEFAULT_TIMEOUT,
        },
        async_client_args={
            "transport": RunVaultProviderAsyncTransport(provider="google"),
            "timeout": DEFAULT_TIMEOUT,
        },
    )

    genai_client = genai.Client(
        api_key="rv-placeholder",
        http_options=http_options,
    )

    llm = _ChatGoogleGenerativeAI(
        google_api_key="rv-placeholder",
        **kwargs,
    )
    # Overwrite the internally-created client with our transport-configured one.
    # The field defaults to None and is not frozen, so this is safe.
    llm.client = genai_client
    return llm
