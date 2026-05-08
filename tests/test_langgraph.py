import pytest
from unittest.mock import MagicMock

from runvault.adapters.langgraph import _LangGraphWrapper, _unwrap_rv_error, wrap_langgraph
from runvault.context import _current_agent
from runvault.exceptions import BudgetExceededError, LLMProviderError, RunVaultError, TokenExpiredError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent():
    return MagicMock()


def make_budget_error():
    return BudgetExceededError(
        "This agent has reached its spending limit.",
        status_code=429,
        error_code="BUDGET_CAP_REACHED",
        user_string="This agent has reached its spending limit.",
    )


class MockGraph:
    def __init__(self, return_value=None, raise_exc=None):
        self._return_value = return_value
        self._raise_exc = raise_exc

    def invoke(self, *args, **kwargs):
        if self._raise_exc:
            raise self._raise_exc
        return self._return_value

    def stream(self, *args, **kwargs):
        if self._raise_exc:
            raise self._raise_exc
        yield from [{"chunk": 1}, {"chunk": 2}]


class MockAsyncGraph:
    def __init__(self, return_value=None, raise_exc=None):
        self._return_value = return_value
        self._raise_exc = raise_exc

    async def ainvoke(self, *args, **kwargs):
        if self._raise_exc:
            raise self._raise_exc
        return self._return_value

    async def astream(self, *args, **kwargs):
        if self._raise_exc:
            raise self._raise_exc
        for chunk in [{"chunk": 1}, {"chunk": 2}]:
            yield chunk


def _context_is_clear() -> bool:
    try:
        _current_agent.get()
        return False
    except LookupError:
        return True


# ---------------------------------------------------------------------------
# _unwrap_rv_error
# ---------------------------------------------------------------------------

class TestUnwrapRvError:
    def test_direct_rv_error(self):
        e = make_budget_error()
        assert _unwrap_rv_error(e) is e

    def test_rv_error_as_cause(self):
        budget_err = make_budget_error()
        wrapper = RuntimeError("connection error")
        wrapper.__cause__ = budget_err
        assert _unwrap_rv_error(wrapper) is budget_err

    def test_rv_error_as_context(self):
        budget_err = make_budget_error()
        wrapper = RuntimeError("something")
        wrapper.__context__ = budget_err
        assert _unwrap_rv_error(wrapper) is budget_err

    def test_rv_error_two_levels_deep(self):
        budget_err = make_budget_error()
        middle = RuntimeError("middle")
        middle.__cause__ = budget_err
        outer = RuntimeError("outer")
        outer.__cause__ = middle
        assert _unwrap_rv_error(outer) is budget_err

    def test_non_rv_error_returns_none(self):
        assert _unwrap_rv_error(ValueError("plain error")) is None

    def test_cyclic_chain_returns_none(self):
        e = ValueError("cycle")
        e.__cause__ = e
        assert _unwrap_rv_error(e) is None

    def test_all_subclasses_detected(self):
        for exc in [
            BudgetExceededError("budget"),
            TokenExpiredError("expired"),
            LLMProviderError("llm error", provider="openai"),
        ]:
            wrapper = RuntimeError("wrapper")
            wrapper.__cause__ = exc
            assert isinstance(_unwrap_rv_error(wrapper), RunVaultError)


# ---------------------------------------------------------------------------
# _LangGraphWrapper — sync
# ---------------------------------------------------------------------------

class TestLangGraphWrapperInvoke:
    def test_invoke_returns_result(self):
        graph = MockGraph(return_value={"output": "result"})
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=graph)
        assert wrapper.invoke({}) == {"output": "result"}

    def test_invoke_sets_context_var_during_execution(self):
        agent = make_agent()
        seen = []

        class CapturingGraph:
            def invoke(self, *args, **kwargs):
                seen.append(_current_agent.get(None))
                return {}

        wrapper = _LangGraphWrapper(agent=agent, graph=CapturingGraph())
        wrapper.invoke({})
        assert seen[0] is agent

    def test_invoke_unwraps_rv_error_from_cause(self):
        budget_err = make_budget_error()
        outer = RuntimeError("connection error")
        outer.__cause__ = budget_err
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockGraph(raise_exc=outer))
        with pytest.raises(BudgetExceededError):
            wrapper.invoke({})

    def test_invoke_reraises_non_rv_error_unchanged(self):
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockGraph(raise_exc=ValueError("plain")))
        with pytest.raises(ValueError, match="plain"):
            wrapper.invoke({})

    def test_invoke_resets_context_on_success(self):
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockGraph(return_value={}))
        wrapper.invoke({})
        assert _context_is_clear()

    def test_invoke_resets_context_on_exception(self):
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockGraph(raise_exc=RuntimeError("fail")))
        with pytest.raises(RuntimeError):
            wrapper.invoke({})
        assert _context_is_clear()


class TestLangGraphWrapperStream:
    def test_stream_yields_chunks(self):
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockGraph())
        assert list(wrapper.stream({})) == [{"chunk": 1}, {"chunk": 2}]

    def test_stream_unwraps_rv_error(self):
        budget_err = make_budget_error()
        outer = RuntimeError("conn error")
        outer.__cause__ = budget_err
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockGraph(raise_exc=outer))
        with pytest.raises(BudgetExceededError):
            list(wrapper.stream({}))

    def test_stream_reraises_non_rv_error(self):
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockGraph(raise_exc=ValueError("plain")))
        with pytest.raises(ValueError):
            list(wrapper.stream({}))

    def test_stream_resets_context_on_exception(self):
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockGraph(raise_exc=RuntimeError("fail")))
        with pytest.raises(RuntimeError):
            list(wrapper.stream({}))
        assert _context_is_clear()


# ---------------------------------------------------------------------------
# _LangGraphWrapper — async
# ---------------------------------------------------------------------------

class TestLangGraphWrapperAinvoke:
    async def test_ainvoke_returns_result(self):
        graph = MockAsyncGraph(return_value={"output": "async result"})
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=graph)
        assert await wrapper.ainvoke({}) == {"output": "async result"}

    async def test_ainvoke_sets_context_var_during_execution(self):
        agent = make_agent()
        seen = []

        class CapturingAsyncGraph:
            async def ainvoke(self, *args, **kwargs):
                seen.append(_current_agent.get(None))
                return {}

        wrapper = _LangGraphWrapper(agent=agent, graph=CapturingAsyncGraph())
        await wrapper.ainvoke({})
        assert seen[0] is agent

    async def test_ainvoke_unwraps_rv_error(self):
        budget_err = make_budget_error()
        outer = RuntimeError("conn error")
        outer.__cause__ = budget_err
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockAsyncGraph(raise_exc=outer))
        with pytest.raises(BudgetExceededError):
            await wrapper.ainvoke({})

    async def test_ainvoke_resets_context_on_success(self):
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockAsyncGraph(return_value={}))
        await wrapper.ainvoke({})
        assert _context_is_clear()

    async def test_ainvoke_resets_context_on_exception(self):
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockAsyncGraph(raise_exc=RuntimeError("fail")))
        with pytest.raises(RuntimeError):
            await wrapper.ainvoke({})
        assert _context_is_clear()


class TestLangGraphWrapperAstream:
    async def test_astream_yields_chunks(self):
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockAsyncGraph())
        chunks = [chunk async for chunk in wrapper.astream({})]
        assert chunks == [{"chunk": 1}, {"chunk": 2}]

    async def test_astream_unwraps_rv_error(self):
        budget_err = make_budget_error()
        outer = RuntimeError("conn error")
        outer.__cause__ = budget_err
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockAsyncGraph(raise_exc=outer))
        with pytest.raises(BudgetExceededError):
            async for _ in wrapper.astream({}):
                pass

    async def test_astream_resets_context_on_exception(self):
        wrapper = _LangGraphWrapper(agent=make_agent(), graph=MockAsyncGraph(raise_exc=RuntimeError("fail")))
        with pytest.raises(RuntimeError):
            async for _ in wrapper.astream({}):
                pass
        assert _context_is_clear()


# ---------------------------------------------------------------------------
# wrap_langgraph
# ---------------------------------------------------------------------------

class TestWrapLangGraph:
    def test_binds_wrapper_to_agent(self):
        agent = make_agent()
        graph = MockGraph(return_value={})
        wrap_langgraph(agent, graph)
        agent._bind_adapter.assert_called_once()
        wrapper = agent._bind_adapter.call_args[0][0]
        assert isinstance(wrapper, _LangGraphWrapper)
        assert wrapper._agent is agent
        assert wrapper._graph is graph
