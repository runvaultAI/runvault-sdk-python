# Installation

The base `runvault` package is small. LLM provider and framework support are opt-in via pip extras, so your environment never grows beyond what you actually use.

## Requirements

- **Python 3.9 or newer** (tested on 3.9 – 3.13).
- A reachable **RunVault backend** — the `be_url` you pass to `RunVault(...)`.
- A **RunVault project API key** (`rv_live_…`) issued from your dashboard.
- *(Recommended for production)* `RV_CA_PUBLIC_KEY` environment variable set to your deployment's RunVault CA public key. When present, the SDK verifies the CA signature on every certificate it receives.

## Install the SDK

Core only — enough to call the proxy from raw `httpx`:

```bash
pip install runvault
```

Add the extras that match your stack:

```bash
pip install "runvault[langchain-openai]"     # LangChain ChatOpenAI
pip install "runvault[langchain-anthropic]"  # LangChain ChatAnthropic
pip install "runvault[langchain-google]"     # LangChain ChatGoogleGenerativeAI
pip install "runvault[langgraph]"            # LangGraph runtime
pip install "runvault[crewai]"               # CrewAI BaseLLM subclass
pip install "runvault[openai]"               # bare openai SDK
pip install "runvault[anthropic]"            # bare anthropic SDK
pip install "runvault[all]"                  # everything above
```

Multiple extras can be combined in one install:

```bash
pip install "runvault[langgraph,langchain-openai]"
```

## Verify the install

```bash
python -c "from runvault import RunVault; print(RunVault)"
```

Expected output:

```
<class 'runvault.client.RunVault'>
```

## Environment variables

The SDK does not auto-read environment variables. You pass values to `RunVault(...)` explicitly. The conventional names below are what most deployments use:

| Variable | Required | Purpose |
|---|---|---|
| `RUNVAULT_API_KEY` | recommended | Your project API key (`rv_live_…`). Pass to `RunVault(api_key=…)`. |
| `RUNVAULT_BE_URL`  | recommended | Backend base URL. Pass to `RunVault(be_url=…)`. |
| `RV_CA_PUBLIC_KEY` | recommended in production | Base64-encoded Ed25519 RunVault CA public key. When set, the SDK verifies every certificate's CA signature. Absent ⇒ the SDK logs a warning and proceeds. |

```python
import os
from runvault import RunVault

rv = RunVault(
    api_key=os.environ["RUNVAULT_API_KEY"],
    be_url=os.environ["RUNVAULT_BE_URL"],
)
```

## Construct a RunVault client

Construction performs no I/O — credentials are stored and an internal HTTP client is built. The first network call happens on `rv.register_agent(...)`.

```python
from runvault import RunVault

rv = RunVault(
    api_key="rv_live_...",
    be_url="https://your-runvault-backend",
    timeout=10,   # optional, seconds — applies to connect / write / pool
)
```

The *read* timeout is intentionally unbounded so legitimate slow responses are never classified as a timeout.

## Next

Continue to the [Quickstart](quickstart.md) to register an agent and route your first LLM call through the proxy.
