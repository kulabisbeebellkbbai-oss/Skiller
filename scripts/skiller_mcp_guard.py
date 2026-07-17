#!/usr/bin/env python3
"""Codex hook that routes reusable work through Skiller MCP."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import UTC, datetime
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
ISSUE_LINE_RE = re.compile(r"\b(error|warning|warn|failed|failure|blocked|exception|traceback)\b", re.IGNORECASE)
DIAGNOSTIC_PREFIX_RE = re.compile(
    r"^\s*(error|warning|warn|failed|failure|exception|traceback|[a-z0-9_.-]+:\s+(?:error|warning|warn|failed|blocked))\b",
    re.IGNORECASE,
)
SELF_REPEAT_NOTICE_RE = re.compile(r"skiller_mcp_guard:\s+repeated warning/error pattern detected", re.IGNORECASE)
CODE_OR_DIFF_RE = re.compile(r"^\s*(?:[+\-]|@@|```|[\"']|\\n[+\-])")
SYNTHETIC_TEST_PATTERN_RE = re.compile(r"Warning:\s+hook preflight failed for Skiller", re.IGNORECASE)
VOLATILE_RE = re.compile(r"0x[0-9a-f]+|\b\d{2,}\b|/tmp/[^\s]+|pid=\d+", re.IGNORECASE)


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


def state_path() -> Path:
    root = Path(os.environ.get("SKILLER_MCP_GUARD_STATE_DIR", codex_home() / "skiller-mcp-guard"))
    return root.expanduser() / "state.json"


def load_state() -> dict[str, Any]:
    path = state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"patterns": {}}
    if not isinstance(data, dict):
        return {"patterns": {}}
    pruned, changed = prune_stale_patterns(data)
    if changed:
        save_state(pruned)
    return pruned


def prune_stale_patterns(state: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    patterns = state.get("patterns")
    if not isinstance(patterns, dict):
        state["patterns"] = {}
        return state, True
    stale = []
    for key, item in patterns.items():
        detail = ""
        if isinstance(item, dict):
            detail = str(item.get("detail") or "")
        material = "\n".join([str(key), detail])
        if (
            SELF_REPEAT_NOTICE_RE.search(material)
            or CODE_OR_DIFF_RE.search(detail)
            or SYNTHETIC_TEST_PATTERN_RE.search(material)
        ):
            stale.append(key)
    for key in stale:
        patterns.pop(key, None)
    return state, bool(stale)


def save_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_pattern(text: str) -> str:
    normalized = VOLATILE_RE.sub("<var>", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized[:240]


def record_pattern(kind: str, detail: str, fix: str) -> tuple[int, bool]:
    key = f"{kind}:{normalize_pattern(detail)}"
    state = load_state()
    patterns = state.setdefault("patterns", {})
    item = patterns.setdefault(key, {"count": 0, "notified_at_count": 0, "first_seen": None})
    item["count"] = int(item.get("count", 0)) + 1
    item["last_seen"] = datetime.now(UTC).isoformat()
    item["first_seen"] = item.get("first_seen") or item["last_seen"]
    item["detail"] = detail[:500]
    item["fix"] = fix
    count = int(item["count"])
    should_notify = count >= 2 and int(item.get("notified_at_count", 0)) < count
    if should_notify:
        item["notified_at_count"] = count
    save_state(state)
    return count, should_notify


def parse_sse_json(body: str) -> dict[str, Any]:
    for line in body.splitlines():
        if line.startswith("data: "):
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}
    return {}


def skiller_rpc(payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        SKILLER_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return parse_sse_json(response.read().decode("utf-8", errors="replace"))


def call_skiller_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    skiller_rpc({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "skiller-mcp-guard", "version": "0.1.0"},
        },
    })
    result = skiller_rpc({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    return result.get("result", {}) if isinstance(result.get("result"), dict) else {}


def skiller_preflight(task_description: str) -> str:
    try:
        result = call_skiller_tool("recommend_skills", {"task_description": task_description[:2000], "limit": 3})
        recommendations = result.get("structuredContent", {}).get("result", [])
        if not recommendations:
            call_skiller_tool("refresh_skill_catalog", {})
            result = call_skiller_tool("recommend_skills", {"task_description": task_description[:2000], "limit": 3})
            recommendations = result.get("structuredContent", {}).get("result", [])
        if recommendations:
            names = [str(item.get("skill_name")) for item in recommendations[:3] if isinstance(item, dict)]
            return f"Skiller MCP preflight ran recommend_skills; candidates: {', '.join(names)}."
        return "Skiller MCP preflight ran recommend_skills; no prior matching skill was found."
    except Exception as exc:
        count, notify = record_pattern(
            "skiller-preflight-call-failed",
            f"{type(exc).__name__}: {exc}",
            "Check skiller-mcp.service health and the Streamable HTTP MCP endpoint.",
        )
        if notify:
            return (
                "Skiller MCP preflight call is repeatedly failing. There may be a fix: "
                "check skiller-mcp.service health and the MCP endpoint."
            )
        return "Skiller MCP route required, but the preflight tool call failed; Stop hook will enforce evidence."


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
        for failure in failures:
            record_pattern("skiller-readiness", failure, "Start skiller-mcp.service or register the skiller MCP server.")
        print("skiller_mcp_guard: blocked prompt because Skiller MCP is not ready.", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 2

    preflight_evidence = skiller_preflight(text)
    emit_continue_message(
        f"{preflight_evidence} "
        "Skiller MCP route required for reusable work. Use skiller.recommend_skills or "
        "refresh_skill_catalog before choosing skills when relevant, then record outcomes with "
        "capture_work_product, record_skill_run, or propose_skill_update before the final answer. "
        "Include brief Skiller MCP evidence in the final response."
    )
    return 0


def stop_check(payload: dict[str, Any]) -> int:
    load_state()
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
    hook_prompt_text = "\n".join(HOOK_PROMPT_RE.findall("\n".join(text for _role, text in entries if text)))
    diagnostic_text = "\n".join([tool_text, hook_prompt_text])

    if not final_claims_work(user_text, assistant_text):
        repeated = repeated_issue_message(diagnostic_text)
        if repeated:
            print(repeated, file=sys.stderr)
            return 2
        return 0
    if has_skiller_evidence(evidence_text):
        repeated = repeated_issue_message(diagnostic_text)
        if repeated:
            print(repeated, file=sys.stderr)
            return 2
        return 0
    count, notify = record_pattern(
        "missing-skiller-evidence",
        user_text[:500],
        "Use Skiller in preflight and include Skiller MCP evidence before finalizing reusable work.",
    )
    extra = ""
    if notify:
        extra = (
            f" This missing-evidence pattern has repeated {count} times; the likely fix is to run Skiller "
            "before finalizing and include its evidence, or decide to ignore this pattern for now."
        )
    print(
        "skiller_mcp_guard: blocked final response; use Skiller MCP before finalizing reusable work "
        "and include brief evidence such as skiller.recommend_skills, capture_work_product, "
        "record_skill_run, propose_skill_update, or a Skiller draft path."
        f"{extra}",
        file=sys.stderr,
    )
    return 2


def repeated_issue_message(text: str) -> str:
    candidate_lines = []
    hook_prompts = HOOK_PROMPT_RE.findall(text)
    for prompt in hook_prompts:
        stripped = re.sub(r"</?hook_prompt[^>]*>", "", prompt).strip()
        for line in stripped.splitlines():
            normalized = line.strip()
            if is_live_diagnostic_line(normalized):
                candidate_lines.append(normalized)
    without_hook_prompts = strip_hook_prompts(text)
    for line in without_hook_prompts.splitlines():
        stripped = line.strip()
        if is_live_diagnostic_line(stripped):
            candidate_lines.append(stripped)
    for line in candidate_lines[:5]:
        count, notify = record_pattern(
            "warning-or-error",
            line,
            "Troubleshoot the repeated warning/error pattern, or explicitly ignore it for now.",
        )
        if notify:
            return (
                "skiller_mcp_guard: repeated warning/error pattern detected. "
                f"It has appeared {count} times: {line[:240]} "
                "There may be a fix; ask the user whether to troubleshoot it now or ignore it for now."
            )
    return ""


def is_live_diagnostic_line(line: str) -> bool:
    if not line:
        return False
    if SELF_REPEAT_NOTICE_RE.search(line):
        return False
    if CODE_OR_DIFF_RE.search(line):
        return False
    return bool(DIAGNOSTIC_PREFIX_RE.search(line))


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
