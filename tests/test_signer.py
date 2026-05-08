"""Tests for runvault.auth.signer — EdDSA JWT minting."""

from __future__ import annotations

import base64
import json
import time

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from runvault.auth.signer import create_agent_jwt


def _b64url_decode(segment: str) -> bytes:
    """JWT segments are base64url with stripped padding — restore it."""
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _decode_jwt(token: str) -> tuple[dict, dict, bytes, bytes]:
    """Return (header, payload, signature, signing_input) for a JWT."""
    header_b64, payload_b64, sig_b64 = token.split(".")
    header = json.loads(_b64url_decode(header_b64))
    payload = json.loads(_b64url_decode(payload_b64))
    signature = _b64url_decode(sig_b64)
    signing_input = f"{header_b64}.{payload_b64}".encode()
    return header, payload, signature, signing_input


@pytest.fixture
def keypair() -> tuple[bytes, Ed25519PrivateKey]:
    """A fresh Ed25519 keypair, returned as (raw_private_bytes, private_key_obj)."""
    private_key = Ed25519PrivateKey.generate()
    return private_key.private_bytes_raw(), private_key


class TestCreateAgentJwt:
    def test_signature_verifies_with_matching_public_key(self, keypair):
        private_key_bytes, private_key = keypair
        token = create_agent_jwt(
            agent_id="a3a268ce-e2db-4abd-ba01-f69057e6e825",
            run_id="40159395-641f-4b4c-82b2-0503e0dff67c",
            private_key_bytes=private_key_bytes,
        )

        _, _, signature, signing_input = _decode_jwt(token)
        # Should not raise.
        private_key.public_key().verify(signature, signing_input)

    def test_signature_fails_with_unrelated_public_key(self, keypair):
        private_key_bytes, _ = keypair
        token = create_agent_jwt(
            agent_id="agent-uuid",
            run_id="run-uuid",
            private_key_bytes=private_key_bytes,
        )

        other_key = Ed25519PrivateKey.generate().public_key()
        _, _, signature, signing_input = _decode_jwt(token)
        with pytest.raises(InvalidSignature):
            other_key.verify(signature, signing_input)

    def test_header_uses_eddsa_jwt_format(self, keypair):
        private_key_bytes, _ = keypair
        token = create_agent_jwt(
            agent_id="agent-uuid", run_id="run-uuid", private_key_bytes=private_key_bytes,
        )
        header, _, _, _ = _decode_jwt(token)
        assert header == {"alg": "EdDSA", "typ": "JWT"}

    def test_payload_carries_aud_iat_exp_jti_agent_id_run_id(self, keypair):
        private_key_bytes, _ = keypair
        before = int(time.time())
        token = create_agent_jwt(
            agent_id="my-agent-uuid",
            run_id="my-run-uuid",
            private_key_bytes=private_key_bytes,
        )
        after = int(time.time())

        _, payload, _, _ = _decode_jwt(token)
        assert payload["aud"] == "runvault-proxy"
        assert payload["agent_id"] == "my-agent-uuid"
        assert payload["run_id"] == "my-run-uuid"
        assert before <= payload["iat"] <= after
        assert payload["exp"] == payload["iat"] + 300
        # jti should be a UUID-ish string.
        assert len(payload["jti"]) == 36 and payload["jti"].count("-") == 4

    def test_each_call_produces_a_fresh_jti(self, keypair):
        """Replay protection assumes every JWT carries a unique jti — verify it."""
        private_key_bytes, _ = keypair
        seen_jtis = set()
        for _ in range(5):
            token = create_agent_jwt(
                agent_id="agent-uuid",
                run_id="run-uuid",
                private_key_bytes=private_key_bytes,
            )
            _, payload, _, _ = _decode_jwt(token)
            seen_jtis.add(payload["jti"])
        assert len(seen_jtis) == 5

    def test_invalid_key_length_raises(self):
        with pytest.raises(ValueError):
            create_agent_jwt(
                agent_id="a", run_id="b", private_key_bytes=b"too-short",
            )
