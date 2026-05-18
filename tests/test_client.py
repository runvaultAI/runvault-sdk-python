"""Tests for runvault.client — RunVault.register_agent."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runvault.client import RunVault
from runvault.exceptions import AuthenticationError, ConnectionError, RegistrationError
from runvault.http.backend import BackendClient
from runvault.identity import Identity


# 32 zero bytes, base64-encoded — a valid-length Ed25519 key for test purposes.
_FAKE_PRIVATE_KEY_B64 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="

_SUCCESS_DATA = {
    "agent_id":      "a3a268ce-e2db-4abd-ba01-f69057e6e825",
    "run_id":        "40159395-641f-4b4c-82b2-0503e0dff67c",
    "agent_created": True,
    "llm_provider":  "openai",
    "proxy_url":     "http://proxy:8080",
    "agent_private_key": _FAKE_PRIVATE_KEY_B64,
    "certificate": {
        "version":       1,
        "serial_number": "test-serial-001",
        "agent_id":      "a3a268ce-e2db-4abd-ba01-f69057e6e825",
        "project_id":    "00000000-0000-0000-0000-000000000000",
        "issued_by":     "RunVault-Test",
        "issued_at":     "2026-01-01T00:00:00+00:00",
        "expires_at":    "2027-01-01T00:00:00+00:00",
        "scope":         ["LLM"],
        "public_key":    _FAKE_PRIVATE_KEY_B64,
        "signature":     "A" * 88,
    },
}


@pytest.fixture(autouse=True)
def _no_credential_writes(monkeypatch):
    """Prevent tests from writing credential files to the real filesystem."""
    monkeypatch.setattr("runvault.auth.registration.save_credentials", lambda **_: None)


def _make_rv() -> RunVault:
    return RunVault(api_key="rv_live_testkey", be_url="http://test.example")


# ─────────────────────────────────────────────────────────────────────
# BackendClient._parse_error — preserved from the previous test suite
# ─────────────────────────────────────────────────────────────────────


class TestBackendClientParseError:
    def _mock_resp(self, json_body=None, text="fallback"):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.text = text
        if json_body is not None:
            resp.json.return_value = json_body
        else:
            resp.json.side_effect = Exception("not json")
        return resp

    def test_structured_detail(self):
        resp = self._mock_resp({"detail": {"detail": "internal", "code": "ERR", "user_string": "Human"}})
        msg, code, user_str = BackendClient._parse_error(resp)
        assert msg == "internal"
        assert code == "ERR"
        assert user_str == "Human"

    def test_string_detail(self):
        resp = self._mock_resp({"detail": "some error"})
        msg, code, user_str = BackendClient._parse_error(resp)
        assert msg == "some error"
        assert code is None
        assert user_str == "some error"

    def test_non_json_falls_back_to_text(self):
        resp = self._mock_resp(text="raw error")
        msg, code, user_str = BackendClient._parse_error(resp)
        assert msg == "raw error"
        assert code is None


# ─────────────────────────────────────────────────────────────────────
# RunVault.register_agent
# ─────────────────────────────────────────────────────────────────────


class TestRegisterAgent:
    def test_returns_identity_on_success(self):
        rv = _make_rv()
        with patch.object(rv._http, "post", return_value=_SUCCESS_DATA):
            identity = rv.register_agent(agent_id="agent-1", name="Test Agent")
        assert isinstance(identity, Identity)
        assert identity.agent_id == "agent-1"
        assert identity.proxy_url == "http://proxy:8080"

    def test_existing_agent_returns_identity(self):
        rv = _make_rv()
        data = {**_SUCCESS_DATA, "agent_created": False}
        with patch.object(rv._http, "post", return_value=data):
            identity = rv.register_agent(agent_id="agent-1", name="Test Agent")
        assert isinstance(identity, Identity)

    def test_connection_error_propagates(self):
        rv = _make_rv()
        with patch.object(rv._http, "post", side_effect=ConnectionError("refused")):
            with pytest.raises(ConnectionError):
                rv.register_agent(agent_id="agent-1", name="Agent")

    def test_authentication_error_propagates(self):
        rv = _make_rv()
        exc = AuthenticationError("bad key", status_code=401, error_code="INVALID_API_KEY")
        with patch.object(rv._http, "post", side_effect=exc):
            with pytest.raises(AuthenticationError) as exc_info:
                rv.register_agent(agent_id="agent-1", name="Agent")
        assert exc_info.value.error_code == "INVALID_API_KEY"

    def test_registration_error_propagates(self):
        rv = _make_rv()
        exc = RegistrationError("server error", status_code=500, error_code="INTERNAL_ERROR")
        with patch.object(rv._http, "post", side_effect=exc):
            with pytest.raises(RegistrationError):
                rv.register_agent(agent_id="agent-1", name="Agent")

    def test_api_key_in_payload(self):
        rv = _make_rv()
        with patch.object(rv._http, "post", return_value=_SUCCESS_DATA) as mock_post:
            rv.register_agent("agent-1", "Agent")
        payload = mock_post.call_args[0][1]
        assert payload["rv_api_key"] == "rv_live_testkey"

    def test_budget_params_forwarded_when_provided(self):
        rv = _make_rv()
        with patch.object(rv._http, "post", return_value=_SUCCESS_DATA) as mock_post:
            rv.register_agent("agent-1", "Agent", budget=0.5, budget_alert_threshold=0.2)
        payload = mock_post.call_args[0][1]
        assert payload["budget"] == 0.5
        assert payload["budget_alert_threshold"] == 0.2

    def test_budget_params_omitted_when_none(self):
        rv = _make_rv()
        with patch.object(rv._http, "post", return_value=_SUCCESS_DATA) as mock_post:
            rv.register_agent("agent-1", "Agent")
        payload = mock_post.call_args[0][1]
        assert "budget" not in payload
        assert "budget_alert_threshold" not in payload

    def test_identity_can_build_a_run(self):
        """Round-trip — register, enter a `with identity.run():` block."""
        rv = _make_rv()
        with patch.object(rv._http, "post", return_value=_SUCCESS_DATA):
            identity = rv.register_agent("agent-1", "Agent")
        with identity.run() as run:
            assert run.identity is identity
            assert run.agent_id == "agent-1"
