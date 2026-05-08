"""Tests for runvault.auth.registration — register() and refresh() branches.

The backend's /auth/agents/runs is idempotent and returns four distinct shapes
depending on whether the agent is new, already registered, has a rotated
cert, or is suspended. register() collapses all four into a single
"give me usable credentials" call. These tests cover each branch in
isolation, plus the refresh() suspension path.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from runvault.auth.registration import refresh, register
from runvault.exceptions import AgentSuspendedError, RegistrationError


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Redirect Path.home() to a temp dir so credential writes are sandboxed."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _disable_ca_verification(monkeypatch):
    """Most tests don't generate CA-signed certs — turn verification off.

    The verify_certificate code path itself is covered by test_credentials.py.
    Tests that need verification on can override this fixture explicitly.
    """
    monkeypatch.delenv("RV_CA_PUBLIC_KEY", raising=False)


@pytest.fixture
def ca_keypair():
    private = Ed25519PrivateKey.generate()
    public_b64 = base64.b64encode(private.public_key().public_bytes_raw()).decode()
    return private, public_b64


def _make_signed_cert(ca_private: Ed25519PrivateKey) -> dict:
    payload = {
        "version": 1,
        "serial_number": "test-serial",
        "agent_id": "a3a268ce-e2db-4abd-ba01-f69057e6e825",
        "project_id": "00000000-0000-0000-0000-000000000000",
        "issued_by": "RunVault-Test",
        "issued_at": "2026-01-01T00:00:00+00:00",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
        "scope": ["LLM"],
        "public_key": base64.b64encode(b"\x00" * 32).decode(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["signature"] = base64.b64encode(ca_private.sign(canonical)).decode()
    return payload


def _success_response(*, private_key_b64: str | None, certificate: dict | None) -> dict:
    """Backend's 200 response shape from /auth/agents/runs and /credentials/refresh."""
    return {
        "agent_id": "a3a268ce-e2db-4abd-ba01-f69057e6e825",
        "run_id": "40159395-641f-4b4c-82b2-0503e0dff67c",
        "agent_created": True,
        "llm_provider": "openai",
        "proxy_url": "http://proxy:8080",
        "agent_private_key": private_key_b64,
        "certificate": certificate,
    }


def _http_returning(*responses):
    """Build a MagicMock http whose .post() returns/raises in sequence."""
    http = MagicMock()
    http.post.side_effect = list(responses)
    return http


# ---------------------------------------------------------------------------
# Path 1 — first registration: backend returns private_key + certificate
# ---------------------------------------------------------------------------

class TestFirstRegistration:
    def test_persists_credentials_and_returns_info(self, _isolated_home):
        raw_key = b"\x42" * 32
        cert = {"v": 1, "serial_number": "abc"}
        http = _http_returning(
            _success_response(
                private_key_b64=base64.b64encode(raw_key).decode(),
                certificate=cert,
            )
        )

        info, private_key_bytes, certificate = register(
            http=http, api_key="rv_live_test", agent_id="my-agent", name="Agent",
        )

        assert info.id == uuid.UUID("a3a268ce-e2db-4abd-ba01-f69057e6e825")
        assert info.run_id == uuid.UUID("40159395-641f-4b4c-82b2-0503e0dff67c")
        assert info.proxy_url == "http://proxy:8080"
        assert private_key_bytes == raw_key
        assert certificate == cert

        # Credentials must have hit the disk so subsequent runs can re-use them.
        assert (_isolated_home / ".runvault" / "my-agent" / "private.key").exists()
        assert (_isolated_home / ".runvault" / "my-agent" / "certificate.json").exists()

    def test_verifies_ca_signature_when_rv_ca_public_key_is_set(
        self, _isolated_home, ca_keypair, monkeypatch,
    ):
        ca_private, ca_public_b64 = ca_keypair
        monkeypatch.setenv("RV_CA_PUBLIC_KEY", ca_public_b64)

        cert = _make_signed_cert(ca_private)
        raw_key = b"\x10" * 32
        http = _http_returning(
            _success_response(
                private_key_b64=base64.b64encode(raw_key).decode(),
                certificate=cert,
            )
        )

        # Should not raise — the cert was actually signed by the configured CA.
        info, _, _ = register(
            http=http, api_key="rv_live_test", agent_id="verified-agent", name="Verified",
        )
        assert info.proxy_url == "http://proxy:8080"


# ---------------------------------------------------------------------------
# Path 2 — re-registration: backend returns no private_key, on-disk creds present
# ---------------------------------------------------------------------------

class TestReRegistration:
    def test_loads_credentials_from_disk(self, _isolated_home):
        # Pre-seed disk with creds (simulating a prior init() on this host).
        from runvault.auth.credentials import save_credentials
        existing_key = b"\x99" * 32
        existing_cert = {"v": 9, "serial_number": "previously-signed"}
        save_credentials(
            agent_id="returning-agent",
            private_key_b64=base64.b64encode(existing_key).decode(),
            certificate=existing_cert,
        )

        # Backend signals "you already have valid credentials" (no key/cert in body).
        http = _http_returning(
            _success_response(private_key_b64=None, certificate=None)
        )

        info, private_key_bytes, certificate = register(
            http=http, api_key="rv_live_test", agent_id="returning-agent", name="Returning",
        )

        assert private_key_bytes == existing_key
        assert certificate == existing_cert
        assert info.run_id == uuid.UUID("40159395-641f-4b4c-82b2-0503e0dff67c")


# ---------------------------------------------------------------------------
# Path 3 — re-registration auto-fall-back: backend says "use your creds"
# but the local disk has none (e.g. ephemeral container without volume)
# ---------------------------------------------------------------------------

class TestReRegistrationAutoFallback:
    def test_falls_back_to_refresh_when_local_creds_missing(self, _isolated_home):
        raw_key = b"\x55" * 32
        cert = {"v": 1, "serial_number": "fresh-after-refresh"}

        # First call returns the "no creds in body" shape; SDK detects
        # missing on-disk creds and calls /credentials/refresh which
        # returns fresh ones.
        http = _http_returning(
            _success_response(private_key_b64=None, certificate=None),
            _success_response(
                private_key_b64=base64.b64encode(raw_key).decode(),
                certificate=cert,
            ),
        )

        _, private_key_bytes, certificate = register(
            http=http, api_key="rv_live_test", agent_id="ephemeral-agent", name="Ephemeral",
        )

        assert private_key_bytes == raw_key
        assert certificate["serial_number"] == "fresh-after-refresh"

        # Two backend calls: /auth/agents/runs then /auth/agents/credentials/refresh.
        assert http.post.call_count == 2
        endpoints = [call.args[0] for call in http.post.call_args_list]
        assert endpoints == ["/auth/agents/runs", "/auth/agents/credentials/refresh"]


# ---------------------------------------------------------------------------
# Path 4 — CERT_ROTATION_REQUIRED: admin rotated the cert; SDK calls /refresh
# ---------------------------------------------------------------------------

class TestCertRotationRequired:
    def test_calls_refresh_and_returns_fresh_creds(self, _isolated_home):
        rotated_key = b"\x77" * 32
        cert = {"v": 1, "serial_number": "post-rotation"}

        http = _http_returning(
            RegistrationError(
                "Cert rotated",
                error_code="CERT_ROTATION_REQUIRED",
                user_string="Admin rotated this agent's certificate.",
            ),
            _success_response(
                private_key_b64=base64.b64encode(rotated_key).decode(),
                certificate=cert,
            ),
        )

        _, private_key_bytes, certificate = register(
            http=http, api_key="rv_live_test", agent_id="rotated-agent", name="Rotated",
        )

        assert private_key_bytes == rotated_key
        assert certificate["serial_number"] == "post-rotation"
        # Backend was called twice: failed init, then refresh.
        assert http.post.call_count == 2
        assert http.post.call_args_list[1].args[0] == "/auth/agents/credentials/refresh"


# ---------------------------------------------------------------------------
# Path 5 — AGENT_SUSPENDED on init: SDK raises AgentSuspendedError
# ---------------------------------------------------------------------------

class TestAgentSuspendedOnInit:
    def test_raises_agent_suspended_error(self, _isolated_home):
        http = _http_returning(
            RegistrationError(
                "Agent has been suspended",
                error_code="AGENT_SUSPENDED",
                user_string="An admin has suspended this agent.",
            ),
        )

        with pytest.raises(AgentSuspendedError) as exc_info:
            register(
                http=http, api_key="rv_live_test", agent_id="suspended", name="Suspended",
            )
        assert "suspended" in str(exc_info.value).lower()

    def test_other_error_codes_propagate_unchanged(self, _isolated_home):
        original = RegistrationError(
            "Some other error",
            error_code="INTERNAL_ERROR",
            user_string="Backend hiccup",
        )
        http = _http_returning(original)

        with pytest.raises(RegistrationError) as exc_info:
            register(
                http=http, api_key="rv_live_test", agent_id="other", name="Other",
            )
        assert exc_info.value.error_code == "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# refresh() — direct invocation paths
# ---------------------------------------------------------------------------

class TestRefresh:
    def test_returns_fresh_credentials_on_success(self, _isolated_home):
        raw_key = b"\xAA" * 32
        cert = {"v": 1, "serial_number": "refreshed"}
        http = _http_returning(
            _success_response(
                private_key_b64=base64.b64encode(raw_key).decode(),
                certificate=cert,
            )
        )

        info, private_key_bytes, certificate = refresh(
            http=http, api_key="rv_live_test", agent_id="refreshed-agent", name="Refreshed",
        )

        assert private_key_bytes == raw_key
        assert certificate == cert
        assert info.proxy_url == "http://proxy:8080"
        assert http.post.call_args.args[0] == "/auth/agents/credentials/refresh"

    def test_raises_agent_suspended_error_on_403(self, _isolated_home):
        http = _http_returning(
            RegistrationError(
                "suspended",
                error_code="AGENT_SUSPENDED",
                user_string="Suspended by admin.",
            )
        )

        with pytest.raises(AgentSuspendedError):
            refresh(
                http=http, api_key="rv_live_test", agent_id="suspended", name="Suspended",
            )

    def test_other_errors_propagate_unchanged(self, _isolated_home):
        http = _http_returning(
            RegistrationError("not found", error_code="AGENT_NOT_FOUND", user_string="Gone."),
        )

        with pytest.raises(RegistrationError) as exc_info:
            refresh(
                http=http, api_key="rv_live_test", agent_id="missing", name="Missing",
            )
        assert exc_info.value.error_code == "AGENT_NOT_FOUND"
