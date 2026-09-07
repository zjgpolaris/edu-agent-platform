"""Local reviewed-content capabilities; no user data, network, or writes."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re

from agents import autotutor_content as content

MAX_CANDIDATES = 20
LABELS = {"cause": "失败原因", "purpose": "目的", "impact": "影响", "significance": "历史意义", "measure": "措施"}
REASONS = {"explicit_focus", "available_priority_target", "lower_difficulty_available", "default_available",
           "no_available_target", "grade_unavailable", "content_unavailable", "catalog_changed"}


def grade_matches(requested, actual):
    value = str(requested or "").strip()
    return not value or value == actual or (value in {"七年级", "八年级", "九年级"} and bool(actual) and actual.startswith(value))


@dataclass
class Catalog:
    entries: tuple
    version: str
    _capabilities: dict = field(default_factory=dict)

    def question_valid(self, label, question, kind):
        with content.use_content_snapshot(self.entries):
            entry = content.find_curated_content(content.build_learning_objective(label))
            if not entry:
                return False
            pool = entry.practice_items if kind == "practice" else entry.exit_ticket_items
            item = next((q for q in pool if q.assessment_id == (question or {}).get("assessment_id")), None)
            if not item:
                return False
            expected = content.assessment_to_question(content._stable_option_order(item))
            return all((question or {}).get(k) == expected[k] for k in ("question", "answer", "options", "options_meta"))

    def capability(self, label):
        objective = content.build_learning_objective(label)
        key = (objective.entity, objective.aspect)
        if key in self._capabilities:
            return self._capabilities[key]
        result = {"objective_id": objective.objective_id, "grade": None, "lesson": None, "content_version": None, "pairs": {}, "difficulties": [], "practice_difficulties": {}}
        with content.use_content_snapshot(self.entries):
            entry = content.find_curated_content(objective)
            if entry and entry.review_status in content.APPROVED_REVIEW_STATUSES:
                result.update(grade=entry.grade, lesson=entry.lesson, content_version=entry.content_version)
                for i, item in enumerate(entry.practice_items):
                    practice = content.prepare_content(objective, {}, kind="practice", variant_index=i)
                    if practice.validation.status != "verified" or not practice.assessment:
                        continue
                    exits = []
                    for j, ticket in enumerate(entry.exit_ticket_items):
                        if ticket.difficulty != "medium":
                            continue
                        checked = content.prepare_content(objective, {}, kind="exit_ticket", variant_index=j,
                            excluded_assessment_id=item.assessment_id, excluded_assessment=practice.assessment)
                        if checked.validation.status == "verified" and checked.assessment:
                            exits.append(checked.assessment.assessment_id)
                    if exits:
                        result["pairs"][item.assessment_id] = exits
                        result["practice_difficulties"][item.assessment_id] = item.difficulty
                result["difficulties"] = sorted(set(result["practice_difficulties"].values()), key=content.DIFFICULTY_RANK.get)
        self._capabilities[key] = result
        return result


def snapshot():
    entries = content.load_curated_content()
    version = hashlib.sha256(json.dumps([e.model_dump(mode="json") for e in entries], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return Catalog(entries, version)


def targets(grade=None):
    catalog = snapshot()
    normalized = str(grade).strip() if grade is not None else None
    known = {e.grade for e in catalog.entries}
    if normalized is not None and (not normalized or not any(grade_matches(normalized, g) for g in known)):
        return {"schema_version": 1, "catalog_version": catalog.version, "items": [], "reason": "grade_unavailable"}
    items = []
    for entry in catalog.entries[:100]:
        if normalized is not None and not grade_matches(normalized, entry.grade):
            continue
        label = entry.entity + LABELS.get(entry.aspect, "核心史实")
        cap = catalog.capability(label)
        items.append({"objective_id": cap["objective_id"], "label": label, "grade": entry.grade,
                      "launchable": bool(cap["difficulties"]), "available_difficulties": cap["difficulties"]})
    return {"schema_version": 1, "catalog_version": catalog.version, "items": items}


def choose(weakpoints, weak_topics, recent_topics, *, grade=None, focus=None, catalog=None):
    catalog = catalog or snapshot()
    wrong = {str(w.get("knowledge_tag", "")): int(w.get("wrong_count") or 0) for w in weakpoints[:MAX_CANDIDATES]}
    raw = [(focus, "explicit_focus")] if focus else (
        [(w.get("knowledge_tag"), "weakpoint") for w in weakpoints[:MAX_CANDIDATES]] +
        [(v, "weak_topic") for v in weak_topics[:MAX_CANDIDATES]] + [(v, "recent_topic") for v in recent_topics[:MAX_CANDIDATES]])
    if not raw:
        raw = [("鸦片战争影响", "default")]
    seen, skipped = set(), 0
    first = None
    for raw_label, source in raw[:MAX_CANDIDATES]:
        label = str(raw_label or "").strip()[:160]
        if not label or label in seen:
            continue
        seen.add(label)
        first = first or label
        difficulty = "easy" if wrong.get(label, 0) >= 2 else "medium"
        cap = catalog.capability(label)
        allowed = [d for d in cap["difficulties"] if content.DIFFICULTY_RANK[d] <= content.DIFFICULTY_RANK[difficulty]]
        grade_ok = grade_matches(grade, cap["grade"])
        available = bool(allowed) and (bool(focus) or grade_ok)
        if focus or available:
            selected = allowed[-1] if available else difficulty
            reason = "explicit_focus" if focus else "lower_difficulty_available" if selected != difficulty else "default_available" if source == "default" else "available_priority_target"
            return label, selected, {"schema_version": 1, "selection_source": source, "selected_objective_id": cap["objective_id"],
                "requested_difficulty": difficulty, "selected_difficulty": selected, "reason_code": reason if available else "content_unavailable",
                "skipped_count": skipped, "catalog_version": catalog.version, "launchable": available}
        skipped += 1
    label = first or "当前年级学习目标"
    return label, "easy", {"schema_version": 1, "selection_source": "automatic", "selected_objective_id": None,
        "requested_difficulty": "easy", "selected_difficulty": "easy", "reason_code": "no_available_target",
        "skipped_count": skipped, "catalog_version": catalog.version, "launchable": False}


def project_planning(raw, revision=0):
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return None
    def enum(key, values):
        value = raw.get(key)
        return value if isinstance(value, str) and value in values else None
    version = raw.get("catalog_version")
    objective = raw.get("selected_objective_id")
    return {"schema_version": 1, "revision": revision if type(revision) is int and revision >= 0 else 0,
        "selection_source": enum("selection_source", {"explicit_focus", "weakpoint", "weak_topic", "recent_topic", "default", "automatic"}),
        "selected_objective_id": objective if isinstance(objective, str) and re.fullmatch(r"history:[^\s:]{1,80}:[a-z_]{1,30}:v[0-9]+", objective) else None,
        "requested_difficulty": enum("requested_difficulty", {"easy", "medium", "hard"}),
        "selected_difficulty": enum("selected_difficulty", {"easy", "medium", "hard"}),
        "reason_code": enum("reason_code", REASONS),
        "skipped_count": min(MAX_CANDIDATES, max(0, raw.get("skipped_count", 0))) if type(raw.get("skipped_count")) is int else 0,
        "catalog_version": version if isinstance(version, str) and re.fullmatch(r"[0-9a-f]{64}", version) else None,
        "launchable": raw.get("launchable") is True}
