# Architecture

Skiller separates transport from behavior:

- `skiller.server` defines MCP tools and the loopback Streamable HTTP app.
- `skiller.storage` owns the JSON-backed event store, draft generation, reliability summaries, and recommendation ranking.
- `skiller.models` contains the validated records and response shapes.
- `skiller.cli` provides the local server entrypoint.

The server is intentionally conservative. It can draft skill and memory files under the project data directory, but it does not install global Codex skills, hooks, or memory updates. Installation changes should remain explicit and reviewed.

## Tool Families

- `capture_work_product`: record a new, variant, or failed workflow and draft a skill plus memory note.
- `record_skill_run`: append reliability evidence for a skill invocation.
- `recommend_skills`: rank known skills for a task description.
- `propose_skill_update`: summarize guardrails or changes suggested by recent failures and variants.
- `list_recent_learnings`: inspect recent captured records.
- `get_skill_profile`: inspect one skill's summaries, artifacts, and reliability.

