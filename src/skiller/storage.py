from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .models import (
    CaptureResult,
    DraftArtifact,
    Outcome,
    ReliabilitySummary,
    SkillLearning,
    SkillProfile,
    SkillRecommendation,
    SkillRun,
)


WORD_RE = re.compile(r"[a-z0-9][a-z0-9_-]+")


class SkillerStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.learnings_path = data_dir / "learnings.jsonl"
        self.runs_path = data_dir / "skill_runs.jsonl"
        self.drafts_dir = data_dir / "drafts"

    def initialize(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.learnings_path.touch(exist_ok=True)
        self.runs_path.touch(exist_ok=True)

    def capture_work_product(self, learning: SkillLearning, create_drafts: bool = True) -> CaptureResult:
        self.initialize()
        self._append_jsonl(self.learnings_path, learning.model_dump(mode="json"))
        artifacts: list[DraftArtifact] = []
        if create_drafts:
            artifacts.extend(self._write_drafts(learning))
        return CaptureResult(
            learning=learning,
            artifacts=artifacts,
            message="Captured learning and generated reviewable drafts." if artifacts else "Captured learning.",
        )

    def record_skill_run(self, run: SkillRun) -> ReliabilitySummary:
        self.initialize()
        self._append_jsonl(self.runs_path, run.model_dump(mode="json"))
        return self.reliability_summary(run.skill_name)

    def list_recent_learnings(self, limit: int = 10, skill_name: str | None = None) -> list[SkillLearning]:
        records = [SkillLearning.model_validate(item) for item in self._read_jsonl(self.learnings_path)]
        if skill_name:
            normalized = self._normalize_skill(skill_name)
            records = [record for record in records if record.skill_name == normalized]
        return sorted(records, key=lambda item: item.created_at, reverse=True)[: max(1, min(limit, 50))]

    def recommend_skills(self, task_description: str, limit: int = 5) -> list[SkillRecommendation]:
        task_terms = self._terms(task_description)
        if not task_terms:
            return []

        grouped: dict[str, list[SkillLearning]] = {}
        for learning in self.list_recent_learnings(limit=50):
            if learning.skill_name:
                grouped.setdefault(learning.skill_name, []).append(learning)

        recommendations: list[SkillRecommendation] = []
        for skill_name, learnings in grouped.items():
            combined = " ".join(
                [skill_name]
                + [item.title for item in learnings]
                + [item.summary for item in learnings]
                + [tag for item in learnings for tag in item.tags]
                + [step for item in learnings for step in item.reusable_steps]
            )
            skill_terms = self._terms(combined)
            overlap = task_terms & skill_terms
            if not overlap:
                continue
            reliability = self.reliability_summary(skill_name)
            reliability_bonus = reliability.reliability if reliability.reliability is not None else 0.5
            score = len(overlap) + reliability_bonus
            reason = f"Matched terms: {', '.join(sorted(overlap)[:8])}"
            recommendations.append(
                SkillRecommendation(
                    skill_name=skill_name,
                    score=round(score, 3),
                    reason=reason,
                    reliability=reliability,
                )
            )

        return sorted(recommendations, key=lambda item: item.score, reverse=True)[: max(1, min(limit, 10))]

    def propose_skill_update(self, skill_name: str) -> SkillProfile:
        normalized = self._normalize_skill(skill_name)
        learnings = self.list_recent_learnings(limit=50, skill_name=normalized)
        guardrails = []
        for learning in learnings:
            if learning.outcome in {Outcome.FAILED, Outcome.PARTIAL} or learning.novelty.value in {"failure", "guardrail"}:
                guardrails.extend(learning.guardrails)
                if learning.reliability_impact:
                    guardrails.append(learning.reliability_impact)
        deduped = list(dict.fromkeys(item for item in guardrails if item))
        return SkillProfile(
            skill_name=normalized,
            learnings=learnings,
            reliability=self.reliability_summary(normalized),
            suggested_guardrails=deduped,
            draft_paths=self._draft_paths(normalized),
        )

    def reliability_summary(self, skill_name: str) -> ReliabilitySummary:
        normalized = self._normalize_skill(skill_name)
        runs = [SkillRun.model_validate(item) for item in self._read_jsonl(self.runs_path)]
        runs = [run for run in runs if run.skill_name == normalized]
        counts = Counter(run.outcome.value for run in runs)
        completed = counts["worked"] + counts["failed"] + counts["partial"]
        reliability = None if completed == 0 else counts["worked"] / completed
        failure_modes = Counter(run.failure_mode for run in runs if run.failure_mode)
        return ReliabilitySummary(
            skill_name=normalized,
            total_runs=len(runs),
            worked=counts["worked"],
            failed=counts["failed"],
            partial=counts["partial"],
            unknown=counts["unknown"],
            reliability=round(reliability, 3) if reliability is not None else None,
            common_failure_modes=[mode for mode, _ in failure_modes.most_common(5)],
        )

    def get_skill_profile(self, skill_name: str) -> SkillProfile:
        return self.propose_skill_update(skill_name)

    def _write_drafts(self, learning: SkillLearning) -> list[DraftArtifact]:
        skill_name = learning.skill_name or self._slug(learning.title)
        draft_dir = self.drafts_dir / learning.id
        draft_dir.mkdir(parents=True, exist_ok=False)
        skill_dir = draft_dir / "skill" / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        memory_path = draft_dir / "memory-note.md"
        skill_path.write_text(self._render_skill(learning, skill_name), encoding="utf-8")
        memory_path.write_text(self._render_memory(learning, skill_name), encoding="utf-8")
        return [
            DraftArtifact(kind="skill", path=str(skill_path)),
            DraftArtifact(kind="memory", path=str(memory_path)),
        ]

    def _render_skill(self, learning: SkillLearning, skill_name: str) -> str:
        steps = "\n".join(f"- {step}" for step in learning.reusable_steps) or "- Add concrete steps after review."
        guardrails = "\n".join(f"- {guardrail}" for guardrail in learning.guardrails) or "- Verify the workflow before relying on it."
        evidence = "\n".join(f"- {item}" for item in learning.evidence) or "- No evidence captured yet."
        return f"""---
name: {skill_name}
description: {learning.summary[:220].replace(chr(10), " ")}
---

# {learning.title}

Use this skill when a task matches the captured context below and the workflow is expected to be reusable.

## Captured Context

{learning.task_context or learning.summary}

## Reusable Steps

{steps}

## Guardrails

{guardrails}

## Evidence To Preserve

{evidence}
"""

    def _render_memory(self, learning: SkillLearning, skill_name: str) -> str:
        files = "\n".join(f"- {path}" for path in learning.files_changed) or "- None recorded."
        tags = ", ".join(learning.tags) if learning.tags else "none"
        return f"""# Skiller memory draft: {learning.title}

- skill_name: {skill_name}
- novelty: {learning.novelty.value}
- outcome: {learning.outcome.value}
- tags: {tags}

## Summary

{learning.summary}

## Why This Should Be Remembered

{learning.reliability_impact or "This work captured a reusable workflow or variant."}

## Files Changed

{files}
"""

    def _draft_paths(self, skill_name: str) -> list[str]:
        if not self.drafts_dir.exists():
            return []
        matches = []
        for path in self.drafts_dir.glob(f"*/skill/{skill_name}/SKILL.md"):
            matches.append(str(path))
        return sorted(matches)

    @staticmethod
    def _append_jsonl(path: Path, payload: dict) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    @staticmethod
    def _normalize_skill(value: str) -> str:
        return value.strip().lower().replace(" ", "-")

    @staticmethod
    def _slug(value: str) -> str:
        words = WORD_RE.findall(value.lower())
        return "-".join(words[:8]) or "captured-skill"

    @staticmethod
    def _terms(value: str) -> set[str]:
        stop_words = {"and", "the", "for", "with", "from", "that", "this", "when", "into", "then", "they"}
        return {word for word in WORD_RE.findall(value.lower()) if len(word) > 2 and word not in stop_words}

