# Usage

Start the server:

```bash
.venv/bin/skiller serve --host 127.0.0.1 --port 8794 --data-dir data
```

For persistent local use, install the user service and hooks:

```bash
python3 scripts/install_skiller_hooks.py
```

Run a transport smoke test:

```bash
.venv/bin/python scripts/smoke_mcp.py
```

Seed recommendations from installed Codex skills by calling `refresh_skill_catalog` with no arguments.

The default scan roots are:

- `~/.codex/skills`
- `.codex/skills`

Skiller stores the indexed catalog in `data/skill_catalog.jsonl`, reliability events in `data/skill_runs.jsonl`, captured learnings in `data/learnings.jsonl`, and reviewable generated artifacts in `data/drafts/`.

Skiller does not install generated skills or memory drafts automatically. Review the draft paths returned by `capture_work_product`, then install them through the appropriate Codex scope workflow.
