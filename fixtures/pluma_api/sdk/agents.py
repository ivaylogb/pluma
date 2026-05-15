"""Pluma SDK Python client (excerpt: agents module).

This is the developer-facing surface for running agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentRun:
    """The result of an agents.run() call."""
    run_id: str
    agent_id: str
    output: str
    events: list[dict]
    status: str  # "complete" | "failed" | "timeout"


class AgentsAPI:
    """Client for the /agents endpoints."""

    def __init__(self, client):
        self._client = client

    def run(
        self,
        agent_id: str,
        input: str,
        attachments: Optional[list[str]] = None,
        stream: bool = False,
    ) -> AgentRun:
        """Run an agent against an input.

        Args:
            agent_id: The agent to run. Created via the dashboard or agents.create().
            input: The user message or task description.
            attachments: Optional list of file paths or URLs.
            stream: If True, returns a streaming iterator instead of a final AgentRun.

        Returns:
            AgentRun with output and event log.

        Raises:
            PlumaAPIError: For any 4xx or 5xx response. See errors.md.
        """
        payload = {
            "agent_id": agent_id,
            "input": input,
        }
        if attachments:
            payload["attachments"] = attachments
        if stream:
            return self._stream(payload)

        response = self._client._post("/v1/agents/run", payload)
        return AgentRun(
            run_id=response["run_id"],
            agent_id=response["agent_id"],
            output=response["output"],
            events=response["events"],
            status=response["status"],
        )

    def create(
        self,
        name: str,
        model: str,
        system_prompt: str,
        tools: Optional[list[str]] = None,
    ):
        """Create a new agent configuration."""
        payload = {
            "name": name,
            "model": model,
            "system_prompt": system_prompt,
            "tools": tools or [],
        }
        response = self._client._post("/v1/agents", payload)
        return Agent(
            agent_id=response["agent_id"],
            name=response["name"],
            model=response["model"],
        )


@dataclass
class Agent:
    agent_id: str
    name: str
    model: str


class PlumaAPIError(Exception):
    """Raised on any non-2xx response."""

    def __init__(self, code: str, message: str, request_id: str):
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(f"{code}: {message} (request_id={request_id})")
