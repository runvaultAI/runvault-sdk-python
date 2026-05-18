# build_llm

`identity.build_llm(BaseClass)` is the single entry point for constructing a proxy-routed LLM. It dispatches on the base class and returns a dynamic subclass whose constructor injects the proxy URL and a RunVault-aware `httpx` client.

```python
RVChat = identity.build_llm(ChatOpenAI)
llm = RVChat(model="gpt-4o-mini")
```

Inherited methods (`.invoke()`, `.stream()`, `.bind_tools()`, async, batching) work unchanged. Tool-binding, streaming, structured output, `isinstance` checks — all behave as upstream.

## Dispatch table

| Base class | Required extra |
|---|---|
| `langchain_openai.ChatOpenAI` | `runvault[langchain-openai]` |
| `langchain_anthropic.ChatAnthropic` | `runvault[langchain-anthropic]` |
| `langchain_google_genai.ChatGoogleGenerativeAI` | `runvault[langchain-google]` |
| `openai.OpenAI` | `runvault[openai]` |
| `openai.AsyncOpenAI` | `runvault[openai]` |
| Any subclass of `crewai.BaseLLM` | `runvault[crewai]` |

User subclasses of any supported class are picked up through MRO. Unknown classes raise `TypeError`.

## Identity binding

Every wired client is **bound to the identity that built it**. That identity's key signs every JWT the client mints — even if a different identity owns the active run. The cross-identity guard fires in that case (see [Authentication](../guides/authentication.md#cross-identity-guard)).

## Per-framework recipes

See [LLM Clients](../guides/llm-clients.md) for ready-to-paste examples for each supported framework.

---

## Reference

::: runvault.llm.build_llm
    options:
      show_source: false
      show_root_heading: true
      show_signature: true
