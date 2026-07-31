from __future__ import annotations

import json

from skiller.cli import main
from skiller.models import Novelty, Outcome, SkillLearning
from skiller.storage import SkillerStore
from scripts.run_adaptive_review import main as adaptive_review_main
from scripts.run_memory_scan import main as memory_scan_main


def test_scan_lineage_cli_skips_when_not_due(tmp_path, capsys) -> None:
    store = SkillerStore(tmp_path)
    store.capture_work_product(
        SkillLearning(
            title="One captured learning",
            summary="This learning exists so the first scan has data.",
            novelty=Novelty.VARIANT,
            outcome=Outcome.WORKED,
            skill_name="skiller-mcp",
        ),
        create_drafts=False,
    )
    store.scan_learning_lineage(dry_run=True)

    main([
        "scan-lineage",
        "--data-dir",
        str(tmp_path),
        "--min-new-learnings",
        "10",
        "--max-age-hours",
        "24",
    ])
    output = json.loads(capsys.readouterr().out)

    assert output["skipped"] is True
    assert output["due"]["reason"] == "not due"


def test_adaptive_review_records_effectiveness_and_due_state(tmp_path, capsys, monkeypatch) -> None:
    store = SkillerStore(tmp_path)
    store.capture_work_product(
        SkillLearning(
            title="Adaptive review learning",
            summary="A learning record should drive the adaptive maintenance decision.",
            novelty=Novelty.VARIANT,
            outcome=Outcome.WORKED,
            skill_name="skiller-mcp",
        ),
        create_drafts=False,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["run_adaptive_review.py", "--data-dir", str(tmp_path)],
    )

    assert adaptive_review_main() == 0
    output = json.loads(capsys.readouterr().out)

    assert output["review"]["schedule_mode"] in {"record_based", "time_based", "hybrid"}
    assert "lineage_due" in output


def test_memory_scan_cli_runs_against_registry(tmp_path, capsys) -> None:
    memory_root = tmp_path / "memories"
    memory_root.mkdir()
    (memory_root / "MEMORY.md").write_text(
        """# Task Group: Skiller memory scan

## Reusable knowledge

- skiller-mcp should connect memory records to skill learnings so future recommendations include prior guardrails.
""",
        encoding="utf-8",
    )
    store = SkillerStore(tmp_path / "data")
    store.capture_work_product(
        SkillLearning(
            title="Skiller memory scan",
            summary="Connect memory records to skill learnings for future recommendation guardrails.",
            novelty=Novelty.GUARDRAIL,
            outcome=Outcome.WORKED,
            skill_name="skiller-mcp",
        ),
        create_drafts=False,
    )

    main([
        "scan-memory",
        "--data-dir",
        str(tmp_path / "data"),
        "--memory-root",
        str(memory_root),
        "--threshold",
        "5",
        "--apply",
        "--force",
    ])
    output = json.loads(capsys.readouterr().out)

    assert output["skipped"] is False
    assert output["result"]["linked"] == 1


def test_memory_scan_wrapper_reports_guidance_and_due(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_memory_scan.py", "--data-dir", str(tmp_path), "--force"],
    )

    assert memory_scan_main() == 0
    output = json.loads(capsys.readouterr().out)

    assert "guidance" in output
    assert "memory_due" in output
