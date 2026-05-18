# Installation

`runvault` is a small Python package. The base install pulls in only `httpx` and `cryptography`; LLM provider and framework support are opt-in via pip extras, so your environment never grows beyond what you actually use.

## Requirements

- **Python 3.9 or newer.** Tested on 3.9 through 3.13.
- A reachable **RunVault backend** — the `be_url` you will pass to `RunVault(...)`.
- A **RunVault project API key** (`rv_live_…`) issued from your RunVault dashboard.
- *(Recommended for production)* the `RV_CA_PUBLIC_KEY` environment variable, set to your deployment's RunVault CA public key.

## Install the SDK

For the base SDK only:

```bash
pip install runvault
```

LLM provider support is opt-in. Install the extras that match your stack:

```bash
pip install runvault[openai]               # OpenAI raw client
pip install runvault[anthropic]            # Anthropic raw client
pip install runvault[google]               # Google generative AI
pip install runvault[langchain-openai]     # LangChain OpenAI wrapper
pip install runvault[langchain-anthropic]  # LangChain Anthropic wrapper
pip install runvault[langchain-google]     # LangChain Google wrapper
pip install runvault[langgraph]            # LangGraph framework adapter
pip install runvault[all]                  # everything above
```

Multiple extras can be combined in a single install:

```bash
pip install runvault[langgraph,langchain-openai]
```

## Verifying the install

A successful install should let you import the SDK and read its public surface:

```bash
python -c "from runvault import RunVault; print(RunVault)"
```

Expected output:

```
<class 'runvault.client.RunVault'>
```

If you installed the `langchain-openai` extra, the drop-in `ChatOpenAI` factory should also be importable:

```bash
python -c "from runvault import ChatOpenAI; print(ChatOpenAI)"
```

## Recommended environment variables

The SDK does **not** auto-read environment variables on your behalf. You decide how the values reach your code. The conventional names below are what most deployments use:

| Variable | Required | Purpose |
|---|---|---|
| `RUNVAULT_API_KEY` | Recommended | Your project API key (`rv_live_…`). Pass to `RunVault(api_key=…)`. |
| `RUNVAULT_BE_URL` | Recommended | Backend base URL. Pass to `RunVault(be_url=…)`. |
| `RV_CA_PUBLIC_KEY` | Recommended in production | Base64-encoded Ed25519 RunVault CA public key. When set, the SDK verifies the CA signature on every certificate it receives. When absent, the SDK logs a warning and proceeds — acceptable for local development, never for production. |

A typical bootstrap script reads them at process start:

```python
import os

from runvault import RunVault

rv = RunVault(
    api_key=os.environ["RUNVAULT_API_KEY"],
    be_url=os.environ["RUNVAULT_BE_URL"],
)
```

## Constructing a RunVault client

Construction does no I/O — it stores credentials and builds an internal HTTP client. Network calls happen on the first `rv.init(...)`.

```python
from runvault import RunVault

rv = RunVault(
    api_key="rv_live_...",
    be_url="https://your-runvault-backend",
    timeout=10,  # optional, seconds
)
```

`timeout` controls the connect, write, and pool timeouts for backend calls. The read timeout is intentionally unbounded, since a small number of backend operations can legitimately take many seconds.

## Next

Installation is the easy part. The next step is registering an agent and routing your first LLM call through the RunVault proxy. Continue to the [Quickstart](quickstart.md).
