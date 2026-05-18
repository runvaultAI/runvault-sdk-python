# Budgets and Alerts

RunVault enforces budgets at the **proxy**. The SDK only carries the agent's identity; the proxy is what blocks an overspending agent before its request reaches the upstream provider. This means:

- A leaked SDK install cannot exceed the budget set in the dashboard.
- Two SDK instances of the same agent share the same cap.
- The cap is updated in real time when an administrator changes it in the dashboard.

## Setting a budget

```python
identity = rv.register_agent(
    agent_id="research-v1",
    name="Research Agent",
    budget=1.0,                  # hard cap in USD
    budget_alert_threshold=80,   # alert at 80% spent
)
```

Both fields are honoured **only on first registration**. After that the dashboard is authoritative — if an administrator has set a different cap, the SDK's value is ignored and the SDK logs a warning when it disagrees with the backend.

## What happens when the cap is reached

The proxy returns a `BUDGET_CAP_REACHED` error and the SDK raises `BudgetExceededError`:

```python
from runvault import BudgetExceededError

try:
    with identity.run():
        llm.invoke("...")
except BudgetExceededError as e:
    log.warning("budget exhausted: %s", e.user_string)
```

The exception carries:

- `status_code` — usually `402`.
- `error_code` — `"BUDGET_CAP_REACHED"`.
- `user_string` — a UI-friendly message.

## Alerts

Alerts are dashboard-driven. `budget_alert_threshold=80` configures the agent to alert once it has spent 80% of its cap. Delivery (webhook, email, …) is configured in the dashboard, not in the SDK.

## Inspecting remaining budget

Budget queries are not part of the SDK's public API today. If you need spend-aware behaviour, drive it from the dashboard or from your own metrics — do not depend on the SDK to surface live balances.
