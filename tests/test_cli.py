from __future__ import annotations

import json

from skiller.cli import main
from skiller.models import Novelty, Outcome, SkillLearning
from skiller.storage import SkillerStore


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
