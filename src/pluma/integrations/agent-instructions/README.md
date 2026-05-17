## Pluma diagnostic tools — agent instructions

This directory contains markdown files that describe Pluma's four diagnostic
tools (agent-researcher, funnel-researcher, integration-watcher, pluma-cross)
in a format suitable for any coding agent that reads project-level
instructions. Each file describes one tool, when to invoke it, and how. The
agent reads these as persistent context and decides when invocation is
warranted; the agent's own shell runs the installed tool CLI.

For Claude Code users: a parallel skill-based packaging lives at
<https://github.com/ivaylogb/agent-skill-kit>. The skill format gives Claude
Code auto-invocation; this generic format works across agents that don't have
a skill runtime. The content is the same; only the wrapper differs.

## What's here

- `AGENT_RESEARCHER.md` — diagnose failing agent evals
- `FUNNEL_RESEARCHER.md` — diagnose developer-API funnel dropoff
- `INTEGRATION_WATCHER.md` — find patterns in trace cohorts
- `PLUMA_CROSS.md` — correlate findings across tools
- `AGENTS.md.template` — drop-in `AGENTS.md` for OpenAI Codex CLI (also the
  composition source for any agent that wants the four tools in one file)

## Installation

Find your agent below. The files are co-equal — Codex CLI happens to have the
easiest install path via the template, but the same content reaches every
agent.

### Aider

Aider loads files passed with `--read` or listed under `read:` in
`.aider.conf.yml`; `CONVENTIONS.md` at the project root is the documented
convention name. Paste the contents of `AGENT_RESEARCHER.md` (and the other
three) into your project's `CONVENTIONS.md`, or pass them with `--read`:

    aider --read AGENT_RESEARCHER.md --read FUNNEL_RESEARCHER.md \
          --read INTEGRATION_WATCHER.md --read PLUMA_CROSS.md

### Cline (VS Code extension)

Open Cline's settings and navigate to "Custom Instructions." Paste the
contents of each `.md` file. If your Cline version supports project rules,
alternatively place the files in a `.clinerules/` directory (or a single
`.clinerules` file) at the project root.

### Continue (VS Code / JetBrains extension)

Open your Continue config (`.continue/config.json`, or `config.yaml` /
`.continue/rules/` in newer versions). Add the diagnostic-tool instructions
as a system message or rule: paste the contents of each `.md` file into the
`systemMessage` field, or load them as a rules/docs context entry.

### Cursor

Two options:

- Place the contents of each `.md` file in a project rule. Newer Cursor uses
  `.cursor/rules/*.mdc`; older Cursor reads a single `.cursorrules` file at
  the project root. Either is read as persistent context for every chat in
  the project.
- Or open Cursor Settings → Rules for AI and paste the contents there for a
  user-level (cross-project) install.

### OpenAI Codex CLI

Codex CLI auto-reads `AGENTS.md` from the project root.

If your project doesn't already have an `AGENTS.md`: copy `AGENTS.md.template`
to your project root and customize the commented-out project sections.

If your project already has an `AGENTS.md`: open `AGENTS.md.template`, copy
the "Pluma diagnostic tools" section, and paste it into your existing
`AGENTS.md` at an appropriate location (typically after your "Tools
available" or "Available commands" section).

### Roo Code (VS Code)

Roo Code uses mode-specific instructions. Open the mode you use for
debugging/diagnosis work (Code mode, Architect mode, or a custom mode) and
paste the contents of each `.md` file into that mode's custom instructions /
system prompt. If your version supports workspace rules, a `.roo/rules/`
directory (or a `.roorules` file) at the project root works as well.

## After installation

Verify your agent has picked up the instructions:

- Start a fresh agent session in your project.
- Ask: "What diagnostic tools do you have available for debugging LLM
  systems?"
- The agent should mention agent-researcher, funnel-researcher,
  integration-watcher, and pluma-cross with brief descriptions of when each
  is appropriate.

If the agent doesn't surface the tools, the instructions aren't being read.
Check your agent's documentation for the correct config file path.

## Prerequisites for invocation

Reading the instructions doesn't install the tools. To actually invoke them,
each underlying CLI must be installed separately:

    # agent-researcher    — https://github.com/ivaylogb/agent-researcher
    # funnel-researcher   — https://github.com/ivaylogb/funnel-researcher
    # integration-watcher — https://github.com/ivaylogb/integration-watcher
    # pluma               — https://github.com/ivaylogb/pluma
    pip install -e .  # run from each tool's clone
    export ANTHROPIC_API_KEY=sk-ant-...

`pluma-cross` also requires the sister tools it orchestrates
(agent-researcher, funnel-researcher, integration-watcher) to be installed.
