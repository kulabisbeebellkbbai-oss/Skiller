# Hook Plan And Install

Skiller ships a user-scope installer for the hooks needed to ensure Skiller is used for reusable work.

Installed hooks:

- `scripts/skiller_mcp_guard.py --preflight`: a `UserPromptSubmit` hook that checks whether `skiller` is configured and reachable for prompts likely to produce reusable work, then injects route guidance.
- `scripts/skiller_mcp_guard.py --stop-check`: a `Stop` hook that blocks completed-work or failure summaries for relevant prompts unless the turn contains Skiller evidence.

The preflight hook calls Skiller immediately with `recommend_skills`, and falls back to `refresh_skill_catalog` plus another recommendation attempt when no match is found. This prevents Skiller from running only after the Stop hook detects missing evidence.

The Stop hook also tracks repeated warning/error patterns in `~/.codex/skiller-mcp-guard/state.json`. It inspects hook prompts and diagnostic-looking tool output, not ordinary assistant planning prose, patch hunks, quoted code, diff examples, Skiller's own repeated-pattern notification text, or known synthetic verifier patterns. It prunes stale false-positive state at hook startup, stays quiet for one-off warnings, then blocks with a troubleshooting-or-ignore prompt only when the same live diagnostic pattern repeats and there is likely something to fix.

Install:

```bash
cd "/home/god/Documents/Codex Workspace/Skiller"
codex mcp add skiller --url http://127.0.0.1:8794/mcp
python3 scripts/install_skiller_hooks.py
```

The installer copies the hook to `~/.codex/hooks/skiller_mcp_guard.py`, copies the skill to `~/.codex/skills/skiller-mcp`, creates a timestamped backup of `~/.codex/hooks.json`, merges the `UserPromptSubmit` and `Stop` hook entries, and enables `~/.config/systemd/user/skiller-mcp.service`.

After installation, run `/hooks` in Codex and trust the changed Skiller hook entries.
