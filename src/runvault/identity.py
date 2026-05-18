"""Identity, Run, and the active-run ContextVar.

This module is the runtime core of the redesigned SDK.

  Identity  — long-lived: holds the agent's Ed25519 private key, CA-signed
              certificate, proxy URL, and dispatches LLM construction
              through ``build_llm``. One Identity per registered agent.
  Run       — short-lived: a single execution scope. Holds the run_id that
              gets baked into every JWT minted during this scope.
  current_run() — ambient lookup for code that needs the active Run but
              doesn't have an Identity in scope (tool functions, callbacks).

The transport reads ``current_run()`` on every outbound HTTP request,
extracts ``run_id`` from the Run, and reaches back to the owning
Identity for ``private_key_bytes`` and ``certificate_b64`` to sign the JWT.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from runvault.exceptions import NoActiveRunError

if TYPE_CHECKING:
    from runvault.auth.registration import AgentInfo
    from runvault.http.backend import BackendClient

log = logging.getLogger(__name__)

SecurityPolicy = Literal["hard", "soft"]


# ─────────────────────────────────────────────────────────────────────────
# ContextVar: active Run for the current execution
# ─────────────────────────────────────────────────────────────────────────

_CURRENT_RUN: ContextVar["Run"] = ContextVar("_current_run")


def current_run() -> "Run":
    """Return the active Run for the current async task / thread context.

    Set by the ``with identity.run():`` context manager. Read by the
    transport on every outbound request to embed ``run_id`` into the JWT
    and to reach the owning Identity for the signing key.

    Raises:
        RuntimeError: If called outside a ``with identity.run():`` block.
                      Silent ``None`` would mask real bugs ("why is run_id
                      missing from these spans?" three weeks later).
    """
    try:
        return _CURRENT_RUN.get()
    except LookupError:
        raise NoActiveRunError(
            "No active RunVault run. "
            "Wrap your call in `with identity.run():` before invoking the LLM."
        )


# ─────────────────────────────────────────────────────────────────────────
# Run — short-lived execution scope
# ─────────────────────────────────────────────────────────────────────────


class Run:
    """A single active execution. Yielded by ``identity.run()``.

    Holds:
      - run_id     — fresh UUID generated locally on context-manager entry.
      - identity   — back-reference to the owning Identity (for signing).
      - started_at — UTC timestamp when this Run was constructed.

    The Run does NOT hold a JWT. JWTs are minted per-request by the
    transport, which reads ``run_id`` from this Run and uses the
    Identity's private key to sign.
    """

    __slots__ = ("run_id", "identity", "started_at", "_security_policy_override")

    def __init__(
        self,
        identity: "Identity",
        run_id: str,
        security_policy_override: SecurityPolicy | None = None,
    ) -> None:
        self.identity = identity
        self.run_id = run_id
        self.started_at = datetime.now(timezone.utc)
        self._security_policy_override = security_policy_override

    @property
    def agent_id(self) -> str:
        """Convenience accessor — pulls from the owning Identity."""
        return self.identity.agent_id

    @property
    def effective_security_policy(self) -> SecurityPolicy:
        """Per-run override if set, else the owning Identity's default."""
        return self._security_policy_override or self.identity.security_policy

    def __repr__(self) -> str:
        return f"Run(run_id={self.run_id!r}, agent_id={self.agent_id!r})"


# ─────────────────────────────────────────────────────────────────────────
# _RunContext — the context manager returned by identity.run()
# ─────────────────────────────────────────────────────────────────────────


class _RunContext:
    """Sync + async context manager that pushes a fresh Run onto the
    ContextVar on enter and pops it on exit.

    Returned by ``Identity.run()``. Not constructed by user code directly.
    """

    __slots__ = ("_identity", "_run", "_token", "_security_policy_override")

    def __init__(
        self,
        identity: "Identity",
        security_policy_override: SecurityPolicy | None = None,
    ) -> None:
        self._identity = identity
        self._security_policy_override = security_policy_override
        self._run: Run | None = None
        self._token: Any = None  # contextvars.Token, opaque

    # ── sync ────────────────────────────────────────────────────────────
    def __enter__(self) -> Run:
        return self._enter()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._exit()

    # ── async ───────────────────────────────────────────────────────────
    async def __aenter__(self) -> Run:
        return self._enter()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._exit()

    # ── shared ──────────────────────────────────────────────────────────
    def _enter(self) -> Run:
        run_id = uuid.uuid4().hex
        self._run = Run(
            identity=self._identity,
            run_id=run_id,
            security_policy_override=self._security_policy_override,
        )
        self._token = _CURRENT_RUN.set(self._run)
        log.debug("run started: run_id=%s agent_id=%s", run_id, self._identity.agent_id)
        return self._run

    def _exit(self) -> None:
        # Reset the ContextVar even if something goes wrong inside the block —
        # otherwise the next caller would see this Run as still active.
        if self._token is not None:
            _CURRENT_RUN.reset(self._token)
            self._token = None
        if self._run is not None:
            log.debug(
                "run ended: run_id=%s agent_id=%s",
                self._run.run_id,
                self._run.agent_id,
            )
            self._run = None


# ─────────────────────────────────────────────────────────────────────────
# Identity — long-lived registered agent
# ─────────────────────────────────────────────────────────────────────────


class Identity:
    """A registered RunVault agent. Owns the Ed25519 private key and the
    CA-signed certificate. Source of Run objects and LLM classes.

    Not constructed directly — always returned by ``RunVault.register_agent()``.

    Attributes:
        agent_id          — stable external identifier (e.g. "research-v1").
        db_agent_id       — DB UUID assigned by the backend; goes into JWT claims.
        name              — human-readable label.
        proxy_url         — base proxy URL for this deployment.
        private_key_bytes — raw 32-byte Ed25519 private key, in memory.
        certificate_b64   — base64-encoded cert JSON, sent as X-RV-Certificate.
    """

    def __init__(
        self,
        *,
        info: "AgentInfo",
        api_key: str,
        external_agent_id: str,
        name: str,
        private_key_bytes: bytes,
        certificate: dict,
        http: "BackendClient",
        security_policy: SecurityPolicy = "hard",
    ) -> None:
        # Backend identity
        self._info = info
        self.agent_id = external_agent_id
        self.db_agent_id = str(info.id)
        self.name = name
        self.proxy_url = info.proxy_url
        self.llm_provider = info.llm_provider
        self.security_policy: SecurityPolicy = security_policy

        # Credentials (in memory + cached on disk by registration)
        self.private_key_bytes = private_key_bytes
        self.certificate_b64 = self._encode_cert(certificate)

        # Plumbing for refresh_credentials()
        self._api_key = api_key
        self._http = http

    # ── public API ──────────────────────────────────────────────────────

    def run(
        self,
        *,
        security_policy: SecurityPolicy | None = None,
    ) -> _RunContext:
        """Return a context manager that activates a fresh Run.

        ```python
        with identity.run() as run:
            graph.invoke(...)
        ```

        Generates a fresh ``run_id`` locally; no backend round-trip. The
        ContextVar is set on enter and reset on exit. Async usage
        (``async with identity.run():``) is supported with identical
        semantics.

        Args:
            security_policy: Optional per-run override of this identity's
                default ``security_policy``. The transport reads the
                effective policy on every request — see the
                cross-identity guard in ``http/transport.py``.
        """
        return _RunContext(self, security_policy_override=security_policy)

    def build_llm(self, base_cls: type) -> type:
        """Return a dynamic subclass of ``base_cls`` wired through the
        RunVault proxy. Dispatched by base-class identity.

        Currently supported:
          - langchain BaseChatModel subclasses (e.g. ChatOpenAI, ChatAnthropic)
          - crewai.BaseLLM

        Raises:
            TypeError: If ``base_cls`` is not in the dispatch table.
        """
        from runvault.llm import build_llm as _build_llm
        return _build_llm(self, base_cls)

    # ── credentials refresh (called from the transport on 401) ──────────

    def refresh_credentials(self) -> None:
        """Re-mint this identity's credentials via the backend.

        Called by the transport when the proxy returns 401
        CERTIFICATE_REVOKED. After this returns, the next outbound
        request will use the freshly minted private key + cert.

        Raises:
            AgentSuspendedError: admin has suspended this agent.
            RegistrationError:   any other backend failure.
        """
        from runvault.auth.registration import refresh as _refresh_call

        info, private_key_bytes, certificate = _refresh_call(
            http=self._http,
            api_key=self._api_key,
            agent_id=self.agent_id,
            name=self.name,
            budget=self._info.budget,
            budget_alert_threshold=self._info.budget_alert_threshold,
            security_policy=self.security_policy,
        )

        # Atomic swap. The transport reads these on the next request via
        # current_run().identity, so the rotation is instantly visible.
        self._info = info
        # Dashboard-authoritative: trust backend's view of security_policy
        # on every refresh so admin changes propagate.
        self.security_policy = info.security_policy
        self.private_key_bytes = private_key_bytes
        self.certificate_b64 = self._encode_cert(certificate)
        log.info("identity %s credentials refreshed", self.agent_id)

    # ── internal helpers ────────────────────────────────────────────────

    @staticmethod
    def _encode_cert(certificate: dict) -> str:
        """Pre-compute the base64-encoded JSON certificate.

        The transport sends this verbatim as the ``X-RV-Certificate``
        header on every request. Encoding once at construction time is
        cheaper than re-encoding per request.
        """
        return base64.b64encode(
            json.dumps(certificate, sort_keys=True, separators=(",", ":")).encode()
        ).decode()

    def provider_proxy_url(self, provider: str) -> str:
        """Return the full proxy URL for a given provider (e.g. "openai").

        Used by the LLM wrappers when configuring their underlying SDK
        client (``base_url=identity.provider_proxy_url("openai") + "/v1"``).
        """
        return f"{self.proxy_url.rstrip('/')}/{provider}"

    def __repr__(self) -> str:
        return f"Identity(agent_id={self.agent_id!r}, name={self.name!r})"

    def __hash__(self) -> int:
        return hash(self.agent_id)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Identity) and other.agent_id == self.agent_id
