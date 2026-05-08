"""RunVault LangGraph adapter.

Wraps a compiled LangGraph graph so that the RunVault Agent is set on the
ContextVar for the duration of each invocation. Nodes inside the graph
can then call get_rv() without any explicit state or parameter threading.

Usage:

    from runvault import RunVault, ChatOpenAI

    runvault = RunVault(api_key="rv_live_...", be_url="https://your-runvault-backend")
    llm = ChatOpenAI(model="gpt-4o-mini")

    agent = runvault.init(
        framework="langgraph",
        app=compiled_graph,
        agent_id="research-v1",
        name="Research Agent",
    )

    result = agent.invoke({"input": "..."})
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from runvault.context import _current_agent
from runvault.exceptions import RunVaultError

if TYPE_CHECKING:
    from runvault.runtime.agent import Agent


def _unwrap_rv_error(exc: BaseException) -> RunVaultError | None:
    """Walk the exception cause chain and return the first RunVaultError found.

    LLM SDKs (e.g. OpenAI) wrap exceptions raised inside httpx.send into
    their own types (APIConnectionError). This recovers the original
    RunVaultError so callers see a meaningful exception instead of a generic
    connection error.
    """
    current: BaseException | None = exc
    for _ in range(10):
        if isinstance(current, RunVaultError):
            return current
        cause = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        if cause is None or cause is current:
            break
        current = cause
    return None


class _LangGraphWrapper:
    """Sets the RunVault Agent on the ContextVar for each graph invocation."""

    def __init__(self, agent: Agent, graph: Any) -> None:
        self._agent = agent
        self._graph = graph

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        """Invoke the graph synchronously with RunVault context active."""
        token = _current_agent.set(self._agent)
        try:
            return self._graph.invoke(*args, **kwargs)
        except Exception as exc:
            rv_error = _unwrap_rv_error(exc)
            if rv_error is not None:
                raise rv_error
            raise
        finally:
            _current_agent.reset(token)

    def stream(self, *args: Any, **kwargs: Any):
        """Stream the graph synchronously with RunVault context active."""
        token = _current_agent.set(self._agent)
        try:
            yield from self._graph.stream(*args, **kwargs)
        except Exception as exc:
            rv_error = _unwrap_rv_error(exc)
            if rv_error is not None:
                raise rv_error
            raise
        finally:
            _current_agent.reset(token)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        """Invoke the graph asynchronously with RunVault context active."""
        token = _current_agent.set(self._agent)
        try:
            return await self._graph.ainvoke(*args, **kwargs)
        except Exception as exc:
            rv_error = _unwrap_rv_error(exc)
            if rv_error is not None:
                raise rv_error
            raise
        finally:
            _current_agent.reset(token)

    async def astream(self, *args: Any, **kwargs: Any):
        """Stream the graph asynchronously with RunVault context active."""
        token = _current_agent.set(self._agent)
        try:
            async for chunk in self._graph.astream(*args, **kwargs):
                yield chunk
        except Exception as exc:
            rv_error = _unwrap_rv_error(exc)
            if rv_error is not None:
                raise rv_error
            raise
        finally:
            _current_agent.reset(token)


def wrap_langgraph(agent: Agent, app: Any) -> None:
    """Wrap a compiled LangGraph graph and bind it to the Agent.

    Creates a _LangGraphWrapper and attaches it via agent._bind_adapter()
    so agent.invoke() / agent.stream() / etc. delegate to the wrapper.

    Args:
        agent: The Agent returned by RunVault.init().
        app:   A compiled LangGraph graph (result of StateGraph.compile()).
    """
    wrapper = _LangGraphWrapper(agent=agent, graph=app)
    agent._bind_adapter(wrapper)
