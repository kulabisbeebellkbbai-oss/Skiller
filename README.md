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

## Codex MCP Registration

```bash
codex mcp add skiller --transport streamable_http http://127.0.0.1:8794/mcp
codex mcp get skiller
```

Skiller writes only under its configured data directory. By default that is `./data` in the current working directory. Draft skills and memory notes are stored under `data/drafts/` for review before installing them into a global Codex scope.
