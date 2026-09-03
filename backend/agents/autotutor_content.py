"""可信 AutoTutor 内容合同与确定性门禁。

本模块只负责目标解析、审定内容装配和纯校验；会话推进仍由
``agents.auto_tutor`` 的单一状态机负责。
"""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from rag.history_query import HistoryAspect, HistoryQuestionType, parse_history_query


Difficulty = Literal["easy", "medium", "hard"]
AssessmentKind = Literal["practice", "exit_ticket"]
CognitiveAction = Literal["recall", "explain", "compare", "apply"]
DIFFICULTY_RANK: dict[Difficulty, int] = {"easy": 0, "medium": 1, "hard": 2}
COGNITIVE_RANK: dict[CognitiveAction, int] = {"recall": 0, "explain": 1, "compare": 2, "apply": 3}
APPROVED_REVIEW_STATUSES = {"teacher_reviewed", "curriculum_reviewed"}
FORBIDDEN_PLACEHOLDERS = ("基本史实", "与史实不符", "张冠李戴", "完全无关")
def _resolve_content_path(module_file: Path | None = None) -> Path:
    """Resolve curated content in both source-tree and flattened Docker layouts."""
    module_path = (module_file or Path(__file__)).resolve()
    relative = Path("knowledge_base/history/autotutor_content.json")
    # Source tree: <repo>/backend/agents/*.py -> <repo>/knowledge_base.
    # Docker:      /app/agents/*.py          -> /app/knowledge_base.
    candidates = (module_path.parents[2] / relative, module_path.parents[1] / relative)
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


CONTENT_PATH = _resolve_content_path()


class LearningObjective(BaseModel):
    schema_version: Literal[1] = 1
    objective_id: str
    raw_tag: str
    source_tag: str | None = None
    entity: str
    entity_id: str | None = None
    aspect: HistoryAspect
    question_type: HistoryQuestionType
    grade: str | None = None
    lesson: str | None = None
    target_outcome: str
    misconception_code: str | None = None
    confidence: float
    reason_codes: list[str] = Field(default_factory=list)


class TeachingEvidenceDecision(BaseModel):
    status: Literal["sufficient", "partial", "none"]
    objective_id: str
    source_ids: list[str] = Field(default_factory=list)
    answer_bearing_source_ids: list[str] = Field(default_factory=list)
    source_count: int = 0
    answer_bearing_source_count: int = 0
    entity_match: bool = False
    aspect_match: bool = False
    reason_codes: list[str] = Field(default_factory=list)


class TeachingClaim(BaseModel):
    claim_id: str
    text: str
    source_ids: list[str]
    objective_aspect: HistoryAspect


class TeachingContent(BaseModel):
    schema_version: Literal[1] = 1
    objective_id: str
    explanation: str
    key_points: list[str]
    example: str | None = None
    claims: list[TeachingClaim]
    generation_mode: Literal["curated", "llm", "deterministic_fallback"]


class AssessmentOption(BaseModel):
    option_id: Literal["A", "B", "C", "D"]
    text: str
    is_correct: bool
    misconception_code: str | None = None
    feedback: str
    source_ids: list[str] = Field(default_factory=list)


class AssessmentItem(BaseModel):
    schema_version: Literal[1] = 1
    assessment_id: str
    objective_id: str
    kind: AssessmentKind
    stem: str
    review_prompt: str | None = None
    feedback_material: str | None = None
    options: list[AssessmentOption]
    difficulty: Difficulty
    cognitive_action: CognitiveAction
    source_ids: list[str]
    variant_of: str | None = None
    generation_mode: Literal["curated", "llm", "deterministic_fallback"]


class ContentValidation(BaseModel):
    schema_version: Literal[1] = 1
    status: Literal["verified", "blocked"]
    objective_alignment: bool
    evidence_verified: bool
    assessment_valid: bool
    answer_unique: bool
    student_readable: bool
    reason_codes: list[str] = Field(default_factory=list)


class CuratedSourceRef(BaseModel):
    source_id: str
    label: str
    answer_bearing: bool = True


class CuratedContentEntry(BaseModel):
    objective_id: str
    entity: str
    aspect: HistoryAspect
    grade: str | None = None
    lesson: str | None = None
    target_outcome: str
    explanation: str
    claims: list[TeachingClaim]
    key_points: list[str]
    example: str | None = None
    practice_items: list[AssessmentItem]
    exit_ticket_items: list[AssessmentItem]
    source_refs: list[CuratedSourceRef]
    review_status: str
    reviewed_by: str
    content_version: str


class PreparedContent(BaseModel):
    objective: LearningObjective
    evidence: TeachingEvidenceDecision
    teaching: TeachingContent | None = None
    assessment: AssessmentItem | None = None
    validation: ContentValidation
    content_version: str | None = None
    evidence_label: str | None = None
    blocked_reason: str | None = None


class AssessmentSelection(BaseModel):
    status: Literal["selected", "blocked"]
    assessment: AssessmentItem | None = None
    target_difficulty: Difficulty
    reason_codes: list[str] = Field(default_factory=list)


def assessment_fingerprint(item: AssessmentItem | dict[str, Any]) -> str:
    """Return a stable semantic identity shared by AutoTutor and review."""
    data = item.model_dump() if isinstance(item, AssessmentItem) else dict(item)
    options = data.get("options") or []
    normalized_options: list[dict[str, Any]] = []
    for option in options:
        option_data = option.model_dump() if isinstance(option, AssessmentOption) else dict(option)
        normalized_options.append({
            "option_id": option_data.get("option_id"),
            "text": _compact(option_data.get("text")),
            "is_correct": bool(option_data.get("is_correct")),
        })
    canonical = {
        "objective_id": data.get("objective_id"),
        "stem": _compact(data.get("review_prompt") or data.get("stem") or data.get("question")),
        "options": normalized_options,
        "cognitive_action": data.get("cognitive_action"),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


class ContentGateSettings(BaseModel):
    mode: Literal["off", "shadow", "enforce"] = "off"
    basis_points: int = 0
    kill_switch: bool = False

    @classmethod
    def from_env(cls) -> "ContentGateSettings":
        mode = str(os.getenv("EDU_AGENT_AUTOTUTOR_CONTENT_GATE_MODE", "off")).strip().lower()
        if mode not in {"off", "shadow", "enforce"}:
            mode = "off"
        try:
            bps = int(os.getenv("EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS", "0"))
        except ValueError:
            bps = 0
        kill_switch = str(os.getenv("EDU_AGENT_AUTOTUTOR_CONTENT_GATE_KILL_SWITCH", "false")).strip().lower() in {
            "1", "true", "yes", "on",
        }
        return cls(mode=mode, basis_points=max(0, min(bps, 10_000)), kill_switch=kill_switch)

    def selected_mode(self, student_id: str) -> Literal["off", "shadow", "enforce"]:
        if self.mode == "off" or self.basis_points <= 0:
            return "off"
        bucket = int(hashlib.sha256(student_id.encode("utf-8")).hexdigest()[:8], 16) % 10_000
        return self.mode if bucket < self.basis_points else "off"


def _compact(value: Any) -> str:
    return "".join(char.lower() for char in str(value or "") if char.isalnum())


def build_learning_objective(
    raw_tag: str,
    *,
    source_tag: str | None = None,
    grade: str | None = None,
    lesson: str | None = None,
    misconception_hint: str | None = None,
) -> LearningObjective:
    parsed = parse_history_query(raw_tag, grade=grade, lesson=lesson)
    entity = str(parsed.entity or "").strip()
    aspect = parsed.aspect
    objective_id = f"history:{entity or 'unknown'}:{aspect}:v1"
    reason_codes = list(parsed.reason_codes)
    if not entity:
        reason_codes.append("objective_entity_missing")
    if aspect == "unknown":
        reason_codes.append("objective_aspect_unknown")
    misconception_code = None
    hint = _compact(misconception_hint)
    if aspect == "cause" and ("影响" in hint or "意义" in hint):
        misconception_code = "cause_impact_confusion"
    return LearningObjective(
        objective_id=objective_id,
        raw_tag=raw_tag,
        source_tag=source_tag,
        entity=entity,
        entity_id=parsed.entity_id,
        aspect=aspect,
        question_type=parsed.question_type,
        grade=grade,
        lesson=lesson or parsed.lesson,
        target_outcome=f"能够解释{entity or raw_tag}的{_aspect_label(aspect)}并辨析常见混淆",
        misconception_code=misconception_code,
        confidence=parsed.confidence,
        reason_codes=list(dict.fromkeys(reason_codes)),
    )


def _aspect_label(aspect: HistoryAspect) -> str:
    return {
        "cause": "原因",
        "purpose": "目的",
        "impact": "影响",
        "significance": "意义",
        "process": "经过",
        "result": "结果",
        "measure": "措施",
    }.get(aspect, "核心史实")


@lru_cache(maxsize=2)
def _load_content_cached(path: str, mtime_ns: int) -> tuple[CuratedContentEntry, ...]:
    del mtime_ns
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ()
    rows = payload.get("items", []) if isinstance(payload, dict) else []
    entries: list[CuratedContentEntry] = []
    for row in rows:
        try:
            entries.append(CuratedContentEntry.model_validate(row))
        except Exception:
            continue
    return tuple(entries)


def load_curated_content(path: Path = CONTENT_PATH) -> tuple[CuratedContentEntry, ...]:
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return ()
    return _load_content_cached(str(path), mtime_ns)


def find_curated_content(objective: LearningObjective) -> CuratedContentEntry | None:
    return next(
        (
            entry
            for entry in load_curated_content()
            if _compact(entry.entity) == _compact(objective.entity) and entry.aspect == objective.aspect
        ),
        None,
    )


def evidence_decision(
    objective: LearningObjective,
    retrieval_data: dict[str, Any] | None,
    *,
    curated: CuratedContentEntry | None = None,
) -> TeachingEvidenceDecision:
    data = retrieval_data or {}
    sufficiency = data.get("evidence_sufficiency") or {}
    sources = [source for source in data.get("sources", []) if isinstance(source, dict)]
    answer_bearing = [source for source in sources if source.get("answer_bearing") is True]
    source_ids = [str(source.get("source_id")) for source in sources if source.get("source_id")]
    answer_ids = [str(source.get("source_id")) for source in answer_bearing if source.get("source_id")]
    reasons = list(sufficiency.get("reason_codes") or [])
    status = str(sufficiency.get("status") or data.get("retrieval_status") or "none")
    entity_match = bool(sufficiency.get("entity_match"))
    aspect_match = bool(sufficiency.get("aspect_match"))

    if curated is not None and curated.review_status in APPROVED_REVIEW_STATUSES:
        curated_ids = [ref.source_id for ref in curated.source_refs]
        curated_answer_ids = [ref.source_id for ref in curated.source_refs if ref.answer_bearing]
        source_ids = list(dict.fromkeys([*answer_ids, *curated_ids]))
        answer_ids = list(dict.fromkeys([*answer_ids, *curated_answer_ids]))
        status = "sufficient"
        entity_match = True
        aspect_match = True
        reasons.append("reviewed_content_pack_used")

    if objective.confidence < 0.8:
        reasons.append("objective_confidence_below_threshold")
        status = "none"
    if not objective.entity:
        reasons.append("objective_entity_missing")
        status = "none"
    if objective.aspect == "unknown":
        reasons.append("objective_aspect_unknown")
        status = "none"

    normalized_status: Literal["sufficient", "partial", "none"] = (
        status if status in {"sufficient", "partial", "none"} else "none"
    )
    return TeachingEvidenceDecision(
        status=normalized_status,
        objective_id=objective.objective_id,
        source_ids=source_ids,
        answer_bearing_source_ids=answer_ids,
        source_count=len(source_ids),
        answer_bearing_source_count=len(answer_ids),
        entity_match=entity_match,
        aspect_match=aspect_match,
        reason_codes=list(dict.fromkeys(reasons)),
    )


def _stable_option_order(item: AssessmentItem) -> AssessmentItem:
    options = list(item.options)
    if len(options) != 4:
        return item
    offset = int(hashlib.sha256(item.assessment_id.encode("utf-8")).hexdigest()[:8], 16) % 4
    ordered = options[offset:] + options[:offset]
    relabeled = [option.model_copy(update={"option_id": "ABCD"[index]}) for index, option in enumerate(ordered)]
    return item.model_copy(update={"options": relabeled})


def select_assessment(
    pool: list[AssessmentItem],
    *,
    kind: AssessmentKind,
    target_difficulty: Difficulty,
    excluded_assessment_ids: set[str] | None = None,
    preferred_cognitive_actions: list[CognitiveAction] | None = None,
    seed: str = "",
) -> AssessmentSelection:
    """Select a fresh assessment whose declared difficulty matches the plan."""
    excluded = excluded_assessment_ids or set()
    candidates = [
        item
        for item in pool
        if item.kind == kind
        and item.difficulty == target_difficulty
        and item.assessment_id not in excluded
    ]
    if not candidates:
        return AssessmentSelection(
            status="blocked",
            target_difficulty=target_difficulty,
            reason_codes=["no_fresh_assessment_for_target_difficulty"],
        )

    preferred = preferred_cognitive_actions or []
    preferred_rank = {action: index for index, action in enumerate(preferred)}

    def sort_key(item: AssessmentItem) -> tuple[int, int, str]:
        preference = preferred_rank.get(item.cognitive_action, len(preferred_rank) + 1)
        digest = hashlib.sha256(f"{seed}:{item.assessment_id}".encode("utf-8")).hexdigest()
        return preference, COGNITIVE_RANK[item.cognitive_action], digest

    selected = min(candidates, key=sort_key)
    return AssessmentSelection(
        status="selected",
        assessment=selected,
        target_difficulty=target_difficulty,
    )


def validate_content(
    objective: LearningObjective,
    evidence: TeachingEvidenceDecision,
    teaching: TeachingContent | None,
    assessment: AssessmentItem | None,
    *,
    excluded_assessment_id: str | None = None,
    excluded_assessment: AssessmentItem | None = None,
    require_transfer: bool = False,
) -> ContentValidation:
    reasons: list[str] = []
    objective_alignment = bool(
        teaching
        and assessment
        and teaching.objective_id == objective.objective_id
        and assessment.objective_id == objective.objective_id
    )
    if not objective_alignment:
        reasons.append("objective_alignment_failed")

    evidence_verified = bool(
        objective.confidence >= 0.8
        and evidence.status == "sufficient"
        and evidence.entity_match
        and evidence.aspect_match
        and evidence.answer_bearing_source_count >= 1
    )
    if not evidence_verified:
        reasons.append("missing_answer_bearing_evidence")

    answer_unique = False
    assessment_valid = False
    student_readable = False
    if teaching and assessment:
        option_texts = [_compact(option.text) for option in assessment.options]
        correct = [option for option in assessment.options if option.is_correct]
        answer_unique = len(correct) == 1
        four_unique = len(assessment.options) == 4 and len(set(option_texts)) == 4 and all(option_texts)
        no_placeholders = not any(
            marker in option.text for option in assessment.options for marker in FORBIDDEN_PLACEHOLDERS
        )
        distractors_explained = all(
            option.is_correct or bool(option.misconception_code) for option in assessment.options
        )
        source_set = set(evidence.answer_bearing_source_ids)
        correct_grounded = bool(correct and set(correct[0].source_ids) & source_set)
        item_grounded = bool(set(assessment.source_ids) & source_set)
        claims_grounded = bool(teaching.claims) and all(
            claim.objective_aspect == objective.aspect and bool(set(claim.source_ids) & source_set)
            for claim in teaching.claims
        )
        excluded_id = excluded_assessment_id or (
            excluded_assessment.assessment_id if excluded_assessment else None
        )
        independent_id = not excluded_id or assessment.assessment_id != excluded_id
        independent_stem = not excluded_assessment or _compact(assessment.stem) != _compact(excluded_assessment.stem)
        independent_options = not excluded_assessment or {
            _compact(option.text) for option in assessment.options
        } != {
            _compact(option.text) for option in excluded_assessment.options
        }
        cognitive_rank = {"recall": 0, "explain": 1, "compare": 2, "apply": 3}
        cognitive_advanced = bool(
            excluded_assessment
            and cognitive_rank[assessment.cognitive_action] > cognitive_rank[excluded_assessment.cognitive_action]
        )
        contextual_variant = bool(
            excluded_assessment
            and assessment.variant_of
            and assessment.variant_of in {
                excluded_assessment.assessment_id,
                excluded_assessment.variant_of,
            }
            and independent_stem
            and independent_options
        )
        independent = bool(
            independent_id
            and independent_stem
            and independent_options
            and (
                excluded_assessment is None
                or not require_transfer
                or cognitive_advanced
                or contextual_variant
            )
        )
        if not independent:
            reasons.append("assessment_not_independent")
        assessment_valid = bool(
            four_unique
            and answer_unique
            and no_placeholders
            and distractors_explained
            and correct_grounded
            and item_grounded
            and claims_grounded
            and independent
        )
        student_readable = bool(
            8 <= len(assessment.stem.strip()) <= 180
            and all(2 <= len(option.text.strip()) <= 120 for option in assessment.options)
            and 20 <= len(teaching.explanation.strip()) <= 600
        )
        if not four_unique:
            reasons.append("assessment_options_invalid")
        if not answer_unique:
            reasons.append("assessment_answer_not_unique")
        if not no_placeholders:
            reasons.append("forbidden_placeholder_option")
        if not distractors_explained:
            reasons.append("distractor_misconception_missing")
        if not correct_grounded or not item_grounded or not claims_grounded:
            reasons.append("assessment_evidence_binding_failed")
        if not student_readable:
            reasons.append("student_readability_failed")
    else:
        reasons.append("reviewed_content_missing")

    verified = objective_alignment and evidence_verified and assessment_valid and answer_unique and student_readable
    return ContentValidation(
        status="verified" if verified else "blocked",
        objective_alignment=objective_alignment,
        evidence_verified=evidence_verified,
        assessment_valid=assessment_valid,
        answer_unique=answer_unique,
        student_readable=student_readable,
        reason_codes=list(dict.fromkeys(reasons)),
    )


def prepare_content(
    objective: LearningObjective,
    retrieval_data: dict[str, Any] | None,
    *,
    kind: AssessmentKind,
    variant_index: int = 0,
    target_difficulty: Difficulty | None = None,
    excluded_assessment_ids: set[str] | None = None,
    preferred_cognitive_actions: list[CognitiveAction] | None = None,
    selection_seed: str | None = None,
    excluded_assessment_id: str | None = None,
    excluded_assessment: AssessmentItem | None = None,
) -> PreparedContent:
    curated = find_curated_content(objective)
    evidence = evidence_decision(objective, retrieval_data, curated=curated)
    if curated is None or curated.review_status not in APPROVED_REVIEW_STATUSES:
        validation = validate_content(
            objective,
            evidence,
            None,
            None,
            excluded_assessment_id=excluded_assessment_id,
            excluded_assessment=excluded_assessment,
            require_transfer=kind == "exit_ticket" and excluded_assessment is not None,
        )
        reason = "missing_reviewed_content" if curated is None else "content_review_status_invalid"
        return PreparedContent(
            objective=objective,
            evidence=evidence,
            validation=validation.model_copy(update={"reason_codes": [*validation.reason_codes, reason]}),
            blocked_reason=reason,
        )

    teaching = TeachingContent(
        objective_id=objective.objective_id,
        explanation=curated.explanation,
        key_points=curated.key_points,
        example=curated.example,
        claims=[claim.model_copy(update={"objective_aspect": objective.aspect}) for claim in curated.claims],
        generation_mode="curated",
    )
    pool = curated.practice_items if kind == "practice" else curated.exit_ticket_items
    indexed_assessment = pool[variant_index % len(pool)] if pool else None
    effective_target = target_difficulty or (
        indexed_assessment.difficulty if indexed_assessment else "medium"
    )
    excluded_ids = set(excluded_assessment_ids or set())
    if excluded_assessment_id:
        excluded_ids.add(excluded_assessment_id)
    if target_difficulty is None and indexed_assessment is not None and indexed_assessment.assessment_id not in excluded_ids:
        selection = AssessmentSelection(
            status="selected",
            assessment=indexed_assessment,
            target_difficulty=indexed_assessment.difficulty,
        )
    else:
        selection = select_assessment(
            pool,
            kind=kind,
            target_difficulty=effective_target,
            excluded_assessment_ids=excluded_ids,
            preferred_cognitive_actions=preferred_cognitive_actions,
            seed=selection_seed or f"{objective.objective_id}:{variant_index}:{kind}",
        )
    assessment = _stable_option_order(selection.assessment) if selection.assessment else None
    if assessment is not None:
        assessment = assessment.model_copy(update={"objective_id": objective.objective_id, "kind": kind})
    validation = validate_content(
        objective,
        evidence,
        teaching,
        assessment,
        excluded_assessment_id=excluded_assessment_id,
        excluded_assessment=excluded_assessment,
        require_transfer=kind == "exit_ticket" and excluded_assessment is not None,
    )
    reason_codes = list(dict.fromkeys([*selection.reason_codes, *validation.reason_codes]))
    if reason_codes != validation.reason_codes:
        validation = validation.model_copy(update={"reason_codes": reason_codes})
    blocked_reason = validation.reason_codes[0] if validation.status == "blocked" and validation.reason_codes else None
    return PreparedContent(
        objective=objective,
        evidence=evidence,
        teaching=teaching,
        assessment=assessment,
        validation=validation,
        content_version=curated.content_version,
        evidence_label=f"依据{curated.lesson or '教材'}与项目审定辅导材料",
        blocked_reason=blocked_reason,
    )


def assessment_to_question(item: AssessmentItem) -> dict[str, Any]:
    correct = next(option for option in item.options if option.is_correct)
    return {
        "assessment_id": item.assessment_id,
        "objective_id": item.objective_id,
        "kind": item.kind,
        "question": item.stem,
        "options": [f"{option.option_id}. {option.text}" for option in item.options],
        "answer": correct.option_id,
        "explanation": correct.feedback,
        "options_meta": [option.model_dump(mode="json") for option in item.options],
        "difficulty": item.difficulty,
        "cognitive_action": item.cognitive_action,
        "source_ids": item.source_ids,
        "variant_of": item.variant_of,
        "generation_mode": item.generation_mode,
    }


def answer_feedback(item: AssessmentItem, selected: str) -> dict[str, Any]:
    letter = str(selected or "").strip()[:1].upper()
    chosen = next((option for option in item.options if option.option_id == letter), None)
    correct = next(option for option in item.options if option.is_correct)
    is_correct = chosen is not None and chosen.is_correct
    return {
        "selected_option": letter,
        "message": chosen.feedback if chosen else "请选择 A、B、C、D 中的一个选项。",
        "correction": correct.feedback,
        "misconception_code": chosen.misconception_code if chosen and not chosen.is_correct else None,
        "is_correct": is_correct,
    }


def verified_mastery(
    *,
    practice_assessment_id: str | None,
    practice_objective_id: str | None,
    practice_correct: bool,
    practice_validation_status: str | None,
    exit_assessment_id: str | None,
    exit_objective_id: str | None,
    exit_correct: bool,
    exit_validation_status: str | None,
) -> bool:
    return bool(
        practice_validation_status == "verified"
        and practice_correct
        and exit_validation_status == "verified"
        and exit_correct
        and practice_assessment_id
        and exit_assessment_id
        and practice_assessment_id != exit_assessment_id
        and practice_objective_id
        and practice_objective_id == exit_objective_id
    )
