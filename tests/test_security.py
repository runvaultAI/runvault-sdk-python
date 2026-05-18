"""Tests for the cross-identity guard, host allowlist, and
NoActiveRunError surface added to the transport."""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock, patch

import httpx
import pytest

from runvault.exceptions import (
    CrossIdentityError,
    CrossIdentityWarning,
    NoActiveRunError,
    UntrustedHostError,
)
from runvault.http.transport import (
    PLACEHOLDER_BASE,
    RunVaultProviderTransport,
)
from runvault.identity import _CURRENT_RUN, current_run

from tests.conftest import make_httpx_response, make_test_identity, make_test_run


def _make_transport(bound_identity, mock_response):
    """Return a sync transport whose inner HTTP layer is mocked."""
    transport = RunVaultProviderTransport(
        provider="openai", bound_identity=bound_identity,
    )
    transport._inner = MagicMock()
    transport._inner.handle_request.return_value = mock_response
    return transport


# ---------------------------------------------------------------------------
# NoActiveRunError
# ---------------------------------------------------------------------------

class TestNoActiveRunError:
    def test_current_run_outside_block_raises(self):
        # _CURRENT_RUN.get() raises LookupError; current_run() should
        # translate that into the typed NoActiveRunError.
        with pytest.raises(NoActiveRunError):
            current_run()

    def test_transport_raises_when_no_run(self):
        identity = make_test_identity()
        transport = RunVaultProviderTransport(
            provider="openai", bound_identity=identity,
        )
        request = httpx.Request("POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions")
        with pytest.raises(NoActiveRunError):
            transport.handle_request(request)


# ---------------------------------------------------------------------------
# Host allowlist
# ---------------------------------------------------------------------------

class TestHostAllowlist:
    def test_non_proxy_host_raises(self):
        identity = make_test_identity(proxy_url="http://proxy.test:8080")
        transport = _make_transport(identity, make_httpx_response(200, {}))
        run = make_test_run(identity=identity)
        token = _CURRENT_RUN.set(run)
        try:
            request = httpx.Request("POST", "http://attacker.example/v1/chat")
            with pytest.raises(UntrustedHostError):
                transport.handle_request(request)
            # No outbound network call should have been issued.
            transport._inner.handle_request.assert_not_called()
        finally:
            _CURRENT_RUN.reset(token)

    def test_placeholder_host_is_allowed(self):
        """Requests with the PLACEHOLDER_BASE host pass — the rewrite
        step below the check swaps it for the real proxy URL."""
        identity = make_test_identity(proxy_url="http://proxy.test:8080")
        transport = _make_transport(identity, make_httpx_response(200, {}))
        run = make_test_run(identity=identity)
        token = _CURRENT_RUN.set(run)
        try:
            request = httpx.Request(
                "POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions",
            )
            transport.handle_request(request)
            transport._inner.handle_request.assert_called_once()
        finally:
            _CURRENT_RUN.reset(token)


# ---------------------------------------------------------------------------
# Cross-identity guard
# ---------------------------------------------------------------------------

class TestCrossIdentityGuard:
    def test_same_identity_passes(self):
        identity = make_test_identity(agent_id="agent-a")
        transport = _make_transport(identity, make_httpx_response(200, {}))
        run = make_test_run(identity=identity)
        token = _CURRENT_RUN.set(run)
        try:
            request = httpx.Request(
                "POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions",
            )
            transport.handle_request(request)
            transport._inner.handle_request.assert_called_once()
        finally:
            _CURRENT_RUN.reset(token)

    def test_hard_mode_raises_on_mismatch(self):
        bound = make_test_identity(agent_id="agent-a", security_policy="hard")
        active = make_test_identity(agent_id="agent-b", security_policy="hard")
        transport = _make_transport(bound, make_httpx_response(200, {}))
        run = make_test_run(identity=active)
        token = _CURRENT_RUN.set(run)
        try:
            request = httpx.Request(
                "POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions",
            )
            with pytest.raises(CrossIdentityError):
                transport.handle_request(request)
            transport._inner.handle_request.assert_not_called()
        finally:
            _CURRENT_RUN.reset(token)

    def test_soft_mode_warns_and_proceeds_with_bound_identity_key(self):
        bound = make_test_identity(agent_id="agent-a")
        active = make_test_identity(agent_id="agent-b", security_policy="soft")
        transport = _make_transport(bound, make_httpx_response(200, {}))

        # security_policy on the run owner's identity is "soft", and the
        # Run picks it up via effective_security_policy in conftest.
        run = make_test_run(identity=active)
        token = _CURRENT_RUN.set(run)
        try:
            request = httpx.Request(
                "POST", f"{PLACEHOLDER_BASE}/openai/v1/chat/completions",
            )
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                # `create_agent_jwt` is imported lazily inside
                # _build_signed_request, so patch the source module.
                with patch(
                    "runvault.auth.signer.create_agent_jwt",
                    return_value="signed.jwt.token",
                ) as mock_sign:
                    transport.handle_request(request)

            # Exactly one CrossIdentityWarning emitted.
            cross_warnings = [w for w in caught if issubclass(w.category, CrossIdentityWarning)]
            assert len(cross_warnings) == 1

            # The JWT was signed with the BOUND identity's key, not the
            # active run's. This is the "soft mode bills the bound
            # identity" semantic in code form.
            kwargs = mock_sign.call_args.kwargs
            assert kwargs["agent_id"] == bound.db_agent_id
            assert kwargs["private_key_bytes"] is bound.private_key_bytes
            # run_id still comes from the active run.
            assert kwargs["run_id"] == run.run_id
        finally:
            _CURRENT_RUN.reset(token)


# ---------------------------------------------------------------------------
# security_policy override on identity.run()
# ---------------------------------------------------------------------------

class TestSecurityPolicyOverride:
    def test_identity_default_is_hard(self):
        from runvault.identity import Identity

        # Identity defaults to "hard" — direct attribute check; no
        # registration round-trip needed for this assertion.
        info = MagicMock()
        info.proxy_url = "http://proxy.test:8080"
        info.llm_provider = "openai"
        identity = Identity(
            info=info,
            api_key="rv_test",
            external_agent_id="a",
            name="A",
            private_key_bytes=b"\x00" * 32,
            certificate={"serial_number": "x"},
            http=MagicMock(),
        )
        assert identity.security_policy == "hard"

    def test_run_override_wins_over_identity_default(self):
        from runvault.identity import Identity

        info = MagicMock()
        info.proxy_url = "http://proxy.test:8080"
        info.llm_provider = "openai"
        identity = Identity(
            info=info,
            api_key="rv_test",
            external_agent_id="a",
            name="A",
            private_key_bytes=b"\x00" * 32,
            certificate={"serial_number": "x"},
            http=MagicMock(),
            security_policy="hard",
        )
        with identity.run(security_policy="soft") as run:
            assert run.effective_security_policy == "soft"
        # Identity default is unchanged.
        assert identity.security_policy == "hard"
