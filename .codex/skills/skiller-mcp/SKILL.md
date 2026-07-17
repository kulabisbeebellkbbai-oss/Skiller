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

- Use `capture_work_product` after new, different, failed, or guardrail-producing work.
- Use `record_skill_run` when a named skill was used and the outcome is known.
- Use `recommend_skills` before work where prior local skill history may affect tool choice.
- Use `propose_skill_update` after a skill fails or only partially works.
- Use `get_skill_profile` when deciding whether an existing skill needs checks or guardrails.

## Fallback

If the server is unavailable, continue the task but explicitly say Skiller capture was skipped. Do not invent reliability records or draft paths. For durable memory updates, follow the active memory-update rules instead of writing directly to global memory files.

## Verification

```bash
codex mcp get skiller
curl http://127.0.0.1:8794/health
```

