"""CrewAI wiring — RunVault-routed ``BaseLLM`` subclass.

CrewAI's ``BaseLLM`` is abstract: we implement ``.call()`` /
``.acall()`` from scratch, talking to the proxy via the OpenAI Python
SDK pre-configured with our transport. The implementation handles
multi-turn tool-call loops since CrewAI relies on the LLM client to
do its own tool-call orchestration.

A separate dependency on ``crewai`` and ``openai`` is required; both
are imported lazily inside ``wire_crewai`` so importing
``runvault.llm`` works without them.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from runvault.llm.http import make_async_client, make_sync_client

if TYPE_CHECKING:
    from runvault.identity import Identity

log = logging.getLogger(__name__)

# Cap on tool-call iterations to prevent run-away cycles when the model
# keeps requesting tools forever. 8 is well above any practical use
# case (the longest CrewAI examples we observed top out at 4–5).
MAX_TOOL_ITERATIONS = 8

_PLACEHOLDER_API_KEY = "rv-placeholder"


def wire_crewai(base_cls: type, identity: "Identity") -> type:
    """Return a concrete ``BaseLLM`` subclass wired through the proxy.

    Args:
        base_cls: ``crewai.BaseLLM`` itself, or a user subclass of it.
                  In either case we subclass ``base_cls`` and provide a
                  working ``.call()`` / ``.acall()``.
        identity: The Identity whose proxy URL and credentials to wire in.

    Raises:
        ImportError: If ``crewai`` or ``openai`` is not installed.
    """
    try:
        import crewai  # type: ignore[import-not-found]  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "CrewAI integration requires the `crewai` package. "
            "Install with: pip install 'runvault[crewai]'"
        ) from exc

    try:
        from openai import AsyncOpenAI as _AsyncOpenAI
        from openai import OpenAI as _OpenAI
    except ImportError as exc:
        raise ImportError(
            "CrewAI integration requires the `openai` package. "
            "Install with: pip install openai"
        ) from exc

    base_url = f"{identity.provider_proxy_url('openai')}/v1"
    sync_http = make_sync_client("openai", bound_identity=identity)
    async_http = make_async_client("openai", bound_identity=identity)

    class RunVaultCrewLLM(base_cls):  # type: ignore[misc, valid-type]
        """CrewAI-compatible LLM that routes through the RunVault proxy.

        Constructor forwards ``model`` (and any extra kwargs CrewAI
        wants on ``BaseLLM``) to the parent ``BaseLLM.__init__``. The
        OpenAI client is built once and reused — the active Run is
        looked up by our transport on every request.
        """

        def __init__(self, model: str, **kwargs: Any) -> None:
            super().__init__(model=model, **kwargs)
            self._client = _OpenAI(
                api_key=_PLACEHOLDER_API_KEY,
                base_url=base_url,
                http_client=sync_http,
            )
            self._aclient = _AsyncOpenAI(
                api_key=_PLACEHOLDER_API_KEY,
                base_url=base_url,
                http_client=async_http,
            )

        # ── sync ──────────────────────────────────────────────────────
        def call(
            self,
            messages: Any,
            tools: Any = None,
            callbacks: Any = None,
            available_functions: Any = None,
            from_task: Any = None,
            from_agent: Any = None,
            response_model: Any = None,
            **kwargs: Any,
        ) -> Any:
            """Run a sync chat completion, looping if the model calls tools.

            ``response_model`` is honoured for structured-output tasks
            (CrewAI 0.12x+ passes a Pydantic class). Unknown kwargs are
            absorbed so future CrewAI additions don't crash the call.
            """
            return self._chat_loop_sync(
                messages, tools, available_functions, response_model,
            )

        # ── async ─────────────────────────────────────────────────────
        async def acall(
            self,
            messages: Any,
            tools: Any = None,
            callbacks: Any = None,
            available_functions: Any = None,
            from_task: Any = None,
            from_agent: Any = None,
            response_model: Any = None,
            **kwargs: Any,
        ) -> Any:
            """Run an async chat completion, looping if the model calls tools."""
            return await self._chat_loop_async(
                messages, tools, available_functions, response_model,
            )

        def supports_function_calling(self) -> bool:
            """OpenAI-compatible endpoints support function calling."""
            return True

        # ── internals ─────────────────────────────────────────────────
        def _build_params(
            self,
            messages: Any,
            tools: Any,
            response_model: Any = None,
        ) -> dict:
            params: dict = {"model": self.model, "messages": messages}
            if tools:
                params["tools"] = tools
            if response_model is not None:
                # OpenAI's `parse()` accepts a Pydantic class here; the
                # `create()` path also tolerates a JSON-schema dict if
                # CrewAI ever passes one instead.
                params["response_format"] = response_model
            return params

        def _terminal_content(self, choice: Any, response_model: Any) -> str:
            """Pick the content to return to CrewAI for the final message.

            When ``response_model`` is set and the OpenAI `.parse()` call
            populated ``choice.parsed`` with a Pydantic instance, return
            its JSON serialisation — CrewAI validates that string against
            the same model on its side. Otherwise return the raw text.
            """
            if response_model is not None:
                parsed = getattr(choice, "parsed", None)
                if parsed is not None and hasattr(parsed, "model_dump_json"):
                    return parsed.model_dump_json()
            return choice.content or ""

        def _invoke_tool(self, tool_call: Any, available_functions: dict) -> str:
            """Execute one tool call, returning its result as a string."""
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            fn = available_functions.get(name)
            if fn is None:
                return f"ERROR: tool {name!r} not available"
            try:
                result = fn(**args)
            except Exception as exc:  # pragma: no cover — surfaces tool errors
                return f"ERROR: tool {name!r} raised {type(exc).__name__}: {exc}"
            return result if isinstance(result, str) else json.dumps(result, default=str)

        def _chat_loop_sync(
            self,
            messages: Any,
            tools: Any,
            available_functions: Any,
            response_model: Any = None,
        ) -> Any:
            # When CrewAI asks for structured output (Pydantic class), use
            # OpenAI's `parse()` so the SDK returns a validated instance on
            # `choice.parsed`. Tool-calling intermediate turns still flow
            # through unchanged; the schema only constrains terminal text.
            use_parse = response_model is not None
            msgs = list(messages)
            for _ in range(MAX_TOOL_ITERATIONS):
                params = self._build_params(msgs, tools, response_model)
                if use_parse:
                    response = self._client.chat.completions.parse(**params)
                else:
                    response = self._client.chat.completions.create(**params)
                choice = response.choices[0].message
                tool_calls = getattr(choice, "tool_calls", None)
                if not tool_calls or not available_functions:
                    return self._terminal_content(choice, response_model)
                msgs.append(choice.model_dump())
                for tc in tool_calls:
                    msgs.append({
                        "role":         "tool",
                        "tool_call_id": tc.id,
                        "content":      self._invoke_tool(tc, available_functions),
                    })
            raise RuntimeError(
                f"RunVaultCrewLLM exceeded {MAX_TOOL_ITERATIONS} tool-call iterations. "
                f"Check for an infinite tool-calling loop in the agent's task."
            )

        async def _chat_loop_async(
            self,
            messages: Any,
            tools: Any,
            available_functions: Any,
            response_model: Any = None,
        ) -> Any:
            use_parse = response_model is not None
            msgs = list(messages)
            for _ in range(MAX_TOOL_ITERATIONS):
                params = self._build_params(msgs, tools, response_model)
                if use_parse:
                    response = await self._aclient.chat.completions.parse(**params)
                else:
                    response = await self._aclient.chat.completions.create(**params)
                choice = response.choices[0].message
                tool_calls = getattr(choice, "tool_calls", None)
                if not tool_calls or not available_functions:
                    return self._terminal_content(choice, response_model)
                msgs.append(choice.model_dump())
                for tc in tool_calls:
                    msgs.append({
                        "role":         "tool",
                        "tool_call_id": tc.id,
                        "content":      self._invoke_tool(tc, available_functions),
                    })
            raise RuntimeError(
                f"RunVaultCrewLLM exceeded {MAX_TOOL_ITERATIONS} tool-call iterations. "
                f"Check for an infinite tool-calling loop in the agent's task."
            )

    RunVaultCrewLLM.__name__ = "RunVaultCrewLLM"
    RunVaultCrewLLM.__qualname__ = "RunVaultCrewLLM"
    return RunVaultCrewLLM
