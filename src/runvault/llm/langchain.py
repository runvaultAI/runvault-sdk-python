"""Wiring strategies for LangChain LLM classes and OpenAI-style clients.

Each function takes a base class (e.g. ``langchain_openai.ChatOpenAI``)
and an ``Identity``, and returns a dynamic subclass whose ``__init__``
injects the proxy URL and our RunVault-aware httpx clients.

The subclass otherwise inherits everything from its parent — including
``.invoke()``, ``.stream()``, ``.bind_tools()``, batching, retries.
Users construct it exactly like the original class.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from runvault.llm.http import make_async_client, make_sync_client

if TYPE_CHECKING:
    from runvault.identity import Identity


# Placeholder API key. The transport strips ``Authorization`` and adds
# ``X-RV-Certificate`` + ``X-RV-Agent-JWT`` instead, but the underlying
# SDKs (langchain-openai, openai-python) require *some* non-empty string
# for their api_key parameter or they refuse to construct.
_PLACEHOLDER_API_KEY = "rv-placeholder"


def wire_chat_openai(base_cls: type, identity: "Identity") -> type:
    """Wire ``langchain_openai.ChatOpenAI`` (or a subclass) for proxy routing.

    Returns a class identical to ``base_cls`` except that its
    constructor injects ``api_key``, ``base_url``, ``http_client``, and
    ``http_async_client`` if the user did not pass them.
    """
    base_url = f"{identity.provider_proxy_url('openai')}/v1"
    sync_client = make_sync_client("openai", bound_identity=identity)
    async_client = make_async_client("openai", bound_identity=identity)

    class _RVChatOpenAI(base_cls):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.setdefault("api_key", _PLACEHOLDER_API_KEY)
            kwargs.setdefault("base_url", base_url)
            kwargs.setdefault("http_client", sync_client)
            kwargs.setdefault("http_async_client", async_client)
            super().__init__(*args, **kwargs)

    _RVChatOpenAI.__name__ = f"RV{base_cls.__name__}"
    _RVChatOpenAI.__qualname__ = _RVChatOpenAI.__name__
    return _RVChatOpenAI


def wire_chat_anthropic(base_cls: type, identity: "Identity") -> type:
    """Wire ``langchain_anthropic.ChatAnthropic`` for proxy routing."""
    base_url = identity.provider_proxy_url("anthropic")
    sync_client = make_sync_client("anthropic", bound_identity=identity)
    async_client = make_async_client("anthropic", bound_identity=identity)

    class _RVChatAnthropic(base_cls):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.setdefault("api_key", _PLACEHOLDER_API_KEY)
            kwargs.setdefault("anthropic_api_url", base_url)
            kwargs.setdefault("default_headers", {})
            # ChatAnthropic doesn't accept http_client directly; the underlying
            # anthropic SDK uses its own. We replace it at the SDK level via
            # a custom client. TODO: tighten this when langchain-anthropic
            # adds an http_client parameter (already in the openai integration).
            super().__init__(*args, **kwargs)

    _RVChatAnthropic.__name__ = f"RV{base_cls.__name__}"
    _RVChatAnthropic.__qualname__ = _RVChatAnthropic.__name__
    return _RVChatAnthropic


def wire_chat_google(base_cls: type, identity: "Identity") -> type:
    """Wire ``langchain_google_genai.ChatGoogleGenerativeAI`` for proxy routing."""
    base_url = identity.provider_proxy_url("google")
    sync_client = make_sync_client("google", bound_identity=identity)

    class _RVChatGoogle(base_cls):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.setdefault("google_api_key", _PLACEHOLDER_API_KEY)
            kwargs.setdefault("client_options", {"api_endpoint": base_url})
            kwargs.setdefault("transport", "rest")
            super().__init__(*args, **kwargs)

    _RVChatGoogle.__name__ = f"RV{base_cls.__name__}"
    _RVChatGoogle.__qualname__ = _RVChatGoogle.__name__
    return _RVChatGoogle


def wire_openai_client(base_cls: type, identity: "Identity") -> type:
    """Wire ``openai.OpenAI`` (or AsyncOpenAI) — the bare OpenAI SDK client."""
    base_url = f"{identity.provider_proxy_url('openai')}/v1"
    # Pick sync or async client based on the base class. Both subclasses of
    # ``openai._base_client.BaseClient`` but we don't import that internal
    # path; just compare class names.
    is_async = "Async" in base_cls.__name__
    http_client = (
        make_async_client("openai", bound_identity=identity)
        if is_async
        else make_sync_client("openai", bound_identity=identity)
    )

    class _RVOpenAI(base_cls):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.setdefault("api_key", _PLACEHOLDER_API_KEY)
            kwargs.setdefault("base_url", base_url)
            kwargs.setdefault("http_client", http_client)
            super().__init__(*args, **kwargs)

    _RVOpenAI.__name__ = f"RV{base_cls.__name__}"
    _RVOpenAI.__qualname__ = _RVOpenAI.__name__
    return _RVOpenAI
