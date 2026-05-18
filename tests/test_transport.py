"""Tests for runvault.http.transport — PKI-aware proxy transport."""

from __future__ import annotations

import base64
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from unittest.mock import AsyncMock, MagicMock, patch

from runvault.identity import _CURRENT_RUN
from runvault.exceptions import (
    BudgetExceededError,
    LLMProviderError,
    NoActiveRunError,
    ProxyError,
    TokenExpiredError,
)
from runvault.http.transport import (
    PLACEHOLDER_BASE,
    RunVaultProviderAsyncTransport,
    RunVaultProviderTransport,
    _extract_llm_error,
    _is_cert_revoked_response,
    _parse_proxy_error,
    _raise_for_error,
    _rewrite_request,
)
from tests.conftest import make_httpx_response


# Ed25519 key used wherever a real private key is required by the transport.
# Generated once per test module — never persisted, never used outside tests.
_TEST_PRIVATE_KEY_BYTES = Ed25519PrivateKey.generate().private_bytes_raw()
_TEST_CERT_B64 = base64.b64encode(b'{"serial_number":"test-serial"}').decode()


# ---------------------------------------------------------------------------
# _parse_proxy_error
# ---------------------------------------------------------------------------

class TestParseProxyError:
    def test_flat_format(self):
        resp = make_httpx_response(401, {"code": "TOKEN_EXPIRED", "user_string": "Expired", "detail": "Token gone"})
        code, user_str, detail = _parse_proxy_error(resp)
        assert code == "TOKEN_EXPIRED"
        assert user_str == "Expired"
        assert detail == "Token gone"

    def test_nested_format(self):
        resp = make_httpx_response(402, {"detail": {"code": "BUDGET_CAP_REACHED", "user_string": "Over budget", "detail": "Cap hit"}})
        code, user_str, detail = _parse_proxy_error(resp)
        assert code == "BUDGET_CAP_REACHED"
        assert user_str == "Over budget"
        assert detail == "Cap hit"

    def test_unknown_body_returns_none(self):
        resp = make_httpx_response(500, {"message": "internal server error"})
        assert _parse_proxy_error(resp) == (None, None, None)

    def test_non_json_returns_none(self):
        resp = httpx.Response(status_code=500, content=b"not json")
        assert _parse_proxy_error(resp) == (None, None, None)

    def test_nested_detail_not_dict_returns_none(self):
        resp = make_httpx_response(400, {"detail": "just a string"})
        assert _parse_proxy_error(resp) == (None, None, None)


# ---------------------------------------------------------------------------
# _extract_llm_error
# ---------------------------------------------------------------------------

class TestExtractLlmError:
    def test_openai_format(self):
        resp = make_httpx_response(429, {"error": {"message": "Rate limit exceeded"}})
        assert _extract_llm_error(resp, "openai") == "Rate limit exceeded"

    def test_anthropic_format(self):
        resp = make_httpx_response(529, {"error": {"type": "overloaded_error", "message": "Overloaded"}})
        assert _extract_llm_error(resp, "anthropic") == "Overloaded"

    def test_message_field_fallback(self):
        resp = make_httpx_response(400, {"message": "Bad request"})
        assert _extract_llm_error(resp, "cohere") == "Bad request"

    def test_detail_field_fallback(self):
        resp = make_httpx_response(400, {"detail": "Validation failed"})
        assert _extract_llm_error(resp, "openai") == "Validation failed"

    def test_error_not_dict_falls_back_to_status(self):
        resp = make_httpx_response(400, {"error": "string error"})
        assert _extract_llm_error(resp, "openai") == "openai returned HTTP 400"

    def test_empty_body_falls_back_to_status(self):
        resp = make_httpx_response(503, {})
        assert _extract_llm_error(resp, "mistral") == "mistral returned HTTP 503"

    def test_non_json_falls_back_to_status(self):
        resp = httpx.Response(status_code=500, content=b"not json")
        assert _extract_llm_error(resp, "google") == "google returned HTTP 500"


# ---------------------------------------------------------------------------
# _raise_for_error
# ---------------------------------------------------------------------------

class TestRaiseForError:
    def test_budget_cap_header_raises_budget_exceeded(self):
        resp = make_httpx_response(
            429,
            {"error": {"message": "Spending limit reached."}},
            headers={"x-runvault-code": "BUDGET_CAP_REACHED"},
        )
        with pytest.raises(BudgetExceededError) as exc_info:
            _raise_for_error(resp, "openai")
        assert exc_info.value.error_code == "BUDGET_CAP_REACHED"
        assert exc_info.value.status_code == 429

    def test_402_with_runvault_body_raises_budget_exceeded(self):
        resp = make_httpx_response(402, {"code": "BUDGET_CAP_REACHED", "detail": "Cap hit", "user_string": "Over budget"})
        with pytest.raises(BudgetExceededError) as exc_info:
            _raise_for_error(resp, "openai")
        assert exc_info.value.error_code == "BUDGET_CAP_REACHED"

    def test_401_raises_token_expired(self):
        resp = make_httpx_response(401, {"code": "INVALID_TOKEN", "detail": "Bad token", "user_string": "Invalid"})
        with pytest.raises(TokenExpiredError) as exc_info:
            _raise_for_error(resp, "openai")
        assert exc_info.value.status_code == 401

    def test_token_expired_error_code(self):
        resp = make_httpx_response(400, {"code": "TOKEN_EXPIRED", "detail": "Expired", "user_string": "Expired"})
        with pytest.raises(TokenExpiredError):
            _raise_for_error(resp, "anthropic")

    def test_jwt_expired_error_code(self):
        resp = make_httpx_response(400, {"code": "JWT_EXPIRED", "detail": "JWT gone", "user_string": "Expired"})
        with pytest.raises(TokenExpiredError):
            _raise_for_error(resp, "openai")

    def test_503_proxy_version_mismatch_raises_proxy_error(self):
        resp = make_httpx_response(503, {"code": "PROXY_VERSION_MISMATCH", "detail": "Old version", "user_string": "Update needed"})
        with pytest.raises(ProxyError) as exc_info:
            _raise_for_error(resp, "openai")
        assert exc_info.value.status_code == 503

    def test_unknown_runvault_code_raises_generic_proxy_error(self):
        resp = make_httpx_response(400, {"code": "UNKNOWN_CODE", "detail": "Unknown", "user_string": "Unknown error"})
        with pytest.raises(ProxyError) as exc_info:
            _raise_for_error(resp, "openai")
        assert exc_info.value.error_code == "UNKNOWN_CODE"

    def test_no_runvault_code_raises_llm_provider_error(self):
        resp = make_httpx_response(404, {"error": {"message": "Model not found"}})
        with pytest.raises(LLMProviderError) as exc_info:
            _raise_for_error(resp, "openai")
        assert exc_info.value.provider == "openai"
        assert exc_info.value.status_code == 404
        assert exc_info.value.error_code == "OPENAI_ERROR"


# ---------------------------------------------------------------------------
# _is_cert_revoked_response
# ---------------------------------------------------------------------------

class TestIsCertRevokedResponse:
    def test_returns_true_on_401_certificate_revoked(self):
        resp = make_httpx_response(401, {"code": "CERTIFICATE_REVOKED", "detail": "revoked"})
        assert _is_cert_revoked_response(resp) is True

    def test_returns_false_on_other_401_codes(self):
        resp = make_httpx_response(401, {"code": "INVALID_TOKEN", "detail": "bad"})
        assert _is_cert_revoked_response(resp) is False

    def test_returns_false_on_non_401_status(self):
        resp = make_httpx_response(403, {"code": "CERTIFICATE_REVOKED"})
        assert _is_cert_revoked_response(resp) is False


# ---------------------------------------------------------------------------
# _rewrite_request
# ---------------------------------------------------------------------------

class TestRewriteRequest:
    def test_replaces_placeholder_with_proxy_base(self):
        req = httpx.Request("POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions")
        rewritten = _rewrite_request(
            req, "http://proxy:8080", "openai",
            agent_jwt="my-jwt", certificate_b64="my-cert",
        )
        assert str(rewritten.url) == "http://proxy:8080/openai/v1/chat/completions"

    def test_injects_pki_headers(self):
        req = httpx.Request("POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions")
        rewritten = _rewrite_request(
            req, "http://proxy:8080", "openai",
            agent_jwt="my-jwt", certificate_b64="my-cert-b64",
        )
        assert rewritten.headers["x-rv-agent-jwt"] == "my-jwt"
        assert rewritten.headers["x-rv-certificate"] == "my-cert-b64"
        # Legacy auth headers must be absent — proxy refuses bearer auth.
        assert "authorization" not in rewritten.headers
        assert "x-goog-api-key" not in rewritten.headers

    def test_strips_existing_auth_headers(self):
        req = httpx.Request(
            "POST",
            f"{PLACEHOLDER_BASE}/openai/v1/chat/completions",
            headers={"authorization": "Bearer old", "x-goog-api-key": "old-key"},
        )
        rewritten = _rewrite_request(
            req, "http://proxy:8080", "openai",
            agent_jwt="new-jwt", certificate_b64="cert",
        )
        assert "authorization" not in rewritten.headers
        assert "x-goog-api-key" not in rewritten.headers
        assert rewritten.headers["x-rv-agent-jwt"] == "new-jwt"

    def test_preserves_other_headers(self):
        req = httpx.Request(
            "POST",
            f"{PLACEHOLDER_BASE}/openai/v1/chat/completions",
            headers={"content-type": "application/json"},
        )
        rewritten = _rewrite_request(
            req, "http://proxy:8080", "openai",
            agent_jwt="jwt", certificate_b64="cert",
        )
        assert rewritten.headers["content-type"] == "application/json"


# ---------------------------------------------------------------------------
# RunVaultProviderTransport
# ---------------------------------------------------------------------------

def _make_pki_run(proxy_url: str = "http://proxy:8080"):
    """Build a MagicMock Run with an Identity that satisfies the PKI contract."""
    identity = MagicMock()
    identity.agent_id = "test-agent"
    identity.proxy_url = proxy_url
    identity.db_agent_id = "a3a268ce-e2db-4abd-ba01-f69057e6e825"
    identity.private_key_bytes = _TEST_PRIVATE_KEY_BYTES
    identity.certificate_b64 = _TEST_CERT_B64
    identity.security_policy = "hard"

    run = MagicMock()
    run.identity = identity
    run.run_id = "40159395-641f-4b4c-82b2-0503e0dff67c"
    run.effective_security_policy = "hard"
    return run


class TestRunVaultProviderTransport:
    def test_raises_if_no_agent_in_context(self):
        run = _make_pki_run()
        transport = RunVaultProviderTransport(
            provider="openai", bound_identity=run.identity,
        )
        req = httpx.Request("POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions")
        with pytest.raises(NoActiveRunError, match="No active RunVault run"):
            transport.handle_request(req)

    def test_rewrites_url_and_injects_pki_headers(self):
        run = _make_pki_run()
        transport = RunVaultProviderTransport(
            provider="openai", bound_identity=run.identity,
        )
        mock_response = make_httpx_response(200, {"choices": []})

        with patch.object(transport._inner, "handle_request", return_value=mock_response) as mock_inner:
            token = _CURRENT_RUN.set(run)
            try:
                result = transport.handle_request(
                    httpx.Request("POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions")
                )
            finally:
                _CURRENT_RUN.reset(token)

        sent = mock_inner.call_args[0][0]
        assert str(sent.url) == "http://proxy:8080/openai/v1/chat/completions"
        # PKI headers — both required, no legacy bearer auth.
        assert sent.headers["x-rv-certificate"] == _TEST_CERT_B64
        # JWT is freshly minted per request — assert structure (3 base64url segments) rather than equality.
        assert sent.headers["x-rv-agent-jwt"].count(".") == 2
        assert "authorization" not in sent.headers
        assert "x-goog-api-key" not in sent.headers
        assert result.status_code == 200

    def test_raises_runtime_error_if_agent_missing_pki(self):
        run = _make_pki_run()
        run.identity.private_key_bytes = None
        run.identity.certificate_b64 = None
        transport = RunVaultProviderTransport(
            provider="openai", bound_identity=run.identity,
        )

        token = _CURRENT_RUN.set(run)
        try:
            with pytest.raises(RuntimeError, match="PKI credentials"):
                transport.handle_request(
                    httpx.Request("POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions")
                )
        finally:
            _CURRENT_RUN.reset(token)

    def test_raises_typed_error_on_4xx(self):
        run = _make_pki_run()
        transport = RunVaultProviderTransport(
            provider="openai", bound_identity=run.identity,
        )
        error_resp = make_httpx_response(404, {"error": {"message": "Model not found"}})

        with patch.object(transport._inner, "handle_request", return_value=error_resp):
            token = _CURRENT_RUN.set(run)
            try:
                with pytest.raises(LLMProviderError) as exc_info:
                    transport.handle_request(
                        httpx.Request("POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions")
                    )
            finally:
                _CURRENT_RUN.reset(token)
        assert exc_info.value.provider == "openai"

    def test_raises_budget_exceeded_on_402(self):
        run = _make_pki_run()
        transport = RunVaultProviderTransport(
            provider="openai", bound_identity=run.identity,
        )
        error_resp = make_httpx_response(402, {"code": "BUDGET_CAP_REACHED", "detail": "Cap", "user_string": "Over budget"})

        with patch.object(transport._inner, "handle_request", return_value=error_resp):
            token = _CURRENT_RUN.set(run)
            try:
                with pytest.raises(BudgetExceededError):
                    transport.handle_request(
                        httpx.Request("POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions")
                    )
            finally:
                _CURRENT_RUN.reset(token)

    def test_refreshes_credentials_and_retries_on_cert_revoked(self):
        """On 401 CERTIFICATE_REVOKED, transport calls
        bound_identity.refresh_credentials() once and retries. The second
        attempt is what the caller sees."""
        run = _make_pki_run()
        transport = RunVaultProviderTransport(
            provider="openai", bound_identity=run.identity,
        )

        revoked_resp = make_httpx_response(
            401, {"code": "CERTIFICATE_REVOKED", "detail": "revoked", "user_string": "Cert rotated"}
        )
        success_resp = make_httpx_response(200, {"choices": []})

        with patch.object(
            transport._inner, "handle_request", side_effect=[revoked_resp, success_resp]
        ) as mock_inner:
            token = _CURRENT_RUN.set(run)
            try:
                result = transport.handle_request(
                    httpx.Request("POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions")
                )
            finally:
                _CURRENT_RUN.reset(token)

        run.identity.refresh_credentials.assert_called_once()
        assert mock_inner.call_count == 2
        assert result.status_code == 200


# ---------------------------------------------------------------------------
# RunVaultProviderAsyncTransport
# ---------------------------------------------------------------------------

class TestRunVaultProviderAsyncTransport:
    async def test_raises_if_no_agent_in_context(self):
        run = _make_pki_run()
        transport = RunVaultProviderAsyncTransport(
            provider="openai", bound_identity=run.identity,
        )
        req = httpx.Request("POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions")
        with pytest.raises(NoActiveRunError, match="No active RunVault run"):
            await transport.handle_async_request(req)

    async def test_rewrites_url_and_injects_pki_headers(self):
        run = _make_pki_run()
        transport = RunVaultProviderAsyncTransport(
            provider="openai", bound_identity=run.identity,
        )
        mock_response = make_httpx_response(200, {"choices": []})

        with patch.object(
            transport._inner, "handle_async_request",
            new=AsyncMock(return_value=mock_response),
        ) as mock_inner:
            token = _CURRENT_RUN.set(run)
            try:
                result = await transport.handle_async_request(
                    httpx.Request("POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions")
                )
            finally:
                _CURRENT_RUN.reset(token)

        sent = mock_inner.call_args[0][0]
        assert str(sent.url) == "http://proxy:8080/openai/v1/chat/completions"
        assert sent.headers["x-rv-certificate"] == _TEST_CERT_B64
        assert sent.headers["x-rv-agent-jwt"].count(".") == 2
        assert "authorization" not in sent.headers
        assert result.status_code == 200

    async def test_raises_typed_error_on_4xx(self):
        run = _make_pki_run()
        transport = RunVaultProviderAsyncTransport(
            provider="openai", bound_identity=run.identity,
        )
        error_resp = make_httpx_response(401, {"code": "INVALID_TOKEN", "detail": "Bad token", "user_string": "Invalid"})

        with patch.object(
            transport._inner, "handle_async_request",
            new=AsyncMock(return_value=error_resp),
        ):
            token = _CURRENT_RUN.set(run)
            try:
                with pytest.raises(TokenExpiredError):
                    await transport.handle_async_request(
                        httpx.Request("POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions")
                    )
            finally:
                _CURRENT_RUN.reset(token)
