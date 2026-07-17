#!/usr/bin/env python3
"""Codex hook that routes reusable work through Skiller MCP."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any


SKILLER_ENDPOINT = "http://127.0.0.1:8794/mcp"
SKILLER_HEALTH = "http://127.0.0.1:8794/health"

PROMPT_ROUTE_RE = re.compile(
    r"\b("
    r"skiller|skill(?:s)?|memor(?:y|ies)|hook(?:s)?|mcp|agent(?:s)?|plugin(?:s)?|"
    r"create|created|build|built|implement|implemented|fix|fixed|debug|repair|"
    r"improve|refactor|finish|complete|commit|push|publish|test|verify|deploy"
    r")\b",
    re.IGNORECASE,
)
WORK_SUMMARY_RE = re.compile(
    r"\b("
    r"implemented|added|created|built|changed|updated|fixed|repaired|refactored|"
    r"completed|finished|committed|pushed|published|verified|tested|failed|blocked|"
    r"could not|was not able|wasn't able"
    r")\b",
    re.IGNORECASE,
)
SKILLER_EVIDENCE_RE = re.compile(
    r"(Skiller MCP evidence|skiller\.|capture_work_product|record_skill_run|"
    r"recommend_skills|refresh_skill_catalog|list_skill_catalog|get_skill_profile|"
    r"propose_skill_update|codex mcp get skiller|server_name[\"']?\s*:\s*[\"']skiller[\"']|"
    r"http://127\.0\.0\.1:8794/mcp|scripts/smoke_mcp\.py)",
    re.IGNORECASE,
)
HOOK_PROMPT_RE = re.compile(r"<hook_prompt\b[^>]*>.*?</hook_prompt>", re.IGNORECASE | re.DOTALL)


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve()


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def strip_hook_prompts(text: str) -> str:
    return HOOK_PROMPT_RE.sub("", text)


def prompt_text(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return strip_hook_prompts(value)
    return strip_hook_prompts(json.dumps(payload, sort_keys=True))


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def entry_role_and_text(entry: dict[str, Any]) -> tuple[str | None, str]:
    payload = entry.get("payload") or {}
    entry_type = entry.get("type")
    if entry_type == "response_item":
        item_type = payload.get("type")
        if item_type == "message":
            return payload.get("role"), text_from_content(payload.get("content"))
        if item_type in {"function_call", "function_call_output", "tool_call", "tool_result"}:
            return "tool", json.dumps(payload, sort_keys=True)
        return None, json.dumps(payload, sort_keys=True)
    if entry_type == "event_msg":
        msg_type = payload.get("type")
        if msg_type == "user_message":
            return "user", str(payload.get("message") or "")
        if msg_type == "agent_message":
            return "assistant", str(payload.get("message") or "")
        return None, json.dumps(payload, sort_keys=True)
    return None, ""


def latest_turn(path: Path) -> list[tuple[str | None, str]]:
    entries: list[tuple[str | None, str]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict):
                entries.append(entry_role_and_text(raw))
    last_user = -1
    for index, (role, _text) in enumerate(entries):
        if role == "user":
            last_user = index
    return entries[last_user:] if last_user >= 0 else entries


def config_text() -> str:
    path = codex_home() / "config.toml"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def has_skiller_config() -> bool:
    text = config_text()
    return "[mcp_servers.skiller]" in text and SKILLER_ENDPOINT in text


def health_ready() -> bool:
    try:
        with urllib.request.urlopen(SKILLER_HEALTH, timeout=2) as response:
            return 200 <= response.status < 300
    except OSError:
        return False


def needs_skiller_prompt(text: str) -> bool:
    return bool(PROMPT_ROUTE_RE.search(text))


def final_claims_work(user_text: str, assistant_text: str) -> bool:
    if not needs_skiller_prompt(user_text):
        return False
    return bool(WORK_SUMMARY_RE.search(assistant_text))


def has_skiller_evidence(text: str) -> bool:
    return bool(SKILLER_EVIDENCE_RE.search(text))


def emit_continue_message(message: str) -> None:
    print(json.dumps({
        "continue": True,
        "suppressOutput": True,
        "systemMessage": message,
    }))


def preflight(payload: dict[str, Any]) -> int:
    text = prompt_text(payload)
    if not needs_skiller_prompt(text):
        return 0
    failures: list[str] = []
    if not has_skiller_config():
        failures.append(
            "Skiller MCP server is not configured; run: "
            "codex mcp add skiller --transport streamable_http http://127.0.0.1:8794/mcp"
        )
    if not health_ready():
        failures.append(
            "Skiller MCP server is not reachable; run: "
            "systemctl --user start skiller-mcp.service"
        )
    if failures:
        print("skiller_mcp_guard: blocked prompt because Skiller MCP is not ready.", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 2

    emit_continue_message(
        "Skiller MCP route required for reusable work. Use skiller.recommend_skills or "
        "refresh_skill_catalog before choosing skills when relevant, then record outcomes with "
        "capture_work_product, record_skill_run, or propose_skill_update before the final answer. "
        "Include brief Skiller MCP evidence in the final response."
    )
    return 0


def stop_check(payload: dict[str, Any]) -> int:
    transcript = payload.get("transcript_path")
    if not transcript:
        return 0
    path = Path(str(transcript))
    if not path.exists():
        return 0
    entries = latest_turn(path)
    user_text = strip_hook_prompts("\n".join(text for role, text in entries if role == "user" and text))
    assistant_text = strip_hook_prompts("\n".join(text for role, text in entries if role == "assistant" and text))
    tool_text = "\n".join(text for role, text in entries if role == "tool" and text)
    evidence_text = "\n".join([assistant_text, tool_text])

    if not final_claims_work(user_text, assistant_text):
        return 0
    if has_skiller_evidence(evidence_text):
        return 0
    print(
        "skiller_mcp_guard: blocked final response; use Skiller MCP before finalizing reusable work "
        "and include brief evidence such as skiller.recommend_skills, capture_work_product, "
        "record_skill_run, propose_skill_update, or a Skiller draft path.",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-stdin", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--stop-check", action="store_true")
    args = parser.parse_args()

    if os.environ.get("SKILLER_MCP_GUARD_DISABLE") == "1":
        return 0
    payload = read_payload() if args.from_stdin else {}
    if args.preflight:
        return preflight(payload)
    if args.stop_check:
        return stop_check(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

