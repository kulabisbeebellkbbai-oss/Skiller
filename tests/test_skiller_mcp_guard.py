from __future__ import annotations

import json
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


def run_stop(transcript: Path) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"transcript_path": str(transcript)})
    return subprocess.run(
        ["python3", str(SCRIPT), "--from-stdin", "--stop-check"],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )


def test_stop_blocks_completed_work_without_skiller_evidence(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout.jsonl"
    write_transcript(transcript, "Implement a new hook", "Implemented the hook and tests passed.")

    result = run_stop(transcript)

    assert result.returncode == 2
    assert "Skiller MCP" in result.stderr


def test_stop_allows_completed_work_with_skiller_evidence(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout.jsonl"
    write_transcript(
        transcript,
        "Implement a new hook",
        "Implemented the hook. Skiller MCP evidence: skiller.capture_work_product recorded the change.",
    )

    result = run_stop(transcript)

    assert result.returncode == 0


def test_stop_ignores_non_work_answers(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout.jsonl"
    write_transcript(transcript, "What is Skiller?", "Skiller is an MCP server for skill capture.")

    result = run_stop(transcript)

    assert result.returncode == 0

