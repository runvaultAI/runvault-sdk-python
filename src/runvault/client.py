"""RunVault SDK entry point.

Usage:

    from runvault import RunVault, ChatOpenAI

    rv = RunVault(
        api_key="rv_live_...",
        be_url="https://your-runvault-backend",
    )
    llm = ChatOpenAI(model="gpt-4o-mini")
    graph = build_graph(llm)

    agent = rv.init(framework="langgraph", app=graph,
                    agent_id="research-v1", name="Research Agent")
    result = agent.invoke({"input": "..."})
"""

from __future__ import annotations

import logging
from typing import Any

from runvault.adapters import ADAPTERS
from runvault.auth.registration import register
from runvault.http.backend import BackendClient
from runvault.runtime.agent import Agent

log = logging.getLogger(__name__)


class RunVault:
    """RunVault SDK client.

    Args:
        api_key: Active RunVault project API key (rv_live_…). Always required.
        be_url:  Base URL of the RunVault backend. Always required.
        timeout: HTTP request timeout in seconds for backend calls.
    """

    def __init__(
        self,
        api_key: str,
        be_url: str,
        timeout: int = 10,
    ) -> None:
        self._api_key = api_key
        self._http = BackendClient(be_url=be_url, timeout=timeout)

    def _register_agent(
        self,
        agent_id: str,
        name: str,
        budget: float | None = None,
        budget_alert_threshold: float | None = None,
    ) -> Agent:
        """Register an agent and obtain a proxy JWT (internal).

        Idempotent — the backend returns the existing agent record but always
        issues a fresh run_id and JWT, scoping each execution for spend tracking.
        Called by init(). Not part of the public API in v1.
        """
        info, private_key_bytes, certificate = register(
            http=self._http,
            api_key=self._api_key,
            agent_id=agent_id,
            name=name,
            budget=budget,
            budget_alert_threshold=budget_alert_threshold,
        )
        return Agent(
            info=info,
            http=self._http,
            # api_key + external_agent_id + name are needed by the Agent if
            # it has to call /credentials/refresh after the admin rotates
            # this agent's certificate. Storing them on the Agent keeps the
            # transport layer slim — it just calls agent.refresh_credentials().
            api_key=self._api_key,
            external_agent_id=agent_id,
            name=name,
            private_key_bytes=private_key_bytes,
            certificate=certificate,
        )

    def init(
        self,
        framework: str,
        app: Any,
        agent_id: str,
        name: str,
        budget: float | None = None,
        budget_alert_threshold: float | None = None,
    ) -> Agent:
        """Register an agent and wrap a framework graph in one call.

        Args:
            framework: Framework name (e.g. "langgraph").
            app:       Compiled graph or runnable to wrap.
            agent_id:  Stable identifier for this agent.
            name:      Human-readable name.
            budget:    Optional spending cap in USD.
            budget_alert_threshold: Optional alert percentage (0–100).

        Returns:
            Agent ready to invoke.

        Raises:
            ValueError: If the framework is not supported.
        """
        try:
            wrap = ADAPTERS[framework]
        except KeyError:
            raise ValueError(
                f"Unknown framework {framework!r}. "
                f"Supported: {sorted(ADAPTERS)}"
            )
        agent = self._register_agent(
            agent_id=agent_id,
            name=name,
            budget=budget,
            budget_alert_threshold=budget_alert_threshold,
        )
        wrap(agent, app)
        return agent
