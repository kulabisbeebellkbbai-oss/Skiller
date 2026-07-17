---
name: skiller-mcp
description: Use the local Skiller MCP server to capture new or variant workflows, draft skill and memory artifacts, record skill reliability, and recommend skills for future tasks.
---

# Skiller MCP

Use Skiller when a task produced a reusable workflow, a variant of an existing workflow, a failed skill attempt, a new guardrail, or reliability evidence about a skill.

## Server

- MCP name: `skiller`
- Local endpoint: `http://127.0.0.1:8794/mcp`
- Health endpoint: `http://127.0.0.1:8794/health`
- Auth: none for loopback local use

## Required Evidence

When Skiller results affect the final answer, include brief evidence such as:

- tool name used;
- skill name recorded or recommended;
- draft artifact path;
- reliability summary counts when relevant.

## Tool Routing

- Preflight hooks that enforce Skiller must call Skiller immediately, such as `recommend_skills` or `refresh_skill_catalog`, not only emit guidance for the model to use Skiller later.
- Use `capture_work_product` after new, different, failed, or guardrail-producing work.
- Use `record_skill_run` when a named skill was used and the outcome is known.
- Use `recommend_skills` before work where prior local skill history may affect tool choice.
- Use `refresh_skill_catalog` to index installed or project-local `SKILL.md` files before relying on recommendations.
- Use `list_skill_catalog` to inspect the indexed skill catalog.
- Use `propose_skill_update` after a skill fails or only partially works.
- Use `get_skill_profile` when deciding whether an existing skill needs checks or guardrails.

## Hook Reliability Guardrails

- If a Stop hook repeatedly catches missing Skiller evidence, treat it as a hook-design failure: fix the preflight hook so it uses Skiller before model work.
- Track repeated warning or error patterns quietly from hook prompts and diagnostic tool output, not ordinary assistant planning prose.
- Notify only when the same diagnostic pattern repeats and there is a likely fix to troubleshoot or explicitly ignore.
- Do not spam advisory messages for one-off warnings or errors.

## Fallback

If the server is unavailable, continue the task but explicitly say Skiller capture was skipped. Do not invent reliability records or draft paths. For durable memory updates, follow the active memory-update rules instead of writing directly to global memory files.

## Verification

```bash
codex mcp get skiller
curl http://127.0.0.1:8794/health
.venv/bin/python scripts/smoke_mcp.py
python3 scripts/install_skiller_hooks.py --dry-run
```
