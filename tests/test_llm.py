"""Tests for LLM factories and runvault.__init__ lazy loading."""

import sys
import pytest
from unittest.mock import MagicMock, patch

import runvault


# ---------------------------------------------------------------------------
# runvault.__init__ lazy loading
# ---------------------------------------------------------------------------

class TestSdkLazyLoading:
    def test_chat_openai_is_callable(self):
        assert callable(runvault.ChatOpenAI)

    def test_openai_is_callable(self):
        assert callable(runvault.OpenAI)

    def test_async_openai_is_callable(self):
        assert callable(runvault.AsyncOpenAI)

    def test_chat_anthropic_is_callable(self):
        assert callable(runvault.ChatAnthropic)

    def test_anthropic_is_callable(self):
        assert callable(runvault.Anthropic)

    def test_async_anthropic_is_callable(self):
        assert callable(runvault.AsyncAnthropic)

    def test_chat_google_generative_ai_is_callable(self):
        assert callable(runvault.ChatGoogleGenerativeAI)

    def test_unknown_attribute_raises_attribute_error(self):
        with pytest.raises(AttributeError, match="has no attribute"):
            _ = runvault.NonExistentFactory


# ---------------------------------------------------------------------------
# runvault.llm.openai factories
# ---------------------------------------------------------------------------

class TestChatOpenAIFactory:
    def test_returns_langchain_chat_openai_instance(self):
        from langchain_openai import ChatOpenAI as LangchainChatOpenAI
        from runvault.llm.openai import ChatOpenAI
        llm = ChatOpenAI(model="gpt-4o-mini")
        assert isinstance(llm, LangchainChatOpenAI)

    def test_raises_import_error_when_langchain_openai_missing(self):
        from runvault.llm.openai import ChatOpenAI
        with patch.dict(sys.modules, {"langchain_openai": None}):
            with pytest.raises(ImportError, match="langchain-openai"):
                ChatOpenAI(model="gpt-4o-mini")


class TestOpenAIFactory:
    def test_returns_openai_instance(self):
        from openai import OpenAI as RealOpenAI
        from runvault.llm.openai import OpenAI
        client = OpenAI()
        assert isinstance(client, RealOpenAI)

    def test_raises_import_error_when_openai_missing(self):
        from runvault.llm.openai import OpenAI
        with patch.dict(sys.modules, {"openai": None}):
            with pytest.raises(ImportError, match="openai"):
                OpenAI()


class TestAsyncOpenAIFactory:
    def test_returns_async_openai_instance(self):
        from openai import AsyncOpenAI as RealAsyncOpenAI
        from runvault.llm.openai import AsyncOpenAI
        client = AsyncOpenAI()
        assert isinstance(client, RealAsyncOpenAI)

    def test_raises_import_error_when_openai_missing(self):
        from runvault.llm.openai import AsyncOpenAI
        with patch.dict(sys.modules, {"openai": None}):
            with pytest.raises(ImportError, match="openai"):
                AsyncOpenAI()


# ---------------------------------------------------------------------------
# runvault.llm.anthropic factories
# ---------------------------------------------------------------------------

class TestChatAnthropicFactory:
    def test_returns_langchain_chat_anthropic_instance(self):
        from langchain_anthropic import ChatAnthropic as LangchainChatAnthropic
        from runvault.llm.anthropic import ChatAnthropic
        llm = ChatAnthropic(model="claude-opus-4-5")
        assert isinstance(llm, LangchainChatAnthropic)

    def test_raises_import_error_when_langchain_anthropic_missing(self):
        from runvault.llm.anthropic import ChatAnthropic
        with patch.dict(sys.modules, {"langchain_anthropic": None}):
            with pytest.raises(ImportError, match="langchain-anthropic"):
                ChatAnthropic(model="claude-opus-4-5")


class TestAnthropicFactory:
    def test_returns_anthropic_instance(self):
        from anthropic import Anthropic as RealAnthropic
        from runvault.llm.anthropic import Anthropic
        client = Anthropic()
        assert isinstance(client, RealAnthropic)

    def test_raises_import_error_when_anthropic_missing(self):
        from runvault.llm.anthropic import Anthropic
        with patch.dict(sys.modules, {"anthropic": None}):
            with pytest.raises(ImportError, match="anthropic"):
                Anthropic()


class TestAsyncAnthropicFactory:
    def test_returns_async_anthropic_instance(self):
        from anthropic import AsyncAnthropic as RealAsyncAnthropic
        from runvault.llm.anthropic import AsyncAnthropic
        client = AsyncAnthropic()
        assert isinstance(client, RealAsyncAnthropic)

    def test_raises_import_error_when_anthropic_missing(self):
        from runvault.llm.anthropic import AsyncAnthropic
        with patch.dict(sys.modules, {"anthropic": None}):
            with pytest.raises(ImportError, match="anthropic"):
                AsyncAnthropic()


# ---------------------------------------------------------------------------
# runvault.llm.google factories
# ---------------------------------------------------------------------------

class TestChatGoogleGenerativeAIFactory:
    def test_returns_langchain_google_instance(self):
        from langchain_google_genai import ChatGoogleGenerativeAI as LangchainGoogleAI
        from runvault.llm.google import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
        assert isinstance(llm, LangchainGoogleAI)

    def test_raises_import_error_when_langchain_google_genai_missing(self):
        from runvault.llm.google import ChatGoogleGenerativeAI
        with patch.dict(sys.modules, {"langchain_google_genai": None}):
            with pytest.raises(ImportError, match="langchain-google-genai"):
                ChatGoogleGenerativeAI(model="gemini-2.0-flash")

