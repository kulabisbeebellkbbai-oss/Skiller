# Skiller

Skiller is a loopback-only MCP server that records reusable skill learnings from agent work, drafts skill and memory artifacts, tracks reliability outcomes, and recommends relevant skills for future tasks.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

## Run

```bash
.venv/bin/skiller serve --host 127.0.0.1 --port 8794
```

MCP endpoint: `http://127.0.0.1:8794/mcp`

Health endpoint: `http://127.0.0.1:8794/health`

## Test

```bash
.venv/bin/python -m pytest
```

With the server running, validate the MCP transport:

```bash
.venv/bin/python scripts/smoke_mcp.py
```

## Tools

- `capture_work_product`: record reusable new, variant, guardrail, or failure learnings.
- `record_skill_run`: append reliability evidence for a skill invocation.
- `recommend_skills`: rank captured or indexed skills for a task.
- `propose_skill_update`: summarize failures and variants that should become guardrails.
- `list_recent_learnings`: inspect recent captured learning records.
- `get_skill_profile`: inspect a skill's catalog entry, reliability, guardrails, and drafts.
- `refresh_skill_catalog`: index existing `SKILL.md` files from Codex skill roots.
- `list_skill_catalog`: inspect indexed skills.

## Codex MCP Registration

```bash
codex mcp add skiller --url http://127.0.0.1:8794/mcp
codex mcp get skiller
```

## User-Scope Hooks

Install the Skiller route/evidence hooks and loopback user service:

```bash
python3 scripts/install_skiller_hooks.py
```

The installer copies `scripts/skiller_mcp_guard.py` into `~/.codex/hooks/`, installs the `skiller-mcp` skill into `~/.codex/skills/`, backs up and merges `~/.codex/hooks.json`, and enables `skiller-mcp.service` for the current user. After changing hooks, open Codex and run `/hooks` to review and trust the new Skiller entries.

Skiller writes only under its configured data directory. By default that is `./data` in the current working directory. Draft skills and memory notes are stored under `data/drafts/` for review before installing them into a global Codex scope.
