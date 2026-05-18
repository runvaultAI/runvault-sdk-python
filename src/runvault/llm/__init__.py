"""LLM wiring — dispatch on base class to the right provider strategy.

Public entry point:

    from runvault.llm import build_llm
    RVChat = build_llm(identity, ChatOpenAI)

Most users reach this via ``identity.build_llm(BaseClass)`` instead.

Dispatch rules (in order):

  1. Exact match by ``<module>.<class_name>`` in the LangChain / OpenAI
     dispatch table — handles ChatOpenAI, ChatAnthropic, ChatGoogleGenerativeAI,
     OpenAI, AsyncOpenAI.
  2. MRO walk — supports user subclasses of the above.
  3. CrewAI BaseLLM (or subclass of it) — returns the RunVault CrewAI LLM
     class. Wired in :mod:`runvault.llm.crewai`.
  4. Otherwise raise ``TypeError``.

Adding a new framework means adding one entry to ``_DISPATCH`` or one
branch to ``build_llm`` — no other code in the SDK changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from runvault.llm.langchain import (
    wire_chat_anthropic,
    wire_chat_google,
    wire_chat_openai,
    wire_openai_client,
)

if TYPE_CHECKING:
    from runvault.identity import Identity


# Module-qualified class name → wiring strategy.
# Strings are used so this file never imports any LLM provider package
# at module load time — keeps ``import runvault`` cheap.
_DISPATCH: dict[str, Callable[[type, "Identity"], type]] = {
    "langchain_openai.chat_models.base.ChatOpenAI":              wire_chat_openai,
    "langchain_openai.chat_models.ChatOpenAI":                   wire_chat_openai,
    "langchain_anthropic.chat_models.ChatAnthropic":             wire_chat_anthropic,
    "langchain_google_genai.chat_models.ChatGoogleGenerativeAI": wire_chat_google,
    "openai.OpenAI":                                             wire_openai_client,
    "openai.AsyncOpenAI":                                        wire_openai_client,
    "openai._client.OpenAI":                                     wire_openai_client,
    "openai._client.AsyncOpenAI":                                wire_openai_client,
}


def build_llm(identity: "Identity", base_cls: type) -> type:
    """Return a dynamic subclass of ``base_cls`` wired through the proxy.

    The returned class behaves exactly like ``base_cls`` except that its
    constructor injects RunVault's proxy URL and httpx clients. All
    inherited methods (``.invoke()``, ``.stream()``, ``.bind_tools()``,
    etc.) keep working unchanged.

    Args:
        identity:  The Identity whose proxy URL and credentials to wire in.
        base_cls:  The LLM class to extend (e.g. ``ChatOpenAI``).

    Returns:
        A subclass of ``base_cls``.

    Raises:
        TypeError: If ``base_cls`` is not in the dispatch table and is
                   not a CrewAI ``BaseLLM`` subclass.
    """
    key = f"{base_cls.__module__}.{base_cls.__qualname__}"
    strategy = _DISPATCH.get(key)
    if strategy is not None:
        return strategy(base_cls, identity)

    # Walk MRO for parent classes that match — handles user subclasses
    # of the supported LLM classes (e.g. a custom ChatOpenAI wrapper).
    for parent in base_cls.__mro__[1:]:
        parent_key = f"{parent.__module__}.{parent.__qualname__}"
        if parent_key in _DISPATCH:
            return _DISPATCH[parent_key](base_cls, identity)

    # CrewAI BaseLLM — checked after the dispatch table because importing
    # crewai is expensive (and may not be installed).
    try:
        import crewai  # type: ignore[import-not-found]
    except ImportError:
        pass
    else:
        if isinstance(base_cls, type) and issubclass(base_cls, crewai.BaseLLM):
            from runvault.llm.crewai import wire_crewai
            return wire_crewai(base_cls, identity)

    raise TypeError(
        f"build_llm does not support {base_cls.__module__}.{base_cls.__qualname__}. "
        f"Supported base classes: {sorted(_DISPATCH)}, plus crewai.BaseLLM. "
        f"Use one of these or open a feature request."
    )


__all__ = ["build_llm"]
