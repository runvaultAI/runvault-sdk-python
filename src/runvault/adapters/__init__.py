"""Framework adapter registry.

Maps framework name strings (used in runvault.init(framework=...)) to their
wrap_* functions. Each wrap function accepts (agent, app) and calls
agent._bind_adapter() to attach the wrapper.

To add a new adapter:
  1. Create adapters/<framework>.py following langgraph.py as the reference.
  2. Add an entry here.
"""

from runvault.adapters.langgraph import wrap_langgraph

ADAPTERS: dict[str, callable] = {
    "langgraph": wrap_langgraph,
}
