# Pluma

An agentic API platform. Run autonomous agents over your data, your tools, and your workflows.

## Quickstart

```python
from pluma import PlumaClient

client = PlumaClient(api_key="sk_pluma_...")

run = client.agents.run(
    agent_id="agt_xxxxxxxx",
    input="Summarize the Q3 earnings call transcript attached.",
    attachments=["earnings_q3.pdf"],
)

print(run.output)
```

See the [agent configuration guide](docs/agents.md) for how to create an `agent_id` before running.

## Capabilities

- Multi-tool agents with tool use
- Long-running runs with streaming events
- Attachment support (files, URLs, structured data)
- Scoped API keys for production isolation

## Pricing

Pay-per-run, with first 100 runs free per month.
