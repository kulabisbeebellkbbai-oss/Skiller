from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "skiller_mcp_guard.py"


def write_transcript(path: Path, user: str, assistant: str, tool: str = "") -> None:
    entries = [
        {"type": "event_msg", "payload": {"type": "user_message", "message": user}},
        {
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": [{"text": assistant}]},
        },
    ]
    if tool:
        entries.append({"type": "response_item", "payload": {"type": "tool_result", "content": tool}})
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")


def run_stop(
    transcript: Path,
    state_dir: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"transcript_path": str(transcript)})
    env = None
    if state_dir is not None or extra_env:
        env = {**os.environ}
        if state_dir is not None:
            env["SKILLER_MCP_GUARD_STATE_DIR"] = str(state_dir)
        if extra_env:
            env.update(extra_env)
    return subprocess.run(
        ["python3", str(SCRIPT), "--from-stdin", "--stop-check"],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_stop_blocks_completed_work_without_skiller_evidence(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout.jsonl"
    write_transcript(transcript, "Implement a new hook", "Implemented the hook and tests passed.")

    result = run_stop(transcript, tmp_path / "state")

    assert result.returncode == 2
    assert "Skiller MCP" in result.stderr


def test_stop_allows_completed_work_with_skiller_evidence(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout.jsonl"
    write_transcript(
        transcript,
        "Implement a new hook",
        "Implemented the hook. Skiller MCP evidence: skiller.capture_work_product recorded the change.",
    )

    result = run_stop(transcript, tmp_path / "state")

    assert result.returncode == 0


def test_stop_ignores_non_work_answers(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout.jsonl"
    write_transcript(transcript, "What is Skiller?", "Skiller is an MCP server for skill capture.")

    result = run_stop(transcript, tmp_path / "state")

    assert result.returncode == 0


def test_stop_notifies_on_repeated_warning_pattern(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    state_dir = tmp_path / "state"
    hook_prompt = (
        '<hook_prompt hook_run_id="stop:8:/home/god/.codex/hooks.json">'
        "external_hook: Warning: service health check failed."
        "</hook_prompt>"
    )
    write_transcript(first, hook_prompt, "Acknowledged.")
    write_transcript(second, hook_prompt, "Acknowledged.")

    first_result = run_stop(first, state_dir)
    second_result = run_stop(second, state_dir)

    assert first_result.returncode == 0
    assert second_result.returncode == 2
    assert "repeated warning/error pattern" in second_result.stderr


def test_stop_notifies_on_repeated_owned_enforcement_hook(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    state_dir = tmp_path / "state"
    hook_prompt = (
        '<hook_prompt hook_run_id="stop:6:/home/god/.codex/hooks.json">'
        "mcp_usage_guard: blocked final response; include MCP evidence."
        "</hook_prompt>"
    )
    write_transcript(first, hook_prompt, "Acknowledged.")
    write_transcript(second, hook_prompt, "Acknowledged.")

    first_result = run_stop(first, state_dir)
    second_result = run_stop(second, state_dir)

    assert first_result.returncode == 0
    assert second_result.returncode == 2
    assert "repeated owned enforcement-hook diagnostic" in second_result.stderr
    assert "owning enforcement hook" in second_result.stderr


def test_stop_ignores_calculator_guard_when_active_guard_has_metadata_exemption(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    state_dir = tmp_path / "state"
    codex_home = tmp_path / "codex-home"
    hooks_dir = codex_home / "hooks"
    hooks_dir.mkdir(parents=True)
    (hooks_dir / "calculator_mcp_guard.py").write_text(
        "COUNT_OR_HOOK_META_RE = object()\n"
        "def requires_method_evidence(user_text, assistant_text):\n"
        "    return False\n",
        encoding="utf-8",
    )
    hook_prompt = (
        '<hook_prompt hook_run_id="stop:6:/home/god/.codex/hooks.json">'
        "calculator_mcp_guard: blocked final response; use the calculator MCP server."
        "</hook_prompt>"
    )
    write_transcript(first, hook_prompt, "Acknowledged.")
    write_transcript(second, hook_prompt, "Acknowledged.")

    first_result = run_stop(first, state_dir, {"CODEX_HOME": str(codex_home)})
    second_result = run_stop(second, state_dir, {"CODEX_HOME": str(codex_home)})
    state_path = state_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"patterns": {}}

    assert first_result.returncode == 0
    assert second_result.returncode == 0
    assert state["patterns"] == {}


def test_stop_ignores_repeated_assistant_warning_prose(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    state_dir = tmp_path / "state"
    prose = "I will add a quiet repeated-warning detector and keep it from bugging the user."
    write_transcript(first, "What will you change?", prose)
    write_transcript(second, "What will you change?", prose)

    first_result = run_stop(first, state_dir)
    second_result = run_stop(second, state_dir)

    assert first_result.returncode == 0
    assert second_result.returncode == 0


def test_stop_ignores_own_repeated_warning_notice_with_diff_text(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    state_dir = tmp_path / "state"
    hook_prompt = (
        '<hook_prompt hook_run_id="stop:8:/home/god/.codex/hooks.json">'
        "skiller_mcp_guard: repeated warning/error pattern detected. It has appeared 2 times: '\\n"
        '+        "skiller_mcp_guard: blocked final response; Warning: hook preflight failed for Skiller."\\n'
        '+        " There may be a fix; ask the user whether to troubleshoot it now or ignore it for now.'
        "</hook_prompt>"
    )
    write_transcript(first, hook_prompt, "Acknowledged.")
    write_transcript(second, hook_prompt, "Acknowledged.")

    first_result = run_stop(first, state_dir)
    second_result = run_stop(second, state_dir)

    assert first_result.returncode == 0
    assert second_result.returncode == 0


def test_stop_ignores_own_repeated_owned_notice(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    state_dir = tmp_path / "state"
    hook_prompt = (
        '<hook_prompt hook_run_id="stop:8:/home/god/.codex/hooks.json">'
        "skiller_mcp_guard: repeated owned enforcement-hook diagnostic detected. "
        "It has appeared 2 times: calculator_mcp_guard: blocked final response; "
        "use the calculator MCP server. Likely fix: Calculator guard is repeatedly blocking final answers."
        "</hook_prompt>"
    )
    write_transcript(first, hook_prompt, "Acknowledged.")
    write_transcript(second, hook_prompt, "Acknowledged.")

    first_result = run_stop(first, state_dir)
    second_result = run_stop(second, state_dir)

    assert first_result.returncode == 0
    assert second_result.returncode == 0


def test_stop_prunes_stale_self_notice_patterns(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout.jsonl"
    state_dir = tmp_path / "state"
    state_path = state_dir / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "patterns": {
                    "warning-or-error:skiller_mcp_guard: repeated warning/error pattern detected": {
                        "count": 2,
                        "notified_at_count": 2,
                        "detail": "skiller_mcp_guard: repeated warning/error pattern detected. It has appeared 2 times.",
                    },
                    "warning-or-error:+ diff warning line": {
                        "count": 2,
                        "notified_at_count": 2,
                        "detail": '+ "skiller_mcp_guard: blocked final response; Warning: hook preflight failed"',
                    },
                    "warning-or-error:skiller_mcp_guard: blocked final response; Warning: hook preflight failed for Skiller.": {
                        "count": 2,
                        "notified_at_count": 2,
                        "detail": "skiller_mcp_guard: blocked final response; Warning: hook preflight failed for Skiller.",
                    },
                    "owned-enforcement-hook:calculator_mcp_guard: blocked final response; use the calculator MCP server.": {
                        "count": 2,
                        "notified_at_count": 2,
                        "detail": "calculator_mcp_guard: blocked final response; use the calculator MCP server.",
                        "fix": "Calculator guard is repeatedly blocking final answers. Stop reporting derived counts unless calculator.search_calculation_methods or another method tool is used in the same turn, or adjust calculator_mcp_guard if simple count aggregation should not require domain-method evidence.",
                    },
                    "owned-enforcement-hook:skiller_mcp_guard: repeated owned enforcement-hook diagnostic detected": {
                        "count": 2,
                        "notified_at_count": 2,
                        "detail": "skiller_mcp_guard: repeated owned enforcement-hook diagnostic detected. It has appeared 2 times.",
                    },
                    "warning-or-error:I will fix the hook and add a quiet repeated-warning detector.": {
                        "count": 2,
                        "notified_at_count": 2,
                        "detail": "I will fix the hook and add a quiet repeated-warning detector.",
                    },
                    "warning-or-error:calculator_mcp_guard: blocked final response; use the calculator MCP server.": {
                        "count": 2,
                        "notified_at_count": 2,
                        "detail": "calculator_mcp_guard: blocked final response; use the calculator MCP server.",
                    },
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    write_transcript(transcript, "What is Skiller?", "Skiller is an MCP server.")

    result = run_stop(transcript, state_dir)
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert result.returncode == 0
    assert state["patterns"] == {}
