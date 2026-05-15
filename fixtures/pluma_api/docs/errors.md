# Pluma error codes

This page lists every error code the Pluma API can return. Errors are returned as a JSON object:

```json
{
  "error": {
    "code": "ERROR_CODE_HERE",
    "message": "Human-readable description.",
    "request_id": "req_xxxxx"
  }
}
```

## 4xx errors

### MISSING_AGENT_ID
**HTTP 400.** The `agent_id` field is required for `client.agents.run()` and was not provided. Set it to a valid agent ID issued by the dashboard or `agents.create`.

### INVALID_AGENT_SCOPE
**HTTP 401.** The agent referenced by `agent_id` exists but is not accessible with the current API key. This usually means the agent was created under a different organization or is scoped to a production-only key.

### MODEL_UNAVAILABLE
**HTTP 400.** The model specified in the agent configuration is no longer available. Update the agent to use a supported model.

### TOOL_NOT_FOUND
**HTTP 400.** A tool referenced by the agent's toolset is not registered. Check the agent's tool configuration.

### TOOL_PARAM_MISSING
**HTTP 400.** A required parameter for a tool call was missing. The model may have failed to fill it in; consider updating the agent's system prompt or the tool's required-parameter description.

### ATTACHMENT_TOO_LARGE
**HTTP 413.** Attachment exceeds 50MB. Split the input or use the bulk upload endpoint.

### RATE_LIMIT_EXCEEDED
**HTTP 429.** Too many requests. Standard exponential backoff applies.

## 5xx errors

### INTERNAL
**HTTP 500.** Pluma internal error. Retry with backoff; if persistent, contact support with the `request_id`.

### MODEL_TIMEOUT
**HTTP 504.** The model exceeded the maximum run duration. Consider simplifying the input or breaking it into smaller runs.

### TOOL_TIMEOUT
**HTTP 504.** A tool the agent called timed out. Check the tool's external dependency.
