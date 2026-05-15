# Agent configuration

Before you can run an agent, you need to create an agent configuration and retrieve its `agent_id`.

## Why agents are pre-configured

Pluma agents are not ad-hoc. Each agent has:

- A name and description
- A model selection (one of pluma-large, pluma-medium, pluma-small)
- A toolset (which tools the agent can call)
- A system prompt
- Optional scoped credentials

This design choice means production agents are reproducible and auditable — you don't deploy an agent whose behavior changes between calls.

## Create an agent

### Via the dashboard

1. Navigate to https://dashboard.pluma.dev/agents
2. Click "Create agent"
3. Name your agent, pick a model, attach a toolset, write the system prompt
4. Save — your `agent_id` will appear at the top of the agent detail page

### Via the API

```python
agent = client.agents.create(
    name="weather-assistant",
    model="pluma-medium",
    system_prompt="You answer weather questions concisely.",
    tools=["weather_api"],
)

print(agent.agent_id)  # agt_8x3kqp2n
```

You'll need this `agent_id` for every subsequent `client.agents.run(...)` call.

## Managing agent IDs

- Agent IDs are stable across calls — store them in your application config.
- Don't hardcode them in deployed code; treat them like environment variables.
- A revoked agent returns a 401 with `INVALID_AGENT_SCOPE` on any run attempt.

## Tool configuration

Agents can call tools. Pass tool names in the `tools` array when creating an agent — see the [agent creation example](#via-the-api) above.
