import pytest
from unittest.mock import MagicMock

from runvault.context import _current_agent, get_rv


class TestGetRv:
    def test_returns_agent_when_context_is_set(self):
        agent = MagicMock()
        token = _current_agent.set(agent)
        try:
            assert get_rv() is agent
        finally:
            _current_agent.reset(token)

    def test_raises_runtime_error_when_not_set(self):
        try:
            token = _current_agent.set(None)
            _current_agent.reset(token)
        except Exception:
            pass

        with pytest.raises(RuntimeError, match="No active RunVault agent"):
            get_rv()

    def test_context_is_isolated_per_token(self):
        agent_a = MagicMock()
        agent_b = MagicMock()
        token_a = _current_agent.set(agent_a)
        token_b = _current_agent.set(agent_b)
        try:
            assert get_rv() is agent_b
        finally:
            _current_agent.reset(token_b)
            _current_agent.reset(token_a)
