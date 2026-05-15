# Pluma cross-tool report

Generated: 2026-05-15T04:37:12+00:00

Tools run:
  - funnel-researcher
  - integration-watcher

## Correlation matrix

| Tool | Layer 1 | Layer 2 | Layer 3 | Total |
|---|---|---|---|---|
| funnel-researcher | 0 | 1 | 2 | 3 |
| integration-watcher | 1 | 1 | 1 | 3 |

## Cross-tool findings (4)

### Cross-match 1 — Mechanical match

**Reason:** both cite `docs/quickstart.md:23-30`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H1: Quickstart shows `agents.run()` before establishing that `agent_id` must be created first, causing developers to copy-paste the placeholder string and 400 [Layer 3]**

**Claim:** The quickstart guide moves directly from authentication to a runnable `client.agents.run(...)` block with `agent_id="agt_xxxxxxxx"`. The string `agt_xxxxxxxx` visually mirrors `sk_pluma_...` from two code blocks earlier, which the developer just received from signup. The developer reasonably assumes `agent_id` is something the SDK or platform provides automatically (or that the placeholder is decorative like the API key truncation) and submits the request. The server returns `MISSING_AGENT_ID` (when the literal placeholder is stripped or rejected as malformed) or `INVALID_AGENT_SCOPE` (when an agent ID from a tutorial / another org is pasted in). The link to actually create an agent is in "What's next" *after* the run example — too late for a developer who's already hit an error and is now searching the error catalog.

**Evidence:**
- `docs/quickstart.md:23-30`: the `agents.run(agent_id="agt_xxxxxxxx", ...)` block appears with no preceding statement that the developer must first create an agent. The block ends with "That's it." on line 32.
- `docs/quickstart.md:36`: agent configuration is listed under "What's next" — *after* the example, framed as optional follow-up.
- `docs/quickstart.md:15-19` vs. `docs/quickstart.md:23-27`: `sk_pluma_...` and `agt_xxxxxxxx` are presented in identical placeholder syntax two blocks apart, but the former is something the developer has, the latter is something they don't.
- `README.md:12-21`: the README has the same structure — example first, link to `docs/agents.md` at line 21 *after* the snippet — but at least mentions "create an `agent_id` before running." The quickstart drops even that hint.
- Dropoff signal: `MISSING_AGENT_ID` is 31% of dropoffs at median 4 calls (developer retries, suggesting confusion about what value to put there, not a one-shot typo). `INVALID_AGENT_SCOPE` at 18% with median 2 calls is consistent with developers pasting an `agent_id` from somewhere wrong.
- Qualitative: survey free-text clusters on "unclear what `agent_id` should be" and "docs jump to advanced examples"; support tickets mentioning `agent_id` up 4x.

**Proposed change:** Insert a required "Create an agent" step in the quickstart between authentication and the first run example. Show the two-minute dashboard path (most developers) and a one-line `agents.create(...)` alternative, and make explicit that `agt_xxxxxxxx` in the next snippet is to be replaced with the ID that step produces.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/quickstart.md",
      "action": "insert_after",
      "at_line": 19,
      "new_content": "\n## Create an agent\n\nBefore you can run anything, you need an agent configuration. Agents in Pluma are pre-configured (model + tools + system prompt) rather than ad-hoc — see [why](agents.md#why-agents-are-pre-configured).\n\nThe fastest path (about 2 minutes):\n\n1. Go to https://dashboard.pluma.dev/agents and click \"Create agent\"\n2. Name it, pick `pluma-medium`, leave tools empty, write any system prompt\n3. Copy the `agent_id` (it looks like `agt_8x3kqp2n`) from the top of the agent detail page\n\nOr, in code:\n\n```python\nagent = client.agents.create(\n    name=\"my-first-agent\",\n    model=\"pluma-medium\",\n    system_prompt=\"You are a helpful assistant.\",\n)\nprint(agent.agent_id)  # save this; you'll use it below\n```\n\nYou'll use this `agent_id` in every `agents.run(...)` call."
    },
    {
      "file": "docs/quickstart.md",
      "action": "replace",
      "from_line_start": 21,
      "from_line_end": 21,
      "expected_content": "## Run your first agent",
      "new_content": "## Run your first agent\n\nReplace `agt_xxxxxxxx` below with the `agent_id` you just created."
    }
  ]
}
```

**How to verify:** `first_api_call_to_first_successful_agent_run` should move from 0.469 toward the funnel's other within-product transitions (0.68–0.82). The `MISSING_AGENT_ID` signal should drop substantially as a fraction of dropoffs (target: from 31% to under 10%); `INVALID_AGENT_SCOPE` should also fall as developers create their own agents rather than pasting in foreign IDs. The "agent_id" support ticket volume should fall back toward the previous-launches baseline. Re-measure at 30 days post-change on a fresh cohort.

---

**integration-watcher — F3: dev_a8f3's MISSING_AGENT_ID cluster at session start is produced by README and quickstart both showing `agents.run(agent_id="agt_xxxxxxxx", ...)` as the literal first code block, with the create-agent prerequisite presented as a follow-up link rather than a precondition the developer must satisfy first [Layer 3]**

**Pattern claim:** dev_a8f3 issues 4 consecutive `POST /agents/run` calls with the literal placeholder `agent_id="agt_xxxxxxxx"` before ever calling `agents.create`. The README's quickstart code block (README.md:12–16) and the quickstart guide (docs/quickstart.md:23–30) both show `agents.run(agent_id="agt_xxxxxxxx", ...)` as the first runnable code, with the agent-creation step linked as a footnote ("See the agent configuration guide" at README.md:21; "Configure your agent" under "What's next" at docs/quickstart.md:36). The developer copies the example verbatim, runs it, gets MISSING_AGENT_ID, retries the same call shape 3 more times before going to read the docs and discovering `agents.create` is a precondition.

**Cohort prevalence:** 1 of 5 developers; 4 of 200 calls. Small in absolute volume but maximally consequential: this is *time-zero* friction, before the developer has formed any model of the product. dev_a8f3 recovers within ~6 minutes (trace:5 is the eventual create), but the per-cohort cost of "every new developer wastes their first session on this" scales with cohort size.

**Trace evidence:**
- traces:1–4: 4 consecutive `POST /agents/run` with `agent_id="agt_xxxxxxxx"` (the literal placeholder string from README.md:13), each returning 400 MISSING_AGENT_ID. Inter-call intervals 43s / 23s / 47s — the developer is reading the error, re-running, not changing the agent_id between attempts.
- trace:5: After 5+ minutes (09:17:32 → 09:23:05), `POST /agents/create` succeeds. The agent_id `agt_8r3kqx2n` returned here is what the developer uses from trace:6 onward.
- traces:6–30: 25 subsequent runs, all successful except one transient timeout (trace:20). The mechanism is purely first-session ordering.

**Product evidence:**
- README.md:12–16 shows the very first code example as `client.agents.run(agent_id="agt_xxxxxxxx", ...)`. The placeholder `agt_xxxxxxxx` is exactly the string dev_a8f3 sent (traces:1–4). The create-agent dependency is at README.md:21, *after* the runnable block.
- docs/quickstart.md:23–30 ("Run your first agent") repeats the same pattern: a copy-pasteable `agents.run(agent_id="agt_xxxxxxxx", ...)` block, with no preceding "you need an agent_id first" step. The link to agent configuration is at docs/quickstart.md:36, under "What's next" — i.e., framed as a follow-up, not a prerequisite.
- docs/agents.md:3 does state the precondition clearly ("Before you can run an agent, you need to create an agent configuration and retrieve its `agent_id`"), but this lives behind a link the developer only follows *after* failing.
- errors.md:17–18 (MISSING_AGENT_ID entry) describes the missing field but not the ordering: "Set it to a valid agent ID issued by the dashboard or `agents.create`." It does not warn that the literal `agt_xxxxxxxx` from the example is a placeholder, not a working ID.

**Proposed change:** Reorder the quickstart so the create-agent step appears as a numbered prerequisite *before* the run-agent code block. Specifically, insert a "Create an agent" section between "Authenticate" and "Run your first agent" in docs/quickstart.md, with a runnable `agents.create` call producing a real `agent_id` that the subsequent `agents.run` block references by variable rather than by a `agt_xxxxxxxx` placeholder string. (The README change is also warranted but is a one-line addition; the structured edit below covers the quickstart, which is the higher-leverage surface.)

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/quickstart.md",
      "action": "replace",
      "from_line_start": 21,
      "from_line_end": 30,
      "expected_content": "## Run your first agent\n\n```python\nrun = client.agents.run(\n    agent_id=\"agt_xxxxxxxx\",\n    input=\"What's the weather like in San Francisco?\",\n)\n\nprint(run.output)\n```",
      "new_content": "## Create an agent\n\nBefore you can run anything, you need an `agent_id`. Create one:\n\n```python\nagent = client.agents.create(\n    name=\"weather-assistant\",\n    model=\"pluma-medium\",\n    system_prompt=\"You answer weather questions concisely.\",\n    tools=[],\n)\n```\n\n`agent.agent_id` is what you'll pass to `agents.run` below. Store it in your application config — it's stable across calls. See [agent configuration](agents.md) for the full set of options.\n\n## Run your first agent\n\n```python\nrun = client.agents.run(\n    agent_id=agent.agent_id,\n    input=\"What's the weather like in San Francisco?\",\n)\n\nprint(run.output)\n```\n\nNote: `agt_xxxxxxxx` is not a real ID. You must create an agent first (above) and pass the returned `agent.agent_id`."
    }
  ]
}
```

**How to verify:** New developers' first session should contain a successful `agents.create` *before* any `agents.run` call. Specifically, the MISSING_AGENT_ID error count at session start should drop toward zero across the cohort. Failure mode for this finding: if developers still issue `agents.run` with the literal `agt_xxxxxxxx` placeholder before creating an agent, the README's first code block (README.md:12–16) is the binding surface, not the quickstart — in which case the edit needs to extend to the README as well, and this finding's claim about quickstart-as-primary-entry-point is wrong.


### Cross-match 2 — Categorical match

**Reason:** same Layer 2, shared surface `sdk/agents.py`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H2: `MISSING_AGENT_ID` and `INVALID_AGENT_SCOPE` error messages don't include the next-action URL or SDK call, so developers who hit them on their first attempt can't self-recover and quit after a few retries [Layer 2]**

**Claim:** When a developer hits `MISSING_AGENT_ID` (a 400 on their first run attempt), the error message says the field is required and "Set it to a valid agent ID issued by the dashboard or `agents.create`." That sentence names the two paths but doesn't link to them. The developer is at a terminal with a `PlumaAPIError` and has to context-switch to find the dashboard URL or the `agents.create` signature. The median of 4 calls before quitting on this error suggests developers are *trying* — they're not abandoning silently — but the error doesn't give them the click. `INVALID_AGENT_SCOPE` is worse: it explains the cause (cross-org / production-scoped key) but offers no remediation (e.g., "check the API key in your dashboard at https://dashboard.pluma.dev/keys"), and developers quit after only 2 calls.

**Evidence:**
- error catalog `:17-18`: `MISSING_AGENT_ID` message names "dashboard" and `agents.create` but provides no URL or SDK code snippet.
- error catalog `:20-21`: `INVALID_AGENT_SCOPE` describes two possible causes but no remediation steps.
- `sdk/agents.py:96-103`: `PlumaAPIError` exposes `code`, `message`, `request_id` only. No `help_url`, no `recovery_hint` field — so even if the API server wanted to attach a remediation link to the response, the SDK wouldn't surface it as a structured field; it would be jammed into `message`.
- Dropoff signal: `MISSING_AGENT_ID` median-calls-before-quit = 4 (engaged retries, not a typo); `INVALID_AGENT_SCOPE` median-calls-before-quit = 2 (the developer can't figure out what to do, gives up faster).
- Qualitative: support tickets mentioning `agent_id` 4x prior baseline — consistent with developers escalating because the error didn't self-resolve.

**Proposed change:** Rewrite the `MISSING_AGENT_ID` and `INVALID_AGENT_SCOPE` entries in the error catalog to include concrete next-action URLs and (for the missing case) the exact `agents.create` call. The error API server change to include a `help_url` field is out of scope here; this hypothesis is scoped to the catalog page developers land on when they Google the code.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "errors.md",
      "action": "replace",
      "from_line_start": 17,
      "from_line_end": 18,
      "expected_content": "### MISSING_AGENT_ID\n**HTTP 400.** The `agent_id` field is required for `client.agents.run()` and was not provided. Set it to a valid agent ID issued by the dashboard or `agents.create`.",
      "new_content": "### MISSING_AGENT_ID\n**HTTP 400.** The `agent_id` field is required for `client.agents.run()` and was not provided, or the placeholder value `agt_xxxxxxxx` was sent literally.\n\n**To fix:** Create an agent first. Either:\n\n- **Dashboard (2 minutes):** Go to https://dashboard.pluma.dev/agents → \"Create agent\" → copy the `agent_id` from the agent detail page.\n- **In code:**\n  ```python\n  agent = client.agents.create(\n      name=\"my-agent\",\n      model=\"pluma-medium\",\n      system_prompt=\"You are a helpful assistant.\",\n  )\n  print(agent.agent_id)\n  ```\n\nThen pass that `agent_id` to `client.agents.run(agent_id=..., input=...)`. See the [agent configuration guide](agents.md) for details."
    },
    {
      "file": "errors.md",
      "action": "replace",
      "from_line_start": 20,
      "from_line_end": 21,
      "expected_content": "### INVALID_AGENT_SCOPE\n**HTTP 401.** The agent referenced by `agent_id` exists but is not accessible with the current API key. This usually means the agent was created under a different organization or is scoped to a production-only key.",
      "new_content": "### INVALID_AGENT_SCOPE\n**HTTP 401.** The agent referenced by `agent_id` exists but is not accessible with the current API key.\n\n**Common causes and fixes:**\n\n- **You pasted an `agent_id` from a tutorial, blog post, or another organization.** Agent IDs are not shared across organizations. Create your own at https://dashboard.pluma.dev/agents.\n- **Your API key is scoped to a different environment than the agent.** Check your key's scopes at https://dashboard.pluma.dev/keys, and verify the agent's scope at https://dashboard.pluma.dev/agents/<agent_id>.\n- **The agent was revoked.** Revoked agents return this error on any run. Create a new agent or restore from the dashboard."
    }
  ]
}
```

**How to verify:** Among developers who hit `MISSING_AGENT_ID`, the median calls before quit should *rise* (they keep trying because the next action is clear) and the fraction reaching `first_successful_agent_run` afterward should rise. The `MISSING_AGENT_ID` and `INVALID_AGENT_SCOPE` shares of dropoffs at this step should each fall (target: combined from 49% to under 25%). Support ticket volume mentioning `agent_id` should approach the prior-launches baseline.

---

**integration-watcher — F2: The one developer who matches the "stall after 5 runs" shape (dev_b2k7) is dead-ended by INVALID_TOOL_PARAMS with no error-catalog entry under that name and no schema cue in the SDK signature [Layer 2]**

**Pattern claim:** dev_b2k7 successfully runs the agent 5 times on generic "research stage" inputs, then switches to a tool-calling input ("run python_exec on dataset") and hits INVALID_TOOL_PARAMS 8 times in a row, polls run events 3 times, retries with a renamed input ("dataset_v2") 4 more times, then goes silent. The `errors.md` catalog has no entry for `INVALID_TOOL_PARAMS` — only `TOOL_PARAM_MISSING` (errors.md:29–30) and `TOOL_NOT_FOUND` (errors.md:26–27). The developer is receiving an error code whose name does not appear in the catalog they would search, and the SDK's `run()` signature (sdk/agents.py:28–34) accepts only `input: str` — it does not expose the structured tool parameter the API is actually rejecting, so there's no parameter at the call site the developer can edit. They retry the same call shape because the surface gives them nothing else to vary.

**Cohort prevalence:** 1 of 5 developers; 12 of 200 calls (the entire INVALID_TOOL_PARAMS error volume in the cohort).

**Trace evidence:**
- dev_b2k7 transitions from successful generic runs to tool-targeted inputs at trace:37. The first 8 retries (traces:37–44) use identical input "run python_exec on dataset" with identical latency profile (~70–100ms, indicating server-side rejection before model call).
- After 8 failures, dev_b2k7 polls `GET /agents/run/run_b2k7_07/events` 3 times (traces:45–47) — presumably looking for diagnostic detail not in the 400 response body.
- dev_b2k7 then retries with a renamed input "run python_exec on dataset_v2" (traces:48–51), failing 4 more times. The variation is in the prose of `input`, which the SDK signature treats as a free-form string. The developer has no other lever.
- Session ends at trace:51 with no `agents.create` reissue, no other endpoint, no recovery.

**Product evidence:**
- `errors.md:15–47` lists every 4xx/5xx code: MISSING_AGENT_ID, INVALID_AGENT_SCOPE, MODEL_UNAVAILABLE, TOOL_NOT_FOUND, TOOL_PARAM_MISSING, ATTACHMENT_TOO_LARGE, RATE_LIMIT_EXCEEDED, INTERNAL, MODEL_TIMEOUT, TOOL_TIMEOUT. `INVALID_TOOL_PARAMS` is not in the catalog. The closest neighbor, `TOOL_PARAM_MISSING` at errors.md:29–30, says "The model may have failed to fill it in; consider updating the agent's system prompt or the tool's required-parameter description" — a fix that points at agent configuration, not at the SDK call shape.
- `sdk/agents.py:28–34` (the `run()` signature) accepts `agent_id`, `input`, `attachments`, `stream`. There is no parameter for tool inputs, tool selection, or structured tool arguments. The developer attempting to invoke `python_exec` has no SDK-level handle on the failure point.
- `docs/agents.md:47–49` ("Tool configuration") is two sentences: "Agents can call tools. Pass tool names in the `tools` array when creating an agent — see the [agent creation example](#via-the-api) above." It does not describe how tool parameters are supplied at run time, nor what `INVALID_TOOL_PARAMS` indicates.

**Proposed change:** Add an `INVALID_TOOL_PARAMS` entry to `errors.md` immediately after the existing `TOOL_PARAM_MISSING` entry. The entry must (a) name what's actually being validated (the tool-call arguments the model produced or the developer supplied), (b) state explicitly that the cause is usually that the `input` string doesn't give the model enough information to fill required tool parameters or that the agent's tool schema requires fields the model isn't producing, and (c) point to the agent's tool configuration in the dashboard as the diagnostic surface, since the SDK `run()` call has no parameter to edit.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "errors.md",
      "action": "insert_after",
      "at_line": 30,
      "new_content": "\n### INVALID_TOOL_PARAMS\n**HTTP 400.** The agent attempted to call a tool, but the arguments produced for that tool did not satisfy the tool's parameter schema. Unlike `TOOL_PARAM_MISSING` (which fires when a required parameter is absent), `INVALID_TOOL_PARAMS` fires when one or more arguments are present but malformed (wrong type, fails enum/range validation, or references an unknown field). Retrying the same `input` string will not change the outcome — the SDK's `agents.run(input=...)` call does not accept tool arguments directly. Fix it at one of: (1) the agent's tool schema (dashboard → agent → tools), (2) the agent's system prompt (instruct the model on exact argument shape), or (3) the `input` string (give the model the literal values it needs to construct valid arguments). The 400 response body includes a `details` field naming which tool and which parameter failed validation."
    }
  ]
}
```

**How to verify:** After this edit, dev_b2k7-shape developers should either (a) recover within 1–2 retries because they edit the agent's tool schema or system prompt rather than the `input` string, or (b) go silent earlier (after 1–2 retries instead of 8+12), because the catalog tells them retrying the same call shape won't help. The failure mode for this finding: if developers still produce ≥4 consecutive identical INVALID_TOOL_PARAMS calls after the edit, then the SDK signature gap (no tool-arg parameter on `run()`) is the dominant cause and the docs edit is insufficient — that would be a Layer 2 SDK-redesign finding, not a docs finding.

---


### Cross-match 3 — Mechanical match

**Reason:** both cite `sdk/agents.py:28-65`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H3: `run.start` events without `run.complete` within 5 minutes (24% of dropoffs) indicate developers don't know runs are asynchronous / streamable — they expect `agents.run()` to return synchronously and abandon the script before the run finishes [Layer 3]**

**Claim:** The SDK's `agents.run(...)` looks synchronous: it returns an `AgentRun` with `output` and `status` directly. The quickstart's "That's it." after `print(run.output)` reinforces that mental model. But 24% of dropoffs come from developers whose `run.start` succeeded with no `run.complete` within 5 minutes — meaning the server accepted the run but the developer never saw `run.complete`. Combined with the docstring note that `stream=True` "returns a streaming iterator instead of a final AgentRun" (`sdk/agents.py:41`), the natural read is that the non-streaming call blocks until completion. The most likely real mechanism: the call is long-running (multi-minute model + tool work) and either (a) developers are timing out their HTTP client and never receive the response, (b) the call is in fact asynchronous and `output` is empty/partial on return, or (c) the developer kills the process after seeing no output and a slow terminal. None of this is documented. There is no "What to expect" section explaining run duration, no troubleshooting entry for "my run started but I never saw it complete," and no mention of timeouts. The single line under "Troubleshooting" (`docs/quickstart.md:39-41`) just redirects to the error reference, which has no entry for this case.

**Evidence:**
- `sdk/agents.py:28-65`: `agents.run()` signature and implementation are synchronous-looking; the docstring doesn't mention expected duration or that the server holds the connection open.
- `sdk/agents.py:41`: `stream` parameter is mentioned, but the contrast ("instead of a final AgentRun") implies the non-stream path returns when the run is final — without saying how long that takes.
- `docs/quickstart.md:32`: "That's it." — sets the expectation that the run completes promptly within the snippet.
- `docs/quickstart.md:39-41`: troubleshooting section only redirects to errors.md, which has no entry for "run started but never completed."
- error catalog `:43-44`: `MODEL_TIMEOUT` is documented as HTTP 504 server-side, but the catalog says nothing about client-side timeouts (where most "no `run.complete` within 5 minutes" cases will originate).
- Dropoff signal: 24% of failures at this step are `run.start` without `run.complete` within 5 minutes, median 1 call (developer tries once, sees nothing, leaves). 13% additionally show `first_api_call` success then no run attempted within 24h — consistent with "I called something, didn't see output, gave up."

**Proposed change:** Add a "What to expect when a run is in progress" section to the quickstart that names the typical duration range, recommends `stream=True` for any first-time run so the developer sees events as they happen, and shows what the events look like. Add an `errors.md` troubleshooting entry for "run.start with no run.complete" with the most likely client-side cause (default HTTP timeout) and the fix.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/quickstart.md",
      "action": "insert_after",
      "at_line": 30,
      "new_content": "\n### How long does a run take?\n\nAgent runs typically take 10–90 seconds depending on the model, the input, and how many tool calls the agent makes. The `client.agents.run(...)` call holds the HTTP connection open for the duration of the run.\n\nIf your HTTP client has a short default timeout (e.g., `requests` defaults to no timeout but proxies and serverless platforms may impose 30s), use the streaming form so you see progress events as they happen:\n\n```python\nfor event in client.agents.run(\n    agent_id=\"agt_xxxxxxxx\",\n    input=\"What's the weather like in San Francisco?\",\n    stream=True,\n):\n    print(event.type, event.data)\n```\n\nYou'll see `run.start`, `tool_call`, `tool_result`, and finally `run.complete`. If you see `run.start` but the script exits before `run.complete`, your client timed out — switch to streaming or extend your client's timeout."
    },
    {
      "file": "errors.md",
      "action": "insert_after",
      "at_line": 46,
      "new_content": "\n## Run started but never completed\n\nNot strictly an error code, but a common failure mode: you call `client.agents.run(...)`, the run is accepted (`run.start` fires server-side), but your script exits or hangs without receiving `run.complete`.\n\n**Most common cause:** your HTTP client or runtime (serverless function, proxy, notebook kernel) timed out before the run finished. Pluma runs are typically 10–90 seconds; some are longer.\n\n**Fix:** Use `stream=True` so events flush as they arrive, and increase your client's timeout to at least 180 seconds. See the [quickstart](quickstart.md#how-long-does-a-run-take) for the streaming pattern."
    }
  ]
}
```

**How to verify:** The "`run.start` succeeds but no `run.complete` within 5 minutes" signal should fall as a share of dropoffs (target: from 24% to under 10%). The "first_api_call succeeded but no agent run attempted within 24h" signal (13%) should also fall, because developers who streamed and saw `run.start` / `tool_call` / `run.complete` events on their first try will have more confidence to attempt a second run. `first_successful_agent_run_to_ten_runs` (currently 0.69) should be unchanged or slightly higher, since this change converts started-but-incomplete attempts into observed completes.

**integration-watcher — F2: The one developer who matches the "stall after 5 runs" shape (dev_b2k7) is dead-ended by INVALID_TOOL_PARAMS with no error-catalog entry under that name and no schema cue in the SDK signature [Layer 2]**

**Pattern claim:** dev_b2k7 successfully runs the agent 5 times on generic "research stage" inputs, then switches to a tool-calling input ("run python_exec on dataset") and hits INVALID_TOOL_PARAMS 8 times in a row, polls run events 3 times, retries with a renamed input ("dataset_v2") 4 more times, then goes silent. The `errors.md` catalog has no entry for `INVALID_TOOL_PARAMS` — only `TOOL_PARAM_MISSING` (errors.md:29–30) and `TOOL_NOT_FOUND` (errors.md:26–27). The developer is receiving an error code whose name does not appear in the catalog they would search, and the SDK's `run()` signature (sdk/agents.py:28–34) accepts only `input: str` — it does not expose the structured tool parameter the API is actually rejecting, so there's no parameter at the call site the developer can edit. They retry the same call shape because the surface gives them nothing else to vary.

**Cohort prevalence:** 1 of 5 developers; 12 of 200 calls (the entire INVALID_TOOL_PARAMS error volume in the cohort).

**Trace evidence:**
- dev_b2k7 transitions from successful generic runs to tool-targeted inputs at trace:37. The first 8 retries (traces:37–44) use identical input "run python_exec on dataset" with identical latency profile (~70–100ms, indicating server-side rejection before model call).
- After 8 failures, dev_b2k7 polls `GET /agents/run/run_b2k7_07/events` 3 times (traces:45–47) — presumably looking for diagnostic detail not in the 400 response body.
- dev_b2k7 then retries with a renamed input "run python_exec on dataset_v2" (traces:48–51), failing 4 more times. The variation is in the prose of `input`, which the SDK signature treats as a free-form string. The developer has no other lever.
- Session ends at trace:51 with no `agents.create` reissue, no other endpoint, no recovery.

**Product evidence:**
- `errors.md:15–47` lists every 4xx/5xx code: MISSING_AGENT_ID, INVALID_AGENT_SCOPE, MODEL_UNAVAILABLE, TOOL_NOT_FOUND, TOOL_PARAM_MISSING, ATTACHMENT_TOO_LARGE, RATE_LIMIT_EXCEEDED, INTERNAL, MODEL_TIMEOUT, TOOL_TIMEOUT. `INVALID_TOOL_PARAMS` is not in the catalog. The closest neighbor, `TOOL_PARAM_MISSING` at errors.md:29–30, says "The model may have failed to fill it in; consider updating the agent's system prompt or the tool's required-parameter description" — a fix that points at agent configuration, not at the SDK call shape.
- `sdk/agents.py:28–34` (the `run()` signature) accepts `agent_id`, `input`, `attachments`, `stream`. There is no parameter for tool inputs, tool selection, or structured tool arguments. The developer attempting to invoke `python_exec` has no SDK-level handle on the failure point.
- `docs/agents.md:47–49` ("Tool configuration") is two sentences: "Agents can call tools. Pass tool names in the `tools` array when creating an agent — see the [agent creation example](#via-the-api) above." It does not describe how tool parameters are supplied at run time, nor what `INVALID_TOOL_PARAMS` indicates.

**Proposed change:** Add an `INVALID_TOOL_PARAMS` entry to `errors.md` immediately after the existing `TOOL_PARAM_MISSING` entry. The entry must (a) name what's actually being validated (the tool-call arguments the model produced or the developer supplied), (b) state explicitly that the cause is usually that the `input` string doesn't give the model enough information to fill required tool parameters or that the agent's tool schema requires fields the model isn't producing, and (c) point to the agent's tool configuration in the dashboard as the diagnostic surface, since the SDK `run()` call has no parameter to edit.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "errors.md",
      "action": "insert_after",
      "at_line": 30,
      "new_content": "\n### INVALID_TOOL_PARAMS\n**HTTP 400.** The agent attempted to call a tool, but the arguments produced for that tool did not satisfy the tool's parameter schema. Unlike `TOOL_PARAM_MISSING` (which fires when a required parameter is absent), `INVALID_TOOL_PARAMS` fires when one or more arguments are present but malformed (wrong type, fails enum/range validation, or references an unknown field). Retrying the same `input` string will not change the outcome — the SDK's `agents.run(input=...)` call does not accept tool arguments directly. Fix it at one of: (1) the agent's tool schema (dashboard → agent → tools), (2) the agent's system prompt (instruct the model on exact argument shape), or (3) the `input` string (give the model the literal values it needs to construct valid arguments). The 400 response body includes a `details` field naming which tool and which parameter failed validation."
    }
  ]
}
```

**How to verify:** After this edit, dev_b2k7-shape developers should either (a) recover within 1–2 retries because they edit the agent's tool schema or system prompt rather than the `input` string, or (b) go silent earlier (after 1–2 retries instead of 8+12), because the catalog tells them retrying the same call shape won't help. The failure mode for this finding: if developers still produce ≥4 consecutive identical INVALID_TOOL_PARAMS calls after the edit, then the SDK signature gap (no tool-arg parameter on `run()`) is the dominant cause and the docs edit is insufficient — that would be a Layer 2 SDK-redesign finding, not a docs finding.

---


### Cross-match 4 — Categorical match

**Reason:** same Layer 3, shared surface `docs/quickstart.md`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H3: `run.start` events without `run.complete` within 5 minutes (24% of dropoffs) indicate developers don't know runs are asynchronous / streamable — they expect `agents.run()` to return synchronously and abandon the script before the run finishes [Layer 3]**

**Claim:** The SDK's `agents.run(...)` looks synchronous: it returns an `AgentRun` with `output` and `status` directly. The quickstart's "That's it." after `print(run.output)` reinforces that mental model. But 24% of dropoffs come from developers whose `run.start` succeeded with no `run.complete` within 5 minutes — meaning the server accepted the run but the developer never saw `run.complete`. Combined with the docstring note that `stream=True` "returns a streaming iterator instead of a final AgentRun" (`sdk/agents.py:41`), the natural read is that the non-streaming call blocks until completion. The most likely real mechanism: the call is long-running (multi-minute model + tool work) and either (a) developers are timing out their HTTP client and never receive the response, (b) the call is in fact asynchronous and `output` is empty/partial on return, or (c) the developer kills the process after seeing no output and a slow terminal. None of this is documented. There is no "What to expect" section explaining run duration, no troubleshooting entry for "my run started but I never saw it complete," and no mention of timeouts. The single line under "Troubleshooting" (`docs/quickstart.md:39-41`) just redirects to the error reference, which has no entry for this case.

**Evidence:**
- `sdk/agents.py:28-65`: `agents.run()` signature and implementation are synchronous-looking; the docstring doesn't mention expected duration or that the server holds the connection open.
- `sdk/agents.py:41`: `stream` parameter is mentioned, but the contrast ("instead of a final AgentRun") implies the non-stream path returns when the run is final — without saying how long that takes.
- `docs/quickstart.md:32`: "That's it." — sets the expectation that the run completes promptly within the snippet.
- `docs/quickstart.md:39-41`: troubleshooting section only redirects to errors.md, which has no entry for "run started but never completed."
- error catalog `:43-44`: `MODEL_TIMEOUT` is documented as HTTP 504 server-side, but the catalog says nothing about client-side timeouts (where most "no `run.complete` within 5 minutes" cases will originate).
- Dropoff signal: 24% of failures at this step are `run.start` without `run.complete` within 5 minutes, median 1 call (developer tries once, sees nothing, leaves). 13% additionally show `first_api_call` success then no run attempted within 24h — consistent with "I called something, didn't see output, gave up."

**Proposed change:** Add a "What to expect when a run is in progress" section to the quickstart that names the typical duration range, recommends `stream=True` for any first-time run so the developer sees events as they happen, and shows what the events look like. Add an `errors.md` troubleshooting entry for "run.start with no run.complete" with the most likely client-side cause (default HTTP timeout) and the fix.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/quickstart.md",
      "action": "insert_after",
      "at_line": 30,
      "new_content": "\n### How long does a run take?\n\nAgent runs typically take 10–90 seconds depending on the model, the input, and how many tool calls the agent makes. The `client.agents.run(...)` call holds the HTTP connection open for the duration of the run.\n\nIf your HTTP client has a short default timeout (e.g., `requests` defaults to no timeout but proxies and serverless platforms may impose 30s), use the streaming form so you see progress events as they happen:\n\n```python\nfor event in client.agents.run(\n    agent_id=\"agt_xxxxxxxx\",\n    input=\"What's the weather like in San Francisco?\",\n    stream=True,\n):\n    print(event.type, event.data)\n```\n\nYou'll see `run.start`, `tool_call`, `tool_result`, and finally `run.complete`. If you see `run.start` but the script exits before `run.complete`, your client timed out — switch to streaming or extend your client's timeout."
    },
    {
      "file": "errors.md",
      "action": "insert_after",
      "at_line": 46,
      "new_content": "\n## Run started but never completed\n\nNot strictly an error code, but a common failure mode: you call `client.agents.run(...)`, the run is accepted (`run.start` fires server-side), but your script exits or hangs without receiving `run.complete`.\n\n**Most common cause:** your HTTP client or runtime (serverless function, proxy, notebook kernel) timed out before the run finished. Pluma runs are typically 10–90 seconds; some are longer.\n\n**Fix:** Use `stream=True` so events flush as they arrive, and increase your client's timeout to at least 180 seconds. See the [quickstart](quickstart.md#how-long-does-a-run-take) for the streaming pattern."
    }
  ]
}
```

**How to verify:** The "`run.start` succeeds but no `run.complete` within 5 minutes" signal should fall as a share of dropoffs (target: from 24% to under 10%). The "first_api_call succeeded but no agent run attempted within 24h" signal (13%) should also fall, because developers who streamed and saw `run.start` / `tool_call` / `run.complete` events on their first try will have more confidence to attempt a second run. `first_successful_agent_run_to_ten_runs` (currently 0.69) should be unchanged or slightly higher, since this change converts started-but-incomplete attempts into observed completes.

**integration-watcher — F3: dev_a8f3's MISSING_AGENT_ID cluster at session start is produced by README and quickstart both showing `agents.run(agent_id="agt_xxxxxxxx", ...)` as the literal first code block, with the create-agent prerequisite presented as a follow-up link rather than a precondition the developer must satisfy first [Layer 3]**

**Pattern claim:** dev_a8f3 issues 4 consecutive `POST /agents/run` calls with the literal placeholder `agent_id="agt_xxxxxxxx"` before ever calling `agents.create`. The README's quickstart code block (README.md:12–16) and the quickstart guide (docs/quickstart.md:23–30) both show `agents.run(agent_id="agt_xxxxxxxx", ...)` as the first runnable code, with the agent-creation step linked as a footnote ("See the agent configuration guide" at README.md:21; "Configure your agent" under "What's next" at docs/quickstart.md:36). The developer copies the example verbatim, runs it, gets MISSING_AGENT_ID, retries the same call shape 3 more times before going to read the docs and discovering `agents.create` is a precondition.

**Cohort prevalence:** 1 of 5 developers; 4 of 200 calls. Small in absolute volume but maximally consequential: this is *time-zero* friction, before the developer has formed any model of the product. dev_a8f3 recovers within ~6 minutes (trace:5 is the eventual create), but the per-cohort cost of "every new developer wastes their first session on this" scales with cohort size.

**Trace evidence:**
- traces:1–4: 4 consecutive `POST /agents/run` with `agent_id="agt_xxxxxxxx"` (the literal placeholder string from README.md:13), each returning 400 MISSING_AGENT_ID. Inter-call intervals 43s / 23s / 47s — the developer is reading the error, re-running, not changing the agent_id between attempts.
- trace:5: After 5+ minutes (09:17:32 → 09:23:05), `POST /agents/create` succeeds. The agent_id `agt_8r3kqx2n` returned here is what the developer uses from trace:6 onward.
- traces:6–30: 25 subsequent runs, all successful except one transient timeout (trace:20). The mechanism is purely first-session ordering.

**Product evidence:**
- README.md:12–16 shows the very first code example as `client.agents.run(agent_id="agt_xxxxxxxx", ...)`. The placeholder `agt_xxxxxxxx` is exactly the string dev_a8f3 sent (traces:1–4). The create-agent dependency is at README.md:21, *after* the runnable block.
- docs/quickstart.md:23–30 ("Run your first agent") repeats the same pattern: a copy-pasteable `agents.run(agent_id="agt_xxxxxxxx", ...)` block, with no preceding "you need an agent_id first" step. The link to agent configuration is at docs/quickstart.md:36, under "What's next" — i.e., framed as a follow-up, not a prerequisite.
- docs/agents.md:3 does state the precondition clearly ("Before you can run an agent, you need to create an agent configuration and retrieve its `agent_id`"), but this lives behind a link the developer only follows *after* failing.
- errors.md:17–18 (MISSING_AGENT_ID entry) describes the missing field but not the ordering: "Set it to a valid agent ID issued by the dashboard or `agents.create`." It does not warn that the literal `agt_xxxxxxxx` from the example is a placeholder, not a working ID.

**Proposed change:** Reorder the quickstart so the create-agent step appears as a numbered prerequisite *before* the run-agent code block. Specifically, insert a "Create an agent" section between "Authenticate" and "Run your first agent" in docs/quickstart.md, with a runnable `agents.create` call producing a real `agent_id` that the subsequent `agents.run` block references by variable rather than by a `agt_xxxxxxxx` placeholder string. (The README change is also warranted but is a one-line addition; the structured edit below covers the quickstart, which is the higher-leverage surface.)

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/quickstart.md",
      "action": "replace",
      "from_line_start": 21,
      "from_line_end": 30,
      "expected_content": "## Run your first agent\n\n```python\nrun = client.agents.run(\n    agent_id=\"agt_xxxxxxxx\",\n    input=\"What's the weather like in San Francisco?\",\n)\n\nprint(run.output)\n```",
      "new_content": "## Create an agent\n\nBefore you can run anything, you need an `agent_id`. Create one:\n\n```python\nagent = client.agents.create(\n    name=\"weather-assistant\",\n    model=\"pluma-medium\",\n    system_prompt=\"You answer weather questions concisely.\",\n    tools=[],\n)\n```\n\n`agent.agent_id` is what you'll pass to `agents.run` below. Store it in your application config — it's stable across calls. See [agent configuration](agents.md) for the full set of options.\n\n## Run your first agent\n\n```python\nrun = client.agents.run(\n    agent_id=agent.agent_id,\n    input=\"What's the weather like in San Francisco?\",\n)\n\nprint(run.output)\n```\n\nNote: `agt_xxxxxxxx` is not a real ID. You must create an agent first (above) and pass the returned `agent.agent_id`."
    }
  ]
}
```

**How to verify:** New developers' first session should contain a successful `agents.create` *before* any `agents.run` call. Specifically, the MISSING_AGENT_ID error count at session start should drop toward zero across the cohort. Failure mode for this finding: if developers still issue `agents.run` with the literal `agt_xxxxxxxx` placeholder before creating an agent, the README's first code block (README.md:12–16) is the binding surface, not the quickstart — in which case the edit needs to extend to the README as well, and this finding's claim about quickstart-as-primary-entry-point is wrong.


## Findings unique to funnel-researcher (0)

_All of this tool's findings appear in the cross-tool section above._

## Findings unique to integration-watcher (1)

### Finding F1 — The "stall after 5 runs" pattern is an artifact of trace framing; the cohort actually contains three distinct failure shapes with three distinct mechanisms [Layer 1] _(from integration-watcher)_

**Pattern claim:** The cohort hypothesis describes "agents.create + 3–5 successful runs, then a cluster of failures or silence" as a single phenomenon. The traces show this shape literally applies to only one of the five developers (dev_b2k7). dev_a8f3 and dev_c5m1 have their error clusters *before* their first successful run, not after the 5th — they're onboarding-blockage shapes, not late-stage-stall shapes. dev_d9n4 and dev_e3p8 run cleanly past 30+ successful runs with no stall at all. Bundling these under one watch question hides the fact that three different mechanisms (no agent_id at start, wrong scope at start, tool-param dead-end mid-session) are being treated as one.

**Cohort prevalence:** 1 of 5 developers (dev_b2k7) matches the watch-question shape exactly. 2 of 5 (dev_a8f3, dev_c5m1) have error clusters but in a different position in the sequence. 2 of 5 (dev_d9n4, dev_e3p8) don't stall at all.

**Trace evidence:**
- dev_a8f3: MISSING_AGENT_ID ×4 at traces:1–4 occurs *before* `agents.create` at trace:5. After create, 25 consecutive runs succeed (traces:6–30) with only one transient MODEL_TIMEOUT at trace:20. This is a "developer hit run before configuring an agent," not a 5-run stall.
- dev_c5m1: INVALID_AGENT_SCOPE ×6 at traces:53–58 occurs in the first 90 seconds after `agents.create` at trace:52, before any successful run. After a 16-minute gap, 29 consecutive runs succeed (traces:59–87). This is a "wrong key scope at session start," not a 5-run stall.
- dev_b2k7 is the only trace stream matching the watch question: `agents.create` (trace:31), 5 successful runs (traces:32–36), then INVALID_TOOL_PARAMS ×8 (traces:37–44), 3 events polls (traces:45–47), then INVALID_TOOL_PARAMS ×4 more (traces:48–51), then silence.
- dev_d9n4 (traces:88–155) and dev_e3p8 (traces:156–200) both run 30+ successful calls with zero errors — directly contradicting the "stall at 5" framing.

**Product evidence:**
- The cohort definition (`watch_question` in this report's header, restated from the cohort spec) presupposes a single failure shape. The cohort summary's `error_code_prevalence` shows four distinct error codes with non-overlapping developer attribution (per-integration `error_breakdown`: each developer's errors are dominated by a single code), which is the structural signature of multiple mechanisms, not one.
- Layer 1 is not "fix a file:line." The product artifacts don't contain a bug here; the trace-definition layer (what was captured into the cohort, how it was framed) is what's wrong.

**Proposed change:** Split the cohort into three sub-cohorts before generating Layer 2/3/4 findings, and re-issue the watch question per sub-cohort: (a) "developers who hit agents.run before agents.create" (dev_a8f3 shape), (b) "developers who hit INVALID_AGENT_SCOPE immediately after agents.create" (dev_c5m1 shape), (c) "developers whose multi-step run hits an INVALID_TOOL_PARAMS dead-end mid-session" (dev_b2k7 shape). Drop the "stall after 5 runs" framing — it doesn't survive contact with the traces.

```json
{
  "applyable": false,
  "reason": "This is a cohort/trace-definition finding (Layer 1), not an edit to product artifacts. The fix is to revise the cohort definition and re-run the analysis on sub-cohorts, which is upstream of the file/line edit surface this tool emits against."
}
```

**How to verify:** After splitting, each sub-cohort's traces should exhibit a single dominant error code with consistent positional placement in the call sequence (start-of-session vs. mid-session). If the sub-cohorts still mix error codes and positions, the decomposition is wrong. The "stall at 5" framing should disappear from any sub-cohort's watch question; if it reappears, the original framing was load-bearing and this finding is wrong about its source.

---
