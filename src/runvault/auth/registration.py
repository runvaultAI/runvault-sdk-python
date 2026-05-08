"""Agent registration — POST /auth/agents/runs and /credentials/refresh.

This module implements the SDK-side recovery dance described in
``be/app/routers/agent_auth.py``. The backend's `init()` is idempotent on
certificate state, so the SDK has to handle four distinct response shapes:

    HTTP / Code                       Meaning              SDK action
    ────────────────────────────      ───────────────      ───────────────────
    200, private_key+cert in body     first registration    save creds, return
    200, no private_key in body       re-registration       load creds from disk
    410 CERT_ROTATION_REQUIRED        cert was rotated      call /refresh
    403 AGENT_SUSPENDED               admin suspended       raise AgentSuspendedError

The `register()` function below collapses all four into a single
"give me usable credentials" call from the caller's perspective.
"""

from __future__ import annotations

import base64
import logging
import os
import uuid
from dataclasses import dataclass

from runvault.auth.credentials import (
    load_credentials,
    save_credentials,
    verify_certificate,
)
from runvault.exceptions import AgentSuspendedError, RegistrationError

log = logging.getLogger(__name__)


@dataclass
class AgentInfo:
    id: uuid.UUID
    agent_id: str
    name: str
    project_id: uuid.UUID
    run_id: uuid.UUID
    budget: float | None
    budget_alert_threshold: float | None
    llm_provider: str
    proxy_url: str    # base proxy URL returned by the backend on registration
    created: bool


def register(
    http,
    api_key: str,
    agent_id: str,
    name: str,
    budget: float | None = None,
    budget_alert_threshold: float | None = None,
) -> tuple[AgentInfo, bytes, dict]:
    """Register or recover credentials for an agent.

    On success returns ``(AgentInfo, private_key_bytes, certificate)``. The
    credentials are guaranteed to be valid for the proxy at the moment this
    call returns; if the on-disk cert is stale the function transparently
    calls ``/auth/agents/credentials/refresh`` to mint fresh ones.

    Raises:
        AgentSuspendedError: backend returned 403; admin must reactivate.
        RegistrationError:   any other backend failure (network, 5xx, etc.).
    """
    payload = _build_payload(api_key, agent_id, name, budget, budget_alert_threshold)

    try:
        data = http.post("/auth/agents/runs", payload)
    except RegistrationError as exc:
        # Backend mapped 4xx → RegistrationError with the error code in
        # exc.error_code. Branch on the code rather than the HTTP status
        # because the SDK's BackendClient hides the latter.
        return _handle_init_error(
            exc,
            http=http,
            api_key=api_key,
            agent_id=agent_id,
            name=name,
            budget=budget,
            budget_alert_threshold=budget_alert_threshold,
        )

    # Auto-fall-back: if the backend returned the idempotent "existing
    # agent, use your on-disk creds" shape (private_key=None) but the
    # agent has no on-disk credentials, transparently call /refresh to
    # mint fresh ones. This handles the case where the agent's
    # persistent volume was lost between runs (container restart on a
    # fresh filesystem, manual `rm`, OS reinstall). The backend's
    # currently-active cert is now orphaned — /refresh revokes it and
    # issues a fresh keypair, which is exactly the right semantics.
    if data.get("agent_private_key") is None and load_credentials(agent_id) is None:
        log.info(
            "agent %s: backend reports existing registration but no local "
            "credentials on disk — falling back to /credentials/refresh",
            agent_id,
        )
        return refresh(
            http=http,
            api_key=api_key,
            agent_id=agent_id,
            name=name,
            budget=budget,
            budget_alert_threshold=budget_alert_threshold,
        )

    return _process_registration_response(
        data=data,
        agent_id=agent_id,
        name=name,
        budget=budget,
        budget_alert_threshold=budget_alert_threshold,
    )


def refresh(
    http,
    api_key: str,
    agent_id: str,
    name: str,
    budget: float | None = None,
    budget_alert_threshold: float | None = None,
) -> tuple[AgentInfo, bytes, dict]:
    """Mint fresh credentials for an existing agent.

    Calls ``POST /auth/agents/credentials/refresh``. The backend ALWAYS
    returns a fresh keypair + cert if the agent is reachable and active;
    otherwise it raises:

      - ``AgentSuspendedError`` (403) — admin has suspended the agent.
      - ``RegistrationError`` with code AGENT_NOT_FOUND (404) — agent
        doesn't exist; caller should fall back to ``register()``.

    Used directly by ``RunVaultProviderTransport`` when the proxy returns
    401 CERTIFICATE_REVOKED, and indirectly by ``register()`` when the
    backend returns 410 CERT_ROTATION_REQUIRED.
    """
    payload = _build_payload(api_key, agent_id, name, budget, budget_alert_threshold)
    try:
        data = http.post("/auth/agents/credentials/refresh", payload)
    except RegistrationError as exc:
        if exc.error_code == "AGENT_SUSPENDED":
            raise AgentSuspendedError(
                str(exc),
                user_string=getattr(exc, "user_string", None)
                or "This agent has been suspended by an administrator.",
            ) from exc
        raise

    return _process_registration_response(
        data=data,
        agent_id=agent_id,
        name=name,
        budget=budget,
        budget_alert_threshold=budget_alert_threshold,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_payload(
    api_key: str,
    agent_id: str,
    name: str,
    budget: float | None,
    budget_alert_threshold: float | None,
) -> dict:
    payload: dict = {"agent_id": agent_id, "name": name, "rv_api_key": api_key}
    if budget is not None:
        payload["budget"] = budget
    if budget_alert_threshold is not None:
        payload["budget_alert_threshold"] = budget_alert_threshold
    return payload


def _handle_init_error(
    exc: RegistrationError,
    *,
    http,
    api_key: str,
    agent_id: str,
    name: str,
    budget: float | None,
    budget_alert_threshold: float | None,
) -> tuple[AgentInfo, bytes, dict]:
    """Branch on the backend error code returned by /auth/agents/runs."""
    if exc.error_code == "AGENT_SUSPENDED":
        # Permanent. Surface as the typed error so callers can catch it.
        raise AgentSuspendedError(
            str(exc),
            user_string=getattr(exc, "user_string", None)
            or "This agent has been suspended by an administrator.",
        ) from exc

    if exc.error_code == "CERT_ROTATION_REQUIRED":
        # The agent exists but its cert was revoked (admin scope change or
        # explicit revoke). Recover by calling /refresh — same body shape,
        # different endpoint. Refresh handles its own 403 → AgentSuspendedError.
        log.info(
            "init: agent %s requires credential rotation, calling /refresh",
            agent_id,
        )
        return refresh(
            http=http,
            api_key=api_key,
            agent_id=agent_id,
            name=name,
            budget=budget,
            budget_alert_threshold=budget_alert_threshold,
        )

    raise


def _process_registration_response(
    *,
    data: dict,
    agent_id: str,
    name: str,
    budget: float | None,
    budget_alert_threshold: float | None,
) -> tuple[AgentInfo, bytes, dict]:
    """Common 200-response handler for both /runs and /credentials/refresh.

    Two response shapes:

      1. With private_key + certificate (first registration / refresh):
         verify CA signature, persist to disk, return raw bytes.

      2. Without private_key + certificate (re-registration of existing
         agent with valid cert): load credentials from disk and return.
         If on-disk credentials are missing, raise — the SDK has no way
         to recover.
    """
    private_key_b64 = data.get("agent_private_key")
    certificate = data.get("certificate")

    if private_key_b64 is not None and certificate is not None:
        private_key_bytes = _persist_fresh_credentials(
            agent_id=agent_id,
            private_key_b64=private_key_b64,
            certificate=certificate,
        )
    else:
        # Re-registration: backend says "you already have valid creds." Load
        # them from disk. If the disk is empty (e.g. ephemeral container
        # without volume mount), surface a clear error rather than continuing
        # with no credentials.
        loaded = load_credentials(agent_id)
        if loaded is None:
            raise RegistrationError(
                f"Backend reported agent {agent_id!r} already registered, but no "
                f"local credentials were found at ~/.runvault/agents/{agent_id}/. "
                f"This typically means the agent's persistent volume was lost; "
                f"call /credentials/refresh to mint fresh credentials.",
                error_code="LOCAL_CREDENTIALS_MISSING",
                user_string=(
                    "Your agent's local credentials are missing. Restart the "
                    "agent or contact your administrator if the problem persists."
                ),
            )
        private_key_bytes, certificate = loaded
        log.info(
            "loaded existing credentials from disk for agent %s",
            agent_id,
        )

    info = AgentInfo(
        id=uuid.UUID(data["agent_id"]),
        agent_id=agent_id,
        name=name,
        project_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        run_id=uuid.UUID(data["run_id"]),
        budget=budget,
        budget_alert_threshold=budget_alert_threshold,
        llm_provider=data["llm_provider"],
        proxy_url=data["proxy_url"],
        created=data["agent_created"],
    )

    log.info(
        "RunVault agent %s: agent_id=%s id=%s run_id=%s provider=%s proxy=%s",
        "registered" if info.created else "found existing",
        agent_id, info.id, info.run_id, info.llm_provider, info.proxy_url,
    )
    return info, private_key_bytes, certificate


def _persist_fresh_credentials(
    *,
    agent_id: str,
    private_key_b64: str,
    certificate: dict,
) -> bytes:
    """Verify, save, and return the private-key bytes.

    Verifies the certificate's CA signature when ``RV_CA_PUBLIC_KEY`` is
    set (skips with a warning otherwise). Writes both files with
    0600 / 0700 permissions.
    """
    ca_public_key_b64 = os.environ.get("RV_CA_PUBLIC_KEY", "")
    if ca_public_key_b64:
        verify_certificate(certificate, ca_public_key_b64)
        log.info(
            "certificate verified: agent_id=%s serial=%s",
            agent_id,
            certificate.get("serial_number"),
        )
    else:
        log.warning(
            "RV_CA_PUBLIC_KEY not set — skipping certificate verification for agent_id=%s. "
            "Set RV_CA_PUBLIC_KEY to enable CA signature and expiry checks.",
            agent_id,
        )

    save_credentials(
        agent_id=agent_id,
        private_key_b64=private_key_b64,
        certificate=certificate,
    )
    return base64.b64decode(private_key_b64)
