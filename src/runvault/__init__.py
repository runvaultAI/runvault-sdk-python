"""RunVault SDK.

Core imports are eager. LLM factory functions are loaded lazily on first
access so importing sdk never pulls in langchain, openai, anthropic, etc.
unless the caller actually uses them.

Usage:

    from runvault import RunVault, ChatOpenAI, get_rv
"""

from __future__ import annotations

import importlib

from runvault.client import RunVault
from runvault.context import get_rv
from runvault.exceptions import (
    AuthenticationError,
    BudgetExceededError,
    ConfigurationError,
    ConnectionError,
    LLMProviderError,
    ProxyError,
    RegistrationError,
    RunVaultError,
    TokenExpiredError,
)

__all__ = [
    # Entry point
    "RunVault",
    # Context
    "get_rv",
    # Exceptions
    "RunVaultError",
    "AuthenticationError",
    "BudgetExceededError",
    "ConfigurationError",
    "ConnectionError",
    "LLMProviderError",
    "ProxyError",
    "RegistrationError",
    "TokenExpiredError",
    # LLM factories (lazy)
    "ChatOpenAI",
    "OpenAI",
    "AsyncOpenAI",
    "ChatAnthropic",
    "Anthropic",
    "AsyncAnthropic",
    "ChatGoogleGenerativeAI",
]

# Maps factory name → module path. Loaded on first attribute access.
_LAZY: dict[str, str] = {
    "ChatOpenAI":              "runvault.llm.openai",
    "OpenAI":                  "runvault.llm.openai",
    "AsyncOpenAI":             "runvault.llm.openai",
    "ChatAnthropic":           "runvault.llm.anthropic",
    "Anthropic":               "runvault.llm.anthropic",
    "AsyncAnthropic":          "runvault.llm.anthropic",
    "ChatGoogleGenerativeAI":  "runvault.llm.google",
}


def __getattr__(name: str):
    if name in _LAZY:
        module = importlib.import_module(_LAZY[name])
        return getattr(module, name)
    raise AttributeError(f"module 'sdk' has no attribute {name!r}")
