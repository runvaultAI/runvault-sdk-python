"""RunVault SDK.

Public API:

    from runvault import RunVault, current_run

    rv = RunVault(api_key="rv_live_...", be_url="https://your-backend")
    identity = rv.register_agent(agent_id="research-v1", name="Research Agent")

    from langchain_openai import ChatOpenAI
    RVChat = identity.build_llm(ChatOpenAI)

    with identity.run():
        result = compiled_graph.invoke({"input": "..."})

    # Inside graph nodes or tool functions:
    from runvault import current_run
    def my_tool(...):
        run = current_run()    # raises if outside a `with identity.run():` block
        ...
"""

from __future__ import annotations

from runvault.client import RunVault
from runvault.exceptions import (
    AgentSuspendedError,
    AuthenticationError,
    BudgetExceededError,
    ConfigurationError,
    ConnectionError,
    CrossIdentityError,
    CrossIdentityWarning,
    LLMProviderError,
    NoActiveRunError,
    ProxyError,
    RegistrationError,
    RunVaultError,
    TokenExpiredError,
    UntrustedHostError,
)
from runvault.identity import Identity, Run, current_run

__all__ = [
    # Entry point
    "RunVault",
    # Primitives
    "Identity",
    "Run",
    "current_run",
    # Exceptions
    "RunVaultError",
    "AgentSuspendedError",
    "AuthenticationError",
    "BudgetExceededError",
    "ConfigurationError",
    "ConnectionError",
    "CrossIdentityError",
    "CrossIdentityWarning",
    "LLMProviderError",
    "NoActiveRunError",
    "ProxyError",
    "RegistrationError",
    "TokenExpiredError",
    "UntrustedHostError",
]
