# LLM Clients

Every LLM client used with RunVault is built via `identity.build_llm(BaseClass)`. The method returns a dynamic subclass of `BaseClass` whose constructor injects the proxy URL and a RunVault-aware `httpx` client. All inherited methods (`.invoke()`, `.stream()`, `.bind_tools()`, async, batching, retries) continue to work as upstream.

## Supported base classes

| Provider | Class | Install extra |
|---|---|---|
| LangChain ↔ OpenAI | `langchain_openai.ChatOpenAI` | `runvault[langchain-openai]` |
| LangChain ↔ Anthropic | `langchain_anthropic.ChatAnthropic` | `runvault[langchain-anthropic]` |
| LangChain ↔ Google | `langchain_google_genai.ChatGoogleGenerativeAI` | `runvault[langchain-google]` |
| OpenAI SDK (sync) | `openai.OpenAI` | `runvault[openai]` |
| OpenAI SDK (async) | `openai.AsyncOpenAI` | `runvault[openai]` |
| CrewAI | any subclass of `crewai.BaseLLM` | `runvault[crewai]` |

User subclasses of any supported class are picked up through an MRO walk — your own `class MyChat(ChatOpenAI): ...` works without changes.

## LangChain — ChatOpenAI

```python
from runvault import RunVault
from langchain_openai import ChatOpenAI

rv = RunVault(api_key="rv_live_...", be_url="...")
identity = rv.register_agent(agent_id="research-v1", name="Research Agent")

RVChat = identity.build_llm(ChatOpenAI)
llm = RVChat(model="gpt-4o-mini")

with identity.run():
    print(llm.invoke("Hello!").content)
```

`RVChat` accepts every constructor argument `ChatOpenAI` accepts. Tool binding, structured output, and streaming all work unchanged.

## LangChain — ChatAnthropic

```python
from langchain_anthropic import ChatAnthropic

RVAnthropic = identity.build_llm(ChatAnthropic)
llm = RVAnthropic(model="claude-3-5-sonnet-latest")
```

## LangChain — ChatGoogleGenerativeAI

```python
from langchain_google_genai import ChatGoogleGenerativeAI

RVGoogle = identity.build_llm(ChatGoogleGenerativeAI)
llm = RVGoogle(model="gemini-1.5-pro")
```

## Bare OpenAI SDK

`build_llm` also wires the raw `openai` SDK clients — useful when you don't want a framework wrapper.

```python
from openai import OpenAI, AsyncOpenAI

RVOpenAI = identity.build_llm(OpenAI)
client = RVOpenAI()

with identity.run():
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello!"}],
    )
```

Async:

```python
RVAsync = identity.build_llm(AsyncOpenAI)
client = RVAsync()

async with identity.run():
    await client.chat.completions.create(...)
```

## CrewAI

CrewAI's `BaseLLM` is abstract, so RunVault provides a concrete subclass that talks to the proxy via the OpenAI SDK with our transport.

```python
import crewai
from crewai import Agent, Crew, Task

RVCrewLLM = identity.build_llm(crewai.BaseLLM)
llm = RVCrewLLM(model="gpt-4o-mini")

researcher = Agent(role="Researcher", goal="...", llm=llm)
task = Task(description="Find recent papers on …", agent=researcher)
crew = Crew(agents=[researcher], tasks=[task])

with identity.run():
    crew.kickoff()
```

The CrewAI wiring also accepts `response_model=<PydanticClass>` on `.call()` / `.acall()` for structured output via OpenAI's `chat.completions.parse()` API.

## Reusing one client across many runs

A client built by `build_llm` is **bound to the identity** that built it. The active `Run` is read fresh from the `ContextVar` on every request, so a single client serves any number of runs:

```python
llm = identity.build_llm(ChatOpenAI)(model="gpt-4o-mini")

with identity.run():
    llm.invoke("first call")        # tagged with run_id #1

with identity.run():
    llm.invoke("second call")       # tagged with run_id #2
```

Construct your LLMs once, reuse them widely.

## Errors

| Situation | Exception |
|---|---|
| `BaseClass` is not in the dispatch table | `TypeError` |
| LLM invoked outside a `with identity.run():` block | `NoActiveRunError` |
| LLM is bound to a different identity than the active run | `CrossIdentityError` (`"hard"`) / `CrossIdentityWarning` (`"soft"`) |
| Agent has spent its budget | `BudgetExceededError` |
| Admin suspended the agent | `AgentSuspendedError` |

See the [Exceptions reference](../api/exceptions.md) for the full catalog.
