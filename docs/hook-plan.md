# Hook Plan

Skiller is currently packaged with repo-local guidance only. No global hook is installed by this checkout.

Recommended future hooks after review:

- `skiller-mcp-preflight.py`: a `UserPromptSubmit` hook that checks whether `skiller` is configured and reachable for prompts about creating, improving, or recording skills and memories.
- `skiller-mcp-evidence-guard.py`: a `Stop` hook that requires final answers to mention Skiller evidence when the turn claims a skill or memory draft was captured through Skiller.

Both hooks should be copied into `~/.codex/hooks/` only after review and trust through `/hooks`. They should check `http://127.0.0.1:8794/health`, avoid printing local data, and provide exact remediation:

```bash
cd "/home/god/Documents/Codex Workspace/Skiller"
.venv/bin/skiller serve --host 127.0.0.1 --port 8794 --data-dir data
codex mcp add skiller --transport streamable_http http://127.0.0.1:8794/mcp
```

