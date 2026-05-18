"""Tests for runvault.llm — build_llm dispatch.

These tests cover the dispatch logic. The wired classes themselves are
covered separately wherever they intercept HTTP (test_transport.py for
the request-time JWT injection).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from runvault.llm import build_llm
from runvault.llm.langchain import (
    wire_chat_anthropic,
    wire_chat_google,
    wire_chat_openai,
    wire_openai_client,
)


@pytest.fixture
def identity() -> MagicMock:
    identity = MagicMock()
    identity.proxy_url = "http://proxy.test:8080"
    identity.provider_proxy_url = lambda p: f"http://proxy.test:8080/{p}"
    return identity


# ─────────────────────────────────────────────────────────────────────
# build_llm — dispatch by class
# ─────────────────────────────────────────────────────────────────────


class TestBuildLLMDispatch:
    def test_unknown_class_raises_typeerror(self, identity):
        class SomethingElse:
            pass

        with pytest.raises(TypeError, match="build_llm does not support"):
            build_llm(identity, SomethingElse)

    def test_chat_openai_returns_subclass(self, identity):
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            pytest.skip("langchain-openai not installed")

        wired = build_llm(identity, ChatOpenAI)
        assert issubclass(wired, ChatOpenAI)
        assert wired.__name__ == "RVChatOpenAI"

    def test_mro_walk_finds_parent(self, identity):
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            pytest.skip("langchain-openai not installed")

        class UserSubclass(ChatOpenAI):
            pass

        wired = build_llm(identity, UserSubclass)
        # Wired class inherits from UserSubclass (via wire_chat_openai)
        assert issubclass(wired, UserSubclass)


# ─────────────────────────────────────────────────────────────────────
# Wiring functions — return a usable subclass
# ─────────────────────────────────────────────────────────────────────


class TestWirings:
    def test_wire_chat_openai_subclass(self, identity):
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            pytest.skip("langchain-openai not installed")

        wired = wire_chat_openai(ChatOpenAI, identity)
        assert issubclass(wired, ChatOpenAI)

    def test_wire_chat_anthropic_subclass(self, identity):
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            pytest.skip("langchain-anthropic not installed")

        wired = wire_chat_anthropic(ChatAnthropic, identity)
        assert issubclass(wired, ChatAnthropic)

    def test_wire_openai_client_subclass_sync(self, identity):
        try:
            from openai import OpenAI
        except ImportError:
            pytest.skip("openai not installed")

        wired = wire_openai_client(OpenAI, identity)
        assert issubclass(wired, OpenAI)
        assert wired.__name__ == "RVOpenAI"

    def test_wire_openai_client_subclass_async(self, identity):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            pytest.skip("openai not installed")

        wired = wire_openai_client(AsyncOpenAI, identity)
        assert issubclass(wired, AsyncOpenAI)
        assert wired.__name__ == "RVAsyncOpenAI"
