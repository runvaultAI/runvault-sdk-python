"""Tests for runvault.identity — Identity, Run, current_run, _RunContext."""

from __future__ import annotations

import asyncio
import base64
import json
from unittest.mock import MagicMock

import pytest

from runvault.exceptions import NoActiveRunError
from runvault.identity import Identity, Run, _CURRENT_RUN, current_run


# A 32-byte private key; doesn't need to be cryptographically meaningful here —
# none of these tests exercise the signing path.
_FAKE_KEY = b"\x00" * 32
_FAKE_CERT = {"serial_number": "test-1"}


def _make_identity(agent_id: str = "test-agent") -> Identity:
    info = MagicMock()
    info.id = "00000000-0000-0000-0000-000000000001"
    info.proxy_url = "http://proxy.test:8080"
    info.llm_provider = "openai"
    info.budget = None
    info.budget_alert_threshold = None
    return Identity(
        info=info,
        api_key="rv_live_test",
        external_agent_id=agent_id,
        name="Test Agent",
        private_key_bytes=_FAKE_KEY,
        certificate=_FAKE_CERT,
        http=MagicMock(),
    )


# ─────────────────────────────────────────────────────────────────────
# current_run()
# ─────────────────────────────────────────────────────────────────────


class TestCurrentRun:
    def test_raises_when_no_active_run(self):
        with pytest.raises(NoActiveRunError, match="No active RunVault run"):
            current_run()

    def test_returns_active_run_inside_with_block(self):
        identity = _make_identity()
        with identity.run() as run:
            assert current_run() is run
            assert run.agent_id == "test-agent"

    def test_run_id_is_fresh_per_with_block(self):
        identity = _make_identity()
        with identity.run() as r1:
            run_id_1 = r1.run_id
        with identity.run() as r2:
            run_id_2 = r2.run_id
        assert run_id_1 != run_id_2

    def test_contextvar_reset_after_with_exits(self):
        identity = _make_identity()
        with identity.run():
            pass
        with pytest.raises(NoActiveRunError):
            current_run()

    def test_contextvar_reset_even_on_exception(self):
        identity = _make_identity()
        with pytest.raises(ValueError):
            with identity.run():
                raise ValueError("boom")
        with pytest.raises(NoActiveRunError):
            current_run()


# ─────────────────────────────────────────────────────────────────────
# Identity / Run shape
# ─────────────────────────────────────────────────────────────────────


class TestIdentity:
    def test_attributes_populated_from_constructor(self):
        identity = _make_identity("research-v1")
        assert identity.agent_id == "research-v1"
        assert identity.name == "Test Agent"
        assert identity.private_key_bytes == _FAKE_KEY
        assert identity.proxy_url == "http://proxy.test:8080"

    def test_certificate_is_base64_encoded_canonical_json(self):
        identity = _make_identity()
        decoded = base64.b64decode(identity.certificate_b64)
        assert json.loads(decoded) == _FAKE_CERT

    def test_hash_and_eq_by_agent_id(self):
        a1 = _make_identity("agent-1")
        a2 = _make_identity("agent-1")
        a3 = _make_identity("agent-2")
        assert a1 == a2
        assert a1 != a3
        assert hash(a1) == hash(a2)

    def test_provider_proxy_url_appends_provider(self):
        identity = _make_identity()
        assert identity.provider_proxy_url("openai") == "http://proxy.test:8080/openai"
        assert identity.provider_proxy_url("anthropic") == "http://proxy.test:8080/anthropic"


class TestRun:
    def test_run_carries_back_reference_to_identity(self):
        identity = _make_identity()
        with identity.run() as run:
            assert run.identity is identity

    def test_run_agent_id_property_reads_from_identity(self):
        identity = _make_identity("alpha")
        with identity.run() as run:
            assert run.agent_id == "alpha"

    def test_run_id_is_hex_uuid(self):
        identity = _make_identity()
        with identity.run() as run:
            # 32 hex chars, no dashes
            assert len(run.run_id) == 32
            assert all(c in "0123456789abcdef" for c in run.run_id)


# ─────────────────────────────────────────────────────────────────────
# Async context manager
# ─────────────────────────────────────────────────────────────────────


class TestAsyncRun:
    async def test_aenter_aexit(self):
        identity = _make_identity()
        async with identity.run() as run:
            assert current_run() is run
        with pytest.raises(NoActiveRunError):
            current_run()

    async def test_run_id_inherits_to_spawned_tasks(self):
        identity = _make_identity()

        async def child():
            return current_run().run_id

        async with identity.run() as run:
            child_run_id = await asyncio.create_task(child())
            assert child_run_id == run.run_id
