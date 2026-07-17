from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .models import (
    CatalogRefreshResult,
    CaptureResult,
    DraftArtifact,
    Outcome,
    ReliabilitySummary,
    SkillCatalogEntry,
    SkillLearning,
    SkillPolicy,
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
        self.catalog_path = data_dir / "skill_catalog.jsonl"
        self.policies_path = data_dir / "skill_policies.jsonl"
        self.drafts_dir = data_dir / "drafts"

    def initialize(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.learnings_path.touch(exist_ok=True)
        self.runs_path.touch(exist_ok=True)
        self.catalog_path.touch(exist_ok=True)
        self.policies_path.touch(exist_ok=True)

    def capture_work_product(
        self,
        learning: SkillLearning,
        create_drafts: bool = True,
        user_approved_update: bool = False,
    ) -> CaptureResult:
        self.initialize()
        self._append_jsonl(self.learnings_path, learning.model_dump(mode="json"))
        artifacts: list[DraftArtifact] = []
        policy = self.get_skill_policy(learning.skill_name) if learning.skill_name else None
        if create_drafts and policy and not policy.updatable and not user_approved_update:
            return CaptureResult(
                learning=learning,
                artifacts=artifacts,
                message=(
                    f"Captured learning, but draft update for protected skill '{policy.skill_name}' "
                    "was blocked pending user approval."
                ),
                update_blocked=True,
                policy=policy,
            )
        if create_drafts:
            artifacts.extend(self._write_drafts(learning))
        return CaptureResult(
            learning=learning,
            artifacts=artifacts,
            message="Captured learning and generated reviewable drafts." if artifacts else "Captured learning.",
            policy=policy,
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

        catalog = {entry.name: entry for entry in self.list_skill_catalog(limit=500)}
        skill_names = sorted(set(grouped) | set(catalog))
        recommendations: list[SkillRecommendation] = []
        for skill_name in skill_names:
            learnings = grouped.get(skill_name, [])
            catalog_entry = catalog.get(skill_name)
            combined = " ".join(
                [skill_name]
                + [item.title for item in learnings]
                + [item.summary for item in learnings]
                + [tag for item in learnings for tag in item.tags]
                + [step for item in learnings for step in item.reusable_steps]
                + ([catalog_entry.description] if catalog_entry else [])
                + (catalog_entry.tags if catalog_entry else [])
            )
            skill_terms = self._terms(combined)
            overlap = task_terms & skill_terms
            if not overlap:
                continue
            reliability = self.reliability_summary(skill_name)
            reliability_bonus = reliability.reliability if reliability.reliability is not None else 0.5
            catalog_bonus = 0.25 if catalog_entry else 0
            learning_bonus = 0.5 if learnings else 0
            score = len(overlap) + reliability_bonus + catalog_bonus + learning_bonus
            source = "combined" if catalog_entry and learnings else "catalog" if catalog_entry else "captured_learning"
            reason = f"Matched terms: {', '.join(sorted(overlap)[:8])}"
            recommendations.append(
                SkillRecommendation(
                    skill_name=skill_name,
                    score=round(score, 3),
                    reason=reason,
                    source=source,
                    description=catalog_entry.description if catalog_entry else "",
                    source_path=catalog_entry.source_path if catalog_entry else "",
                    updatable=self.is_skill_updatable(skill_name),
                    reliability=reliability,
                )
            )

        return sorted(recommendations, key=lambda item: item.score, reverse=True)[: max(1, min(limit, 10))]

    def propose_skill_update(self, skill_name: str, user_approved_update: bool = False) -> SkillProfile:
        normalized = self._normalize_skill(skill_name)
        policy = self.get_skill_policy(normalized)
        if policy and not policy.updatable and not user_approved_update:
            return SkillProfile(
                skill_name=normalized,
                catalog_entry=self.get_catalog_entry(normalized),
                policy=policy,
                learnings=self.list_recent_learnings(limit=50, skill_name=normalized),
                reliability=self.reliability_summary(normalized),
                suggested_guardrails=[],
                draft_paths=self._draft_paths(normalized),
            )
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
            catalog_entry=self.get_catalog_entry(normalized),
            policy=policy,
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

    def set_skill_policy(self, skill_name: str, updatable: bool, reason: str = "") -> SkillPolicy:
        self.initialize()
        policy = SkillPolicy(skill_name=skill_name, updatable=updatable, reason=reason)
        policies = {item.skill_name: item for item in self.list_skill_policies()}
        policies[policy.skill_name] = policy
        ordered = [item.model_dump(mode="json") for item in sorted(policies.values(), key=lambda item: item.skill_name)]
        self._write_jsonl(self.policies_path, ordered)
        return policy

    def list_skill_policies(self) -> list[SkillPolicy]:
        return [SkillPolicy.model_validate(item) for item in self._read_jsonl(self.policies_path)]

    def get_skill_policy(self, skill_name: str | None) -> SkillPolicy | None:
        if not skill_name:
            return None
        normalized = self._normalize_skill(skill_name)
        for policy in self.list_skill_policies():
            if policy.skill_name == normalized:
                return policy
        return None

    def is_skill_updatable(self, skill_name: str) -> bool:
        policy = self.get_skill_policy(skill_name)
        return True if policy is None else policy.updatable

    def refresh_skill_catalog(self, root_paths: list[str] | None = None) -> CatalogRefreshResult:
        self.initialize()
        roots = [Path(path).expanduser() for path in (root_paths or self.default_skill_roots())]
        entries: list[SkillCatalogEntry] = []
        skipped = 0
        for root in roots:
            if not root.exists():
                skipped += 1
                continue
            skill_files = [root] if root.name == "SKILL.md" else sorted(root.glob("**/SKILL.md"))
            for skill_file in skill_files:
                parsed = self._parse_skill_file(skill_file)
                if parsed is None:
                    skipped += 1
                    continue
                entries.append(parsed)

        deduped: dict[tuple[str, str], SkillCatalogEntry] = {}
        for entry in entries:
            deduped[(entry.name, entry.source_path)] = entry
        final_entries = sorted(deduped.values(), key=lambda item: (item.name, item.source_path))
        self._write_jsonl(self.catalog_path, [entry.model_dump(mode="json") for entry in final_entries])
        return CatalogRefreshResult(
            scanned_roots=[str(root) for root in roots],
            imported=len(final_entries),
            skipped=skipped,
            entries=final_entries,
        )

    def list_skill_catalog(self, limit: int = 50, query: str = "") -> list[SkillCatalogEntry]:
        entries = [SkillCatalogEntry.model_validate(item) for item in self._read_jsonl(self.catalog_path)]
        if query:
            query_terms = self._terms(query)
            entries = [
                entry
                for entry in entries
                if query_terms & self._terms(" ".join([entry.name, entry.description, " ".join(entry.tags)]))
            ]
        return sorted(entries, key=lambda item: item.name)[: max(1, min(limit, 500))]

    def get_catalog_entry(self, skill_name: str) -> SkillCatalogEntry | None:
        normalized = self._normalize_skill(skill_name)
        for entry in self.list_skill_catalog(limit=500):
            if entry.name == normalized:
                return entry
        return None

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

    def _parse_skill_file(self, skill_file: Path) -> SkillCatalogEntry | None:
        try:
            text = skill_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = skill_file.read_text(encoding="utf-8", errors="ignore")
        if not text.strip():
            return None
        frontmatter = self._frontmatter(text)
        name = frontmatter.get("name") or skill_file.parent.name
        description = frontmatter.get("description") or self._first_paragraph(text)
        tags = sorted(self._terms(" ".join([name, description])) & self._terms(text))
        return SkillCatalogEntry(
            name=name,
            description=description,
            source_path=str(skill_file.resolve()),
            tags=tags[:20],
            updated_at=datetime.now(UTC).isoformat(),
        )

    @staticmethod
    def default_skill_roots() -> list[str]:
        return [str(Path.home() / ".codex" / "skills"), ".codex/skills"]

    @staticmethod
    def _frontmatter(text: str) -> dict[str, str]:
        if not text.startswith("---\n"):
            return {}
        try:
            _, block, _rest = text.split("---", 2)
        except ValueError:
            return {}
        values: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        return values

    @staticmethod
    def _first_paragraph(text: str) -> str:
        paragraphs = [part.strip() for part in text.split("\n\n") if part.strip() and not part.startswith("---")]
        if not paragraphs:
            return ""
        return re.sub(r"\s+", " ", paragraphs[0].replace("#", "")).strip()[:2000]

    @staticmethod
    def _append_jsonl(path: Path, payload: dict) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    @staticmethod
    def _write_jsonl(path: Path, payloads: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for payload in payloads:
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
