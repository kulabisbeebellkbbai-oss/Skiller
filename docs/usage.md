# Usage

Start the server:

```bash
.venv/bin/skiller serve --host 127.0.0.1 --port 8794 --data-dir data
```

For persistent local use, install the user service and hooks:

```bash
python3 scripts/install_skiller_hooks.py
```

The preflight hook uses Skiller before model work by calling `recommend_skills`, with a catalog refresh fallback when no matching skill is found. The Stop hook remains the backstop for missing final-answer evidence and repeated warning/error patterns.

Run a transport smoke test:

```bash
.venv/bin/python scripts/smoke_mcp.py
```

Seed recommendations from installed Codex skills by calling `refresh_skill_catalog` with no arguments.

The default scan roots are:

- `~/.codex/skills`
- `.codex/skills`

Skiller stores the indexed catalog in `data/skill_catalog.jsonl`, reliability events in `data/skill_runs.jsonl`, captured learnings in `data/learnings.jsonl`, explicit skill update policies in `data/skill_policies.jsonl`, and reviewable generated artifacts in `data/drafts/`.

Skiller does not install generated skills or memory drafts automatically. Review the draft paths returned by `capture_work_product`, then install them through the appropriate Codex scope workflow.

To protect a skill from automatic Skiller draft updates, call `set_skill_update_policy` with `updatable=false`. Skiller will still record learnings for that skill, but `capture_work_product` will not create skill/memory drafts and `propose_skill_update` will not return guardrails unless the call includes `user_approved_update=true`.
