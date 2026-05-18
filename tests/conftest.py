from __future__ import annotations

import base64
import json
import uuid
from unittest.mock import MagicMock

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def make_httpx_response(
    status_code: int,
    body: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """Build a real httpx.Response for use in interceptor / transport tests."""
    content = json.dumps(body).encode() if body is not None else b""
    h = {"content-type": "application/json"}
    if headers:
        h.update({k.lower(): v for k, v in headers.items()})
    return httpx.Response(status_code=status_code, content=content, headers=h)


def make_test_identity(
    *,
    agent_id: str | None = None,
    private_key_bytes: bytes | None = None,
    certificate_b64: str | None = None,
    proxy_url: str = "http://proxy.test:8080",
    db_agent_id: str | None = None,
    security_policy: str = "hard",
) -> MagicMock:
    """Build a mock ``Identity`` carrying realistic key material + policy."""
    identity = MagicMock()
    identity.agent_id = agent_id or f"agent-{uuid.uuid4().hex[:8]}"
    identity.private_key_bytes = (
        private_key_bytes or Ed25519PrivateKey.generate().private_bytes_raw()
    )
    identity.certificate_b64 = (
        certificate_b64 or base64.b64encode(b'{"serial_number":"test-serial"}').decode()
    )
    identity.proxy_url = proxy_url
    identity.db_agent_id = db_agent_id or str(uuid.uuid4())
    identity.security_policy = security_policy
    identity.refresh_credentials = MagicMock()
    return identity


def make_test_run(
    *,
    identity: MagicMock | None = None,
    run_id: str | None = None,
    security_policy_override: str | None = None,
    **identity_kwargs,
) -> MagicMock:
    """Build a mock ``Run`` with an ``Identity`` attached.

    The transport reads ``run.identity`` (for the cross-identity check),
    ``run.run_id`` (for JWT claims), and ``run.effective_security_policy``
    (for hard/soft branching).
    """
    if identity is None:
        identity = make_test_identity(**identity_kwargs)

    run = MagicMock()
    run.identity = identity
    run.run_id = run_id or uuid.uuid4().hex
    run.effective_security_policy = security_policy_override or identity.security_policy
    return run
