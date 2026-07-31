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
    LineageLinkCandidate,
    LineageScanResult,
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
        self.lineage_scans_path = data_dir / "lineage_scans.jsonl"
        self.drafts_dir = data_dir / "drafts"

    def initialize(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.learnings_path.touch(exist_ok=True)
        self.runs_path.touch(exist_ok=True)
        self.catalog_path.touch(exist_ok=True)
        self.policies_path.touch(exist_ok=True)
        self.lineage_scans_path.touch(exist_ok=True)

    def capture_work_product(
        self,
        learning: SkillLearning,
        create_drafts: bool = True,
        user_approved_update: bool = False,
    ) -> CaptureResult:
        self.initialize()
        learning = self._resolve_learning_lineage(learning)
        self._append_jsonl(self.learnings_path, learning.model_dump(mode="json"))
        self._backfill_learning_lineage(learning)
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

    def get_learning(self, learning_id: str) -> SkillLearning | None:
        normalized = learning_id.strip()
        for record in self._learning_records():
            if record.id == normalized:
                return record
        return None

    def link_learning_correction(
        self,
        correction_learning_id: str,
        corrects_learning_ids: list[str],
        thread_id: str = "",
        root_learning_id: str = "",
    ) -> list[SkillLearning]:
        self.initialize()
        correction_id = correction_learning_id.strip()
        target_ids = list(dict.fromkeys(item.strip() for item in corrects_learning_ids if item and item.strip()))
        if not target_ids:
            raise ValueError("At least one corrected learning id is required.")
        records = self._learning_records()
        by_id = {record.id: record for record in records}
        if correction_id not in by_id:
            raise ValueError(f"Unknown correction learning id: {correction_id}")
        missing = [learning_id for learning_id in target_ids if learning_id not in by_id]
        if missing:
            raise ValueError(f"Unknown corrected learning id(s): {', '.join(missing)}")
        root_id = root_learning_id.strip()
        if root_id and root_id not in by_id:
            raise ValueError(f"Unknown root learning id: {root_id}")

        correction = by_id[correction_id]
        correction.corrects_learning_ids = self._merge_ids(correction.corrects_learning_ids, target_ids)
        if not correction.parent_learning_ids:
            correction.parent_learning_ids = target_ids
        if root_id:
            correction.root_learning_id = root_id
        elif not correction.root_learning_id:
            first_target = by_id[target_ids[0]]
            correction.root_learning_id = first_target.root_learning_id or first_target.id
        if thread_id.strip():
            correction.thread_ids = self._merge_ids(correction.thread_ids, [thread_id.strip()])

        for target_id in target_ids:
            target = by_id[target_id]
            target.correction_learning_ids = self._merge_ids(target.correction_learning_ids, [correction.id])
            target.child_learning_ids = self._merge_ids(target.child_learning_ids, [correction.id])
            if thread_id.strip():
                target.thread_ids = self._merge_ids(target.thread_ids, [thread_id.strip()])
            target_root_id = target.root_learning_id or target.id
            if target_root_id in by_id and target_root_id != target.id:
                root = by_id[target_root_id]
                root.child_learning_ids = self._merge_ids(root.child_learning_ids, [correction.id])
                root.correction_learning_ids = self._merge_ids(root.correction_learning_ids, [correction.id])
                if thread_id.strip():
                    root.thread_ids = self._merge_ids(root.thread_ids, [thread_id.strip()])

        self._write_learning_records(records)
        linked_ids = [correction_id] + target_ids
        if correction.root_learning_id:
            linked_ids.append(correction.root_learning_id)
        return [by_id[learning_id] for learning_id in dict.fromkeys(linked_ids) if learning_id in by_id]

    def get_learning_lineage(self, learning_id: str) -> dict[str, SkillLearning | list[SkillLearning] | None]:
        learning = self.get_learning(learning_id)
        if learning is None:
            raise ValueError(f"Unknown learning id: {learning_id}")
        by_id = {record.id: record for record in self._learning_records()}
        root = by_id.get(learning.root_learning_id) if learning.root_learning_id else learning
        parents = [by_id[item] for item in learning.parent_learning_ids if item in by_id]
        corrections = [by_id[item] for item in learning.correction_learning_ids if item in by_id]
        children = [by_id[item] for item in learning.child_learning_ids if item in by_id]
        if not corrections:
            corrections = [record for record in by_id.values() if learning.id in record.corrects_learning_ids]
        if not children:
            children = [record for record in by_id.values() if learning.id in record.parent_learning_ids]
        return {
            "learning": learning,
            "root": root,
            "parents": parents,
            "corrections": sorted(corrections, key=lambda item: item.created_at),
            "children": sorted(children, key=lambda item: item.created_at),
        }

    def scan_learning_lineage(
        self,
        threshold: float = 7.0,
        limit: int = 100,
        dry_run: bool = True,
    ) -> LineageScanResult:
        self.initialize()
        records = sorted(self._learning_records(), key=lambda item: item.created_at)
        candidates: list[LineageLinkCandidate] = []
        for child_index, child in enumerate(records):
            for parent in records[:child_index]:
                candidate = self._lineage_candidate(parent, child, threshold)
                if candidate is not None:
                    candidates.append(candidate)
        candidates = sorted(candidates, key=lambda item: item.score, reverse=True)[: max(1, min(limit, 500))]
        applied = 0
        if not dry_run:
            for candidate in candidates:
                self._apply_lineage_candidate(candidate)
                candidate.applied = True
                applied += 1
        result = LineageScanResult(
            scanned=len(records),
            candidates=len(candidates),
            applied=applied,
            threshold=threshold,
            dry_run=dry_run,
            links=candidates,
        )
        self._append_jsonl(self.lineage_scans_path, result.model_dump(mode="json"))
        return result

    def lineage_scan_due(self, min_new_learnings: int = 10, max_age_hours: int = 24) -> dict[str, object]:
        self.initialize()
        records = self._learning_records()
        scans = self._read_jsonl(self.lineage_scans_path)
        if not scans:
            return {
                "due": bool(records),
                "reason": "no previous lineage scan",
                "learnings": len(records),
                "new_learnings": len(records),
                "last_scan_at": "",
            }
        last_scan = scans[-1]
        last_scan_at = str(last_scan.get("generated_at") or "")
        new_records = [record for record in records if record.created_at > last_scan_at]
        age_hours = self._age_hours(last_scan_at)
        due = len(new_records) >= min_new_learnings or age_hours >= max_age_hours
        reason = "not due"
        if len(new_records) >= min_new_learnings:
            reason = "new learning threshold reached"
        elif age_hours >= max_age_hours:
            reason = "time threshold reached"
        return {
            "due": due,
            "reason": reason,
            "learnings": len(records),
            "new_learnings": len(new_records),
            "last_scan_at": last_scan_at,
            "age_hours": round(age_hours, 3),
        }

    def recommend_skills(self, task_description: str, limit: int = 5) -> list[SkillRecommendation]:
        task_terms = self._terms(task_description)
        if not task_terms:
            return []

        grouped: dict[str, list[SkillLearning]] = {}
        for learning in self.list_recent_learnings(limit=50):
            if learning.skill_name:
                grouped.setdefault(learning.skill_name, []).append(learning)
        grouped = {skill_name: self._with_linked_learnings(learnings) for skill_name, learnings in grouped.items()}

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
        learnings = self._with_linked_learnings(self.list_recent_learnings(limit=50, skill_name=normalized))
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

    def _learning_records(self) -> list[SkillLearning]:
        return [SkillLearning.model_validate(item) for item in self._read_jsonl(self.learnings_path)]

    def _write_learning_records(self, records: list[SkillLearning]) -> None:
        self._write_jsonl(self.learnings_path, [record.model_dump(mode="json") for record in records])

    def _resolve_learning_lineage(self, learning: SkillLearning) -> SkillLearning:
        by_id = {record.id: record for record in self._learning_records()}
        related_ids = learning.corrects_learning_ids or learning.parent_learning_ids
        if related_ids and not learning.root_learning_id:
            first_related = by_id.get(related_ids[0])
            if first_related is not None:
                learning.root_learning_id = first_related.root_learning_id or first_related.id
        if learning.corrects_learning_ids and not learning.parent_learning_ids:
            learning.parent_learning_ids = list(learning.corrects_learning_ids)
        return learning

    def _backfill_learning_lineage(self, learning: SkillLearning) -> None:
        related_ids = self._merge_ids(learning.parent_learning_ids, learning.corrects_learning_ids)
        if not related_ids and not learning.root_learning_id:
            return
        records = self._learning_records()
        by_id = {record.id: record for record in records}
        changed = False
        for related_id in related_ids:
            target = by_id.get(related_id)
            if target is None:
                continue
            before = target.model_dump(mode="json")
            target.child_learning_ids = self._merge_ids(target.child_learning_ids, [learning.id])
            if related_id in learning.corrects_learning_ids:
                target.correction_learning_ids = self._merge_ids(target.correction_learning_ids, [learning.id])
            target.thread_ids = self._merge_ids(target.thread_ids, learning.thread_ids)
            changed = changed or target.model_dump(mode="json") != before
            root_id = target.root_learning_id or target.id
            root = by_id.get(root_id)
            if root is not None and root.id != target.id:
                before_root = root.model_dump(mode="json")
                root.child_learning_ids = self._merge_ids(root.child_learning_ids, [learning.id])
                if related_id in learning.corrects_learning_ids:
                    root.correction_learning_ids = self._merge_ids(root.correction_learning_ids, [learning.id])
                root.thread_ids = self._merge_ids(root.thread_ids, learning.thread_ids)
                changed = changed or root.model_dump(mode="json") != before_root
        if learning.root_learning_id and learning.root_learning_id in by_id:
            root = by_id[learning.root_learning_id]
            before_root = root.model_dump(mode="json")
            root.child_learning_ids = self._merge_ids(root.child_learning_ids, [learning.id])
            root.thread_ids = self._merge_ids(root.thread_ids, learning.thread_ids)
            changed = changed or root.model_dump(mode="json") != before_root
        if changed:
            self._write_learning_records(records)

    def _with_linked_learnings(self, learnings: list[SkillLearning]) -> list[SkillLearning]:
        by_id = {record.id: record for record in self._learning_records()}
        selected: dict[str, SkillLearning] = {learning.id: learning for learning in learnings}
        to_visit = list(selected.values())
        while to_visit:
            learning = to_visit.pop()
            linked_ids = (
                learning.parent_learning_ids
                + learning.corrects_learning_ids
                + learning.child_learning_ids
                + learning.correction_learning_ids
                + ([learning.root_learning_id] if learning.root_learning_id else [])
            )
            for linked_id in linked_ids:
                linked = by_id.get(linked_id)
                if linked is not None and linked.id not in selected and linked.skill_name == learning.skill_name:
                    selected[linked.id] = linked
                    to_visit.append(linked)
        return sorted(selected.values(), key=lambda item: item.created_at, reverse=True)

    def _lineage_candidate(
        self,
        parent: SkillLearning,
        child: SkillLearning,
        threshold: float,
    ) -> LineageLinkCandidate | None:
        if parent.id == child.id:
            return None
        if child.id in parent.child_learning_ids or child.id in parent.correction_learning_ids:
            return None
        if parent.id in child.parent_learning_ids or parent.id in child.corrects_learning_ids:
            return None

        score = 0.0
        reasons: list[str] = []
        if parent.skill_name and child.skill_name and parent.skill_name == child.skill_name:
            score += 3.0
            reasons.append(f"same skill {parent.skill_name}")

        shared_threads = set(parent.thread_ids) & set(child.thread_ids)
        if shared_threads:
            score += 4.0
            reasons.append(f"shared thread {sorted(shared_threads)[0]}")

        shared_tags = set(parent.tags) & set(child.tags)
        if shared_tags:
            tag_score = min(3.0, len(shared_tags) * 1.25)
            score += tag_score
            reasons.append(f"shared tags {', '.join(sorted(shared_tags)[:4])}")

        parent_terms = self._learning_terms(parent)
        child_terms = self._learning_terms(child)
        shared_terms = parent_terms & child_terms
        if shared_terms:
            term_score = min(4.0, len(shared_terms) * 0.45)
            score += term_score
            reasons.append(f"shared terms {', '.join(sorted(shared_terms)[:8])}")

        shared_paths = self._path_prefixes(parent.files_changed) & self._path_prefixes(child.files_changed)
        if shared_paths:
            score += min(2.0, len(shared_paths))
            reasons.append(f"shared paths {', '.join(sorted(shared_paths)[:3])}")

        if parent.outcome in {Outcome.FAILED, Outcome.PARTIAL} and child.outcome == Outcome.WORKED:
            score += 2.0
            reasons.append("later worked after failed or partial parent")
        if child.novelty.value in {"guardrail", "variant"} and parent.novelty.value in {"failure", "guardrail", "variant"}:
            score += 1.0
            reasons.append("child is a follow-on variant or guardrail")
        if self._looks_like_correction(parent, child):
            score += 2.0
            reasons.append("correction language overlaps")

        if score < threshold:
            return None
        root_id = parent.root_learning_id or parent.id
        return LineageLinkCandidate(
            parent_learning_id=parent.id,
            child_learning_id=child.id,
            root_learning_id=root_id,
            score=round(score, 3),
            reasons=reasons,
        )

    def _apply_lineage_candidate(self, candidate: LineageLinkCandidate) -> None:
        self.link_learning_correction(
            correction_learning_id=candidate.child_learning_id,
            corrects_learning_ids=[candidate.parent_learning_id],
            root_learning_id=candidate.root_learning_id,
        )

    def _learning_terms(self, learning: SkillLearning) -> set[str]:
        text = " ".join(
            [
                learning.title,
                learning.summary,
                learning.task_context,
                learning.reliability_impact,
                " ".join(learning.tags),
                " ".join(learning.reusable_steps),
                " ".join(learning.guardrails),
            ]
        )
        return self._terms(text)

    def _path_prefixes(self, paths: list[str]) -> set[str]:
        prefixes: set[str] = set()
        for raw in paths:
            path = Path(raw)
            parts = path.parts
            if "Codex Workspace" in parts:
                index = parts.index("Codex Workspace")
                if len(parts) > index + 1:
                    prefixes.add("/".join(parts[: index + 2]))
                    continue
            if len(parts) >= 4:
                prefixes.add("/".join(parts[:4]))
        return prefixes

    def _looks_like_correction(self, parent: SkillLearning, child: SkillLearning) -> bool:
        child_text = " ".join([child.title, child.summary, child.task_context]).lower()
        if not re.search(r"\b(fix|correct|repair|follow-on|followup|after|remediat|backfill|supersed)", child_text):
            return False
        return bool(self._learning_terms(parent) & self._learning_terms(child))

    @staticmethod
    def _age_hours(iso_timestamp: str) -> float:
        try:
            parsed = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        except ValueError:
            return float("inf")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return (datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds() / 3600

    @staticmethod
    def _merge_ids(existing: list[str], additions: list[str]) -> list[str]:
        return list(dict.fromkeys([item.strip() for item in existing + additions if item and item.strip()]))

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
