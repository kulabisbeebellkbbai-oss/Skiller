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
- `link_learning_correction`: connect an existing correction learning to earlier records it corrects.
- `get_learning_lineage`: inspect a learning's root, parent, child, and correction records.
- `scan_learning_lineage`: infer related learning chains across existing records and optionally link them.
- `lineage_scan_due`: decide whether a periodic scanner run is due from new-learning count or elapsed time.
- `record_skill_run`: append reliability evidence for a skill invocation.
- `recommend_skills`: rank captured or indexed skills for a task.
- `propose_skill_update`: summarize failures and variants that should become guardrails.
- `list_recent_learnings`: inspect recent captured learning records.
- `get_skill_profile`: inspect a skill's catalog entry, reliability, guardrails, and drafts.
- `refresh_skill_catalog`: index existing `SKILL.md` files from Codex skill roots.
- `list_skill_catalog`: inspect indexed skills.
- `set_skill_update_policy`: mark a skill as updatable or protected from Skiller draft updates.
- `list_skill_update_policies`: inspect explicit update policies.

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

The Skiller preflight hook calls Skiller immediately with `recommend_skills`; the Stop hook is only a backstop for missing evidence and repeated warning/error patterns.

Skiller writes only under its configured data directory. By default that is `./data` in the current working directory. Draft skills and memory notes are stored under `data/drafts/` for review before installing them into a global Codex scope. Skill update policies are stored in `data/skill_policies.jsonl`; protected skills require `user_approved_update=true` before Skiller drafts updates for them.

## Learning Lineage

When a later learning corrects an earlier failed or partial process, pass `corrects_learning_ids` and, when known, `thread_id` to `capture_work_product`. Skiller backfills the corrected record with `child_learning_ids`, `correction_learning_ids`, and `thread_ids` so future recommendations and profiles can pull the follow-on guardrails into the root workflow. Use `link_learning_correction` to repair older records that were captured before the lineage was known.

Run a reviewable lineage scan:

```bash
.venv/bin/skiller scan-lineage --data-dir data --force
```

Apply inferred links:

```bash
.venv/bin/skiller scan-lineage --data-dir data --apply --force
```

The installer can create `skiller-lineage-scan.timer`, which runs hourly and lets Skiller skip work unless enough new learnings accumulated or the time threshold has elapsed.
