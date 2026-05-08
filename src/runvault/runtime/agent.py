"""Agent — runtime context object returned by runvault.init()."""

from __future__ import annotations

import base64
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runvault.auth.registration import AgentInfo
    from runvault.http.backend import BackendClient

log = logging.getLogger(__name__)


class Agent:
    """Runtime context for a registered RunVault agent.

    Returned by RunVault.init(). Holds the proxy JWT, identity data,
    and exposes invoke/stream methods that delegate to the wrapped
    framework adapter.

    The proxy URL is fixed for the lifetime of this Agent — it is
    returned by the backend on registration and does not change
    between requests.

    PKI identity fields:
        private_key_bytes: Raw Ed25519 private key for signing per-request JWTs.
        certificate_b64:   Base64-encoded certificate JSON sent in X-RV-Certificate.
    """

    def __init__(
        self,
        info: AgentInfo,
        http: BackendClient,
        api_key: str,
        external_agent_id: str,
        name: str,
        private_key_bytes: bytes | None = None,
        certificate: dict | None = None,
    ) -> None:
        self.info = info
        self._http = http
        # Stored for refresh_credentials() — the SDK needs to call
        # /auth/agents/credentials/refresh with the original rv_api_key
        # whenever the proxy reports CERTIFICATE_REVOKED. external_agent_id
        # is the user-supplied string identifier (not the DB UUID), which
        # matches how /credentials/refresh looks up the agent.
        self._api_key = api_key
        self._external_agent_id = external_agent_id
        self._name = name

        self.private_key_bytes = private_key_bytes
        self.certificate_b64: str | None = self._encode_cert(certificate)
        self._adapter: Any = None

    @staticmethod
    def _encode_cert(certificate: dict | None) -> str | None:
        """Pre-compute the base64-encoded certificate JSON (the X-RV-Certificate
        header value). Returns None if no certificate is loaded yet.
        """
        if certificate is None:
            return None
        return base64.b64encode(
            json.dumps(certificate, sort_keys=True, separators=(",", ":")).encode()
        ).decode()

    def refresh_credentials(self) -> None:
        """Re-mint this agent's credentials via /auth/agents/credentials/refresh.

        Called by the transport layer when the proxy returns 401
        CERTIFICATE_REVOKED — meaning the admin has rotated the agent's cert
        (scope change or explicit revoke). After this method returns,
        ``self.private_key_bytes`` and ``self.certificate_b64`` reflect the
        fresh credentials and the next outbound request will use them.

        Raises:
            AgentSuspendedError: admin has suspended this agent. The SDK
                cannot recover; an admin must reactivate via the dashboard.
            RegistrationError: any other backend failure (network, 5xx, 404).
        """
        from runvault.auth.registration import refresh as _refresh_call

        info, private_key_bytes, certificate = _refresh_call(
            http=self._http,
            api_key=self._api_key,
            agent_id=self._external_agent_id,
            name=self._name,
            budget=self.info.budget,
            budget_alert_threshold=self.info.budget_alert_threshold,
        )

        # Atomic swap of the credentials in memory. The transport reads
        # private_key_bytes / certificate_b64 on every request via the
        # ContextVar; after this assignment the next request picks up the
        # new credentials. The on-disk copy was already updated by
        # save_credentials() inside the refresh call.
        self.info = info
        self.private_key_bytes = private_key_bytes
        self.certificate_b64 = self._encode_cert(certificate)
        log.info(
            "agent %s credentials refreshed (run_id=%s)",
            self._external_agent_id, info.run_id,
        )

    def proxy_url(self, provider: str) -> str:
        """Return the full proxy URL for a given provider.

        Built from the base URL returned by the backend at registration.
        Fixed for the lifetime of this Agent — cannot be changed after init.

        Example:
            agent.proxy_url("openai")   # → "http://proxy:8080/openai"
            agent.proxy_url("google")   # → "http://proxy:8080/google"
        """
        return f"{self.info.proxy_url.rstrip('/')}/{provider}"

    def langgraph(self, app: Any) -> Agent:
        """Wrap a compiled LangGraph graph and return self.

        Convenience for the long-running agent pattern where register_agent()
        and framework wrapping are separate steps.

        Args:
            app: A compiled LangGraph graph (result of StateGraph.compile()).

        Returns:
            This Agent, now ready to invoke.
        """
        from runvault.adapters.langgraph import wrap_langgraph

        wrap_langgraph(self, app)
        return self

    def _bind_adapter(self, adapter: Any) -> None:
        """Attach a framework adapter wrapper to this Agent.

        Called by wrap_* functions in runvault.adapters after they build their
        internal wrapper. Must be called before any invoke/stream method.
        """
        self._adapter = adapter

    # ------------------------------------------------------------------
    # Graph invocation — delegates to the bound framework adapter
    # ------------------------------------------------------------------

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        """Invoke the wrapped graph synchronously."""
        self._assert_adapter()
        return self._adapter.invoke(*args, **kwargs)

    def stream(self, *args: Any, **kwargs: Any):
        """Stream the wrapped graph synchronously."""
        self._assert_adapter()
        return self._adapter.stream(*args, **kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        """Invoke the wrapped graph asynchronously."""
        self._assert_adapter()
        return await self._adapter.ainvoke(*args, **kwargs)

    async def astream(self, *args: Any, **kwargs: Any):
        """Stream the wrapped graph asynchronously."""
        self._assert_adapter()
        async for chunk in self._adapter.astream(*args, **kwargs):
            yield chunk

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def __enter__(self) -> Agent:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        """No-op end-of-run hook. Reserved for future explicit run shutdown."""

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _assert_adapter(self) -> None:
        if self._adapter is None:
            raise RuntimeError(
                "No framework adapter is bound to this Agent. "
                "Use runvault.init(framework=..., app=...) to create an Agent."
            )
