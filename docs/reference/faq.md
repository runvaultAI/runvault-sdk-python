# FAQ

### Do I have to use a framework?

No. `pip install runvault` alone is enough to call the proxy. Use `identity.build_llm(openai.OpenAI)` (or `AsyncOpenAI`) for raw access without any framework wrapper.

### Does `build_llm` support framework *X* that isn't in the dispatch table?

Not yet. Until an entry exists, the call raises `TypeError`. As a workaround you can still drive the proxy from any framework that accepts a custom `httpx` client or a custom `base_url` — open an issue if you want a specific framework supported as a first-class wiring.

### Is `with identity.run():` required for every call?

Yes. Every outbound LLM request reads the active `Run` from a `ContextVar`. No active run ⇒ `NoActiveRunError` before the request is sent. This is by design: silent fallback would mask missing `run_id`s in spend tracking.

### Can two `with identity.run():` blocks be active at once?

Not in the same task. A `ContextVar` is single-valued per execution context. Nested runs are allowed and shadow each other; concurrent runs in independent `asyncio` tasks see independent values.

### Can I share an `Identity` across processes?

Yes, indirectly. The on-disk credentials in `~/.runvault/<agent_id>/` are reused by any process that registers the same `agent_id`. The in-memory `Identity` object is process-local.

### What happens if my agent's local credentials are lost (volume wipe, fresh container)?

The SDK detects the situation on the next `register_agent(...)` call and transparently calls `/credentials/refresh` to mint fresh credentials. No code change required.

### Do I need `RV_CA_PUBLIC_KEY` set?

In production, yes. Without it the SDK does not verify the CA signature on the certificates it receives and logs a warning. Acceptable for local development.

### How is this different from putting an OpenAI key in `OPENAI_API_KEY`?

The agent never holds the provider key. Credentials are short-lived (5-minute JWT TTL, rotatable certificate). Spend is enforced at the proxy, so a leaked SDK install cannot exceed the budget set in the dashboard. The platform sees every call.

### Where do I report a bug?

<https://github.com/runvaultAI/runvault-sdk-python/issues>
