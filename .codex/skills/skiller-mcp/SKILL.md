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
- When a learning corrects or completes a prior failed/partial learning, pass `corrects_learning_ids` and the current `thread_id` to `capture_work_product`, or use `link_learning_correction` for an existing record.
- Use `get_learning_lineage` before proposing a process update from a known learning id so child corrections and follow-on guardrails are applied with the root workflow.
- Use `scan_learning_lineage` after a batch of learnings or when records look related but unlinked; review dry-run candidates before lowering thresholds.
- Use `lineage_scan_due` or the installed `skiller-lineage-scan.timer` for periodic maintenance so new iterations are connected over time.
- Use `scan_memory_records` when AI memory may contain skill-relevant lessons that should be linked to Skiller learnings or imported as memory-derived guardrails.
- Use `memory_scan_due` or the installed `skiller-memory-scan.timer` for periodic AI-memory association.
- Use `get_learning_memory_context` when a learning has `memory_record_ids` and the thread needs to follow those links back to resolvable AI-memory summaries.
- Use `record_overseer_guidance` for Overseer-provided expansion requests, and `apply_overseer_guidance` only applies bounded configuration actions whose `security_review_status` is `passed`.
- Use `record_skill_run` when a named skill was used and the outcome is known.
- Use `recommend_skills` before work where prior local skill history may affect tool choice.
- Use `refresh_skill_catalog` to index installed or project-local `SKILL.md` files before relying on recommendations.
- Use `list_skill_catalog` to inspect the indexed skill catalog.
- Use `set_skill_update_policy` to mark skills that Skiller must not draft updates for without explicit user approval.
- Use `list_skill_update_policies` before drafting updates when protected skills may be involved.
- Use `propose_skill_update` after a skill fails or only partially works.
- Use `get_skill_profile` when deciding whether an existing skill needs checks or guardrails.

## Protected Skill Updates

- A skill policy with `updatable=false` means Skiller may record learnings and reliability evidence, but must not draft skill updates or return update guardrails unless the tool call includes explicit `user_approved_update=true`.
- Treat protected-skill approval as turn-specific; do not infer approval from prior conversations.
- When a protected update is blocked, report the block and ask for approval before generating drafts.

## Hook Reliability Guardrails

- If a Stop hook repeatedly catches missing Skiller evidence, treat it as a hook-design failure: fix the preflight hook so it uses Skiller before model work.
- Track repeated warning or error patterns quietly from hook prompts and diagnostic tool output, not ordinary assistant planning prose.
- Notify only when the same diagnostic pattern repeats and there is a likely fix to troubleshoot or explicitly ignore.
- Repeated-pattern detectors must ignore their own notification text plus patch hunks, quoted code, and diff examples; these are not live diagnostics.
- When detector rules change, migrate or prune stale state entries at hook startup so old false positives do not keep firing after the code is fixed.
- For diagnostics owned by another enforcement hook such as `calculator_mcp_guard`, record the first occurrence quietly. If the same owned diagnostic repeats, surface a targeted troubleshoot-or-ignore prompt instead of silently swallowing it.
- Do not spam advisory messages for one-off warnings or errors.

## Learning Lineage Guardrails

- Corrections must link back to the earliest known failed or partial learning, not only the most recent follow-up record.
- When repairing old records, backfill the root or original learning so future recommendations can surface the correction chain.
- If a thread id is known, attach it to both the correction and the corrected learning through Skiller lineage metadata.
- Scanner-applied links must be explainable with shared skill, tags, terms, paths, thread IDs, or correction timing; do not silently link unrelated records.
- Before a thread repeats a process, inspect `get_learning_lineage` or a relevant skill profile so prior follow-on issues and environment-specific resources are visible.
- AI-memory association must preserve provenance through `memory_record_ids` and avoid bulk-importing rollout logs, passphrases, secrets, or raw private memory dumps.
- Overseer guidance may expand scanner behavior only through reviewed, bounded configuration actions; unreviewed or failed security reviews remain recorded but unapplied.

## Fallback

If the server is unavailable, continue the task but explicitly say Skiller capture was skipped. Do not invent reliability records or draft paths. For durable memory updates, follow the active memory-update rules instead of writing directly to global memory files.

## Verification

```bash
codex mcp get skiller
curl http://127.0.0.1:8794/health
.venv/bin/python scripts/smoke_mcp.py
python3 scripts/install_skiller_hooks.py --dry-run
```
