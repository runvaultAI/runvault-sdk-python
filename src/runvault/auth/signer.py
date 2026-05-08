"""Agent JWT signer — EdDSA-signed short-lived tokens for proxy authentication.

Produces a JWT signed with the agent's Ed25519 private key. The proxy will
verify this JWT using the agent's public key extracted from the certificate.

Why we build the JWT manually instead of using a library:
    The agent environment is kept lean. Adding python-jose or PyJWT just for
    Ed25519 support pulls in transitive dependencies. The JWT format is a
    simple three-part base64url string — straightforward to build correctly
    with the standard library + cryptography (already required for the key).

JWT structure:
    header  = base64url({"alg":"EdDSA","typ":"JWT"})
    payload = base64url({claims...})
    sig     = base64url(Ed25519_sign(private_key, header + "." + payload))
    token   = header + "." + payload + "." + sig

Claims:
    aud       "runvault-proxy"   — proxy rejects tokens not meant for it
    iat       Unix timestamp     — issued at
    exp       iat + 300          — expires in 5 minutes
    jti       UUID               — unique token ID (for revocation if needed)
    agent_id  DB UUID string     — identifies the agent
    run_id    UUID string        — links this request to the current run
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

log = logging.getLogger(__name__)

_JWT_LIFETIME_SECONDS = 300  # 5 minutes — short enough to limit replay risk
_AUDIENCE = "runvault-proxy"

_HEADER_B64 = base64.urlsafe_b64encode(
    json.dumps({"alg": "EdDSA", "typ": "JWT"}, separators=(",", ":")).encode()
).rstrip(b"=").decode()


def _b64url(data: bytes) -> str:
    """Base64url-encode bytes with no padding characters."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def create_agent_jwt(
    *,
    agent_id: str,
    run_id: str,
    private_key_bytes: bytes,
) -> str:
    """Create a short-lived JWT signed with the agent's Ed25519 private key.

    A new token with a fresh jti and iat/exp is created on every call.
    Call this immediately before each LLM request — do not cache the result.

    Args:
        agent_id:          Agent DB UUID as a string.
        run_id:            Current run UUID as a string.
        private_key_bytes: Raw 32-byte Ed25519 private key loaded from disk.

    Returns:
        Compact JWT string: "<header>.<payload>.<signature>"
    """
    now = int(time.time())

    payload_b64 = _b64url(
        json.dumps(
            {
                "aud": _AUDIENCE,
                "iat": now,
                "exp": now + _JWT_LIFETIME_SECONDS,
                "jti": str(uuid.uuid4()),
                "agent_id": agent_id,
                "run_id": run_id,
            },
            separators=(",", ":"),
        ).encode()
    )

    signing_input = f"{_HEADER_B64}.{payload_b64}".encode()

    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    signature = private_key.sign(signing_input)

    return f"{_HEADER_B64}.{payload_b64}.{_b64url(signature)}"
