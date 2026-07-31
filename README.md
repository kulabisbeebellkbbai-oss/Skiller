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
- `scan_memory_records`: scan AI memory records for skill-relevant guidance, link matching learnings, or create memory-derived learnings.
- `memory_scan_due`: decide whether a periodic AI-memory association run is due.
- `get_learning_memory_context`: resolve a learning's `memory_record_ids` back to available AI-memory summaries.
- `record_overseer_guidance`: store Overseer guidance for future scanner expansion with security review metadata.
- `apply_overseer_guidance`: apply only security-reviewed bounded scanner configuration changes.
- `review_skill_effectiveness`: measure attributed guidance outcomes, recurring pitfalls, and recommend a bounded review cadence.
- `record_skill_run`: append reliability evidence for a skill invocation.
- `recommend_skills`: rank captured or indexed skills for a task.
- `record_guidance_recommendation`: persist what Skiller recommended for a thread or decision point.
- `get_thread_guidance_context`: return the recommendation event plus linked learnings, memory context, guardrails, and known failure paths.
- `evaluate_guidance_adherence`: classify a thread action as `followed`, `ignored`, `violated`, or `unknown` against Skiller guidance.
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

The installer also enables record-driven lineage maintenance through a systemd
path unit and retains a periodic timer as a quiet-period fallback. The adaptive
review records its decisions in `data/effectiveness_reviews.jsonl`. Supply
`guidance_learning_ids` and `pitfalls_avoided` when recording a skill run so
guidance effectiveness can be attributed rather than inferred.

The installer also enables `skiller-memory-scan.service`, `skiller-memory-scan.timer`,
and `skiller-memory-scan.path`. This maintenance path scans safe AI-memory
registry summaries, links matching memories to `memory_record_ids` on learnings,
and can create memory-derived learning records for cataloged skills. Private
memory search is disabled by default and can only be enabled through an applied
configuration change or explicit CLI flag.

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

Run a reviewable AI-memory association scan:

```bash
.venv/bin/skiller scan-memory --data-dir data --force
```

Apply inferred memory links and memory-derived learnings:

```bash
.venv/bin/skiller scan-memory --data-dir data --apply --force
```

Overseer expansion guidance is stored separately from code changes. Only records
with `security_review_status=passed` can change bounded scanner configuration
such as query terms, scan thresholds, scan limits, or private-search enablement.

## Guidance Audit

Skiller owns the evidence package for guidance compliance. Use
`record_guidance_recommendation` at a decision point to store the ranked skills,
linked learnings, memory references, guardrails, and known failure paths that
applied to a thread. Later, call `evaluate_guidance_adherence` with the thread
action summary, used skills, used learning ids, checks, and outcome to produce a
structured finding. Overseer can consume the finding, but policy decisions and
enforcement remain outside Skiller.
