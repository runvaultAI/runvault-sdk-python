"""RunVault context variable.

Provides ambient access to the active Agent from inside framework nodes
without passing it through graph state.

Usage inside a node:

    from runvault import get_rv

    def my_node(state):
        agent = get_rv()
        # agent.info.id, agent.info.run_id, agent.budget_remaining(), etc.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runvault.runtime.agent import Agent

_current_agent: ContextVar[Agent] = ContextVar("_current_agent")


def get_rv() -> Agent:
    """Return the active Agent for the current execution context.

    Set automatically by the framework adapter wrapper around each
    graph invocation. Isolated per async task and per thread — concurrent
    invocations on the same process never see each other's Agent.

    Raises:
        RuntimeError: If called outside a graph wrapped via runvault.init().
    """
    try:
        return _current_agent.get()
    except LookupError:
        raise RuntimeError(
            "No active RunVault agent. "
            "Wrap your graph with runvault.init(framework=..., app=...) "
            "before invoking it."
        )
