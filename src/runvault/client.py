"""RunVault SDK entry point.

Usage:

    from runvault import RunVault

    rv = RunVault(api_key="rv_live_...", be_url="https://your-backend")

    # 1. Register the agent — provisions cert + private key once.
    identity = rv.register_agent(
        agent_id="research-v1",
        name="Research Agent",
        budget=1.0,                          # optional
    )

    # 2. Build a proxy-routed LLM.
    RVChat = identity.build_llm(ChatOpenAI)

    # 3. Wrap each invocation in a Run.
    with identity.run():
        result = compiled_graph.invoke({"input": "..."})
"""

from __future__ import annotations

import logging

from typing import Literal

from runvault.auth.registration import register
from runvault.http.backend import BackendClient
from runvault.identity import Identity

log = logging.getLogger(__name__)


class RunVault:
    """RunVault SDK client.

    Holds the API key (used only at registration) and a backend HTTP
    client. One instance per process is typical, but multiple are
    supported (e.g. testing against multiple environments).

    Args:
        api_key: Active RunVault project API key (``rv_live_…``).
        be_url:  Base URL of the RunVault backend.
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

    def register_agent(
        self,
        agent_id: str,
        name: str,
        budget: float | None = None,
        budget_alert_threshold: float | None = None,
        security_policy: Literal["hard", "soft"] | None = None,
    ) -> Identity:
        """Register an agent (or load it if already registered) and return
        a long-lived ``Identity`` ready to drive LLM calls.

        Idempotent — same ``agent_id`` returns the same Identity. On
        first registration the backend mints an Ed25519 keypair and
        signs a certificate with the project CA; both are cached to
        ``~/.runvault/<agent_id>/`` and held in memory on the returned
        Identity. On re-registration the existing material is loaded
        from disk.

        Args:
            agent_id:                External agent identifier (e.g. ``"research-v1"``).
            name:                    Human-readable agent name.
            budget:                  Optional hard spending cap in USD.
            budget_alert_threshold:  Optional alert percentage (0–100).
            security_policy:         Cross-identity guard mode for the LLMs
                                     built from this identity. ``"hard"``
                                     (default) raises ``CrossIdentityError``
                                     on a mismatch; ``"soft"`` warns and
                                     bills the bound identity. Honoured only
                                     on first registration — the backend is
                                     authoritative afterwards.

        Returns:
            An :class:`Identity` ready for ``identity.run()`` and
            ``identity.build_llm()``.

        Raises:
            AgentSuspendedError: Admin has suspended this agent.
            RegistrationError:   Backend registration failed.
        """
        info, private_key_bytes, certificate = register(
            http=self._http,
            api_key=self._api_key,
            agent_id=agent_id,
            name=name,
            budget=budget,
            budget_alert_threshold=budget_alert_threshold,
            security_policy=security_policy,
        )

        # The run_id returned by the backend at registration is discarded.
        # The new design generates run_ids locally inside `identity.run()`
        # — this keeps the backend off the per-run hot path.

        return Identity(
            info=info,
            api_key=self._api_key,
            external_agent_id=agent_id,
            name=name,
            private_key_bytes=private_key_bytes,
            certificate=certificate,
            http=self._http,
            security_policy=info.security_policy,
        )
