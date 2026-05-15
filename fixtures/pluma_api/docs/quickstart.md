# Quickstart

Welcome to Pluma. This guide walks you through making your first agent run.

## Install the SDK

```bash
pip install pluma-sdk
```

## Authenticate

Get your API key from the dashboard. Pass it to the client:

```python
from pluma import PlumaClient

client = PlumaClient(api_key="sk_pluma_...")
```

## Run your first agent

```python
run = client.agents.run(
    agent_id="agt_xxxxxxxx",
    input="What's the weather like in San Francisco?",
)

print(run.output)
```

That's it.

## What's next

- [Configure your agent](agents.md) — set name, model, toolset, and system prompt
- [Error reference](errors.md) — error codes and what they mean

## Troubleshooting

If your run isn't returning output, check the [error reference](errors.md).
