import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from runvault.runtime.agent import Agent
from runvault.auth.registration import AgentInfo


def _make_agent(proxy_url: str = "http://proxy:8080") -> Agent:
    info = AgentInfo(
        id=uuid.UUID("a3a268ce-e2db-4abd-ba01-f69057e6e825"),
        agent_id="test-agent",
        name="Test Agent",
        project_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        run_id=uuid.UUID("40159395-641f-4b4c-82b2-0503e0dff67c"),
        budget=None,
        budget_alert_threshold=None,
        llm_provider="openai",
        proxy_url=proxy_url,
        created=True,
    )
    return Agent(
        info=info,
        http=MagicMock(),
        api_key="rv_live_test",
        external_agent_id="test-agent",
        name="Test Agent",
    )


# ---------------------------------------------------------------------------
# proxy_url
# ---------------------------------------------------------------------------

class TestAgentProxyUrl:
    def test_appends_provider(self):
        agent = _make_agent()
        assert agent.proxy_url("openai") == "http://proxy:8080/openai"

    def test_strips_trailing_slash(self):
        agent = _make_agent(proxy_url="http://proxy:8080/")
        assert agent.proxy_url("openai") == "http://proxy:8080/openai"

    def test_different_providers(self):
        agent = _make_agent()
        assert agent.proxy_url("anthropic") == "http://proxy:8080/anthropic"
        assert agent.proxy_url("google") == "http://proxy:8080/google"


# ---------------------------------------------------------------------------
# invoke / stream / ainvoke / astream
# ---------------------------------------------------------------------------

class TestAgentInvoke:
    def test_invoke_delegates_to_adapter(self):
        agent = _make_agent()
        adapter = MagicMock()
        adapter.invoke.return_value = {"output": "result"}
        agent._bind_adapter(adapter)
        assert agent.invoke({"input": "x"}) == {"output": "result"}
        adapter.invoke.assert_called_once_with({"input": "x"})

    def test_invoke_raises_if_no_adapter(self):
        agent = _make_agent()
        with pytest.raises(RuntimeError, match="No framework adapter"):
            agent.invoke({})

    def test_stream_delegates_to_adapter(self):
        agent = _make_agent()
        adapter = MagicMock()
        adapter.stream.return_value = iter([{"chunk": 1}])
        agent._bind_adapter(adapter)
        agent.stream({"input": "x"})
        adapter.stream.assert_called_once()

    def test_stream_raises_if_no_adapter(self):
        agent = _make_agent()
        with pytest.raises(RuntimeError, match="No framework adapter"):
            agent.stream({})

    async def test_ainvoke_delegates_to_adapter(self):
        agent = _make_agent()
        adapter = MagicMock()
        adapter.ainvoke = AsyncMock(return_value={"output": "async"})
        agent._bind_adapter(adapter)
        result = await agent.ainvoke({"input": "x"})
        assert result == {"output": "async"}
        adapter.ainvoke.assert_called_once_with({"input": "x"})

    async def test_ainvoke_raises_if_no_adapter(self):
        agent = _make_agent()
        with pytest.raises(RuntimeError, match="No framework adapter"):
            await agent.ainvoke({})

    async def test_astream_delegates_to_adapter(self):
        agent = _make_agent()

        async def _gen():
            yield {"chunk": 1}
            yield {"chunk": 2}

        adapter = MagicMock()
        adapter.astream.return_value = _gen()
        agent._bind_adapter(adapter)
        chunks = [c async for c in agent.astream({})]
        assert chunks == [{"chunk": 1}, {"chunk": 2}]

    async def test_astream_raises_if_no_adapter(self):
        agent = _make_agent()
        with pytest.raises(RuntimeError, match="No framework adapter"):
            async for _ in agent.astream({}):
                pass


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestAgentContextManager:
    def test_enter_returns_self(self):
        agent = _make_agent()
        assert agent.__enter__() is agent

    def test_exit_calls_close(self):
        agent = _make_agent()
        with patch.object(agent, "close") as mock_close:
            agent.__exit__(None, None, None)
        mock_close.assert_called_once()

    def test_used_as_context_manager(self):
        with _make_agent() as agent:
            assert isinstance(agent, Agent)

