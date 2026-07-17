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


def run_stop(transcript: Path, state_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"transcript_path": str(transcript)})
    env = None
    if state_dir is not None:
        env = {**os.environ, "SKILLER_MCP_GUARD_STATE_DIR": str(state_dir)}
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
        "calculator_mcp_guard: blocked final response; use the calculator MCP server and include appropriate MCP evidence."
        "</hook_prompt>"
    )
    write_transcript(first, hook_prompt, "Acknowledged.")
    write_transcript(second, hook_prompt, "Acknowledged.")

    first_result = run_stop(first, state_dir)
    second_result = run_stop(second, state_dir)

    assert first_result.returncode == 0
    assert second_result.returncode == 2
    assert "repeated owned enforcement-hook diagnostic" in second_result.stderr
    assert "calculator.search_calculation_methods" in second_result.stderr


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
