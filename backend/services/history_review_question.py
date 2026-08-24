"""Curriculum-reviewed questions and release gates for student review."""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


CORPUS_PATH = Path(__file__).resolve().parents[2] / "knowledge_base" / "history" / "corpus.json"
QUALITY_CONTRACT_VERSION = 3
_LETTERS = "ABCD"
_PLACEHOLDER_MARKERS = ("选项一", "选项二", "选项三", "选项四", "暂无选项", "题目内容")
_LOW_QUALITY_MARKERS = (
    "完全由单一人物",
    "与当时的社会矛盾和时代背景无关",
    "教材没有提供任何",
    "没有产生任何历史影响",
    "与当时的社会背景完全无关",
    "直接建立了社会主义制度",
    "立即摆脱了半殖民地半封建社会",
    "彻底完成了反帝反封建的历史任务",
)
_HIDDEN_MATERIAL_REFERENCES = (
    "该材料", "材料中", "根据材料", "结合材料", "以上材料",
    "由此", "这些变化", "这最可能", "这最能说明",
)
_ASPECTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("历史意义", ("意义", "影响", "推动", "促进", "终结", "奠定")),
    ("意义", ("意义", "影响", "推动", "促进", "终结", "奠定")),
    ("影响", ("影响", "推动", "促进", "作用", "结果")),
    ("根本目的", ("根本目的", "目的", "旨在", "为了", "维护")),
    ("目的", ("根本目的", "目的", "旨在", "为了", "维护")),
    ("失败原因", ("失败", "原因", "由于", "因为", "局限")),
    ("原因", ("原因", "由于", "因为", "背景")),
    ("背景", ("背景", "局势", "形势", "由于")),
    ("主要内容", ("内容", "措施", "主张", "提出", "实行")),
    ("内容", ("内容", "措施", "主张", "提出", "实行")),
    ("措施", ("措施", "实行", "推行", "创办", "建立")),
    ("结果", ("结果", "最终", "失败", "胜利", "建立", "灭亡")),
    ("特点", ("特点", "特征", "性质")),
    ("评价", ("评价", "作用", "局限", "影响")),
)


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


@lru_cache(maxsize=2)
def _load_corpus(path: str = str(CORPUS_PATH)) -> tuple[dict[str, Any], ...]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ()
    if not isinstance(payload, list):
        return ()
    return tuple(row for row in payload if isinstance(row, dict))


def _split_tag(tag: str) -> tuple[str, str, tuple[str, ...]]:
    normalized = _compact(tag)
    for suffix, terms in _ASPECTS:
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            return normalized[: -len(suffix)], suffix, terms
    return normalized, "核心史实", ("是", "指", "发生", "建立", "实行", "提出", "影响")


def _row_search_text(row: dict[str, Any]) -> tuple[str, str]:
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    meta_text = " ".join(
        str(meta.get(key) or "")
        for key in ("topic", "event", "period", "lesson", "unit", "tags", "keywords", "entities")
    )
    return _compact(row.get("text")), _compact(meta_text)


def _best_corpus_row(tag: str, topic: str, aspect_terms: tuple[str, ...]) -> dict[str, Any] | None:
    compact_tag = _compact(tag)
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for row in _load_corpus():
        text, meta_text = _row_search_text(row)
        if topic not in text and topic not in meta_text:
            continue
        score = 0
        if compact_tag and compact_tag in meta_text:
            score += 30
        if topic in meta_text:
            score += 16
        if topic in text:
            score += 8
        for index, term in enumerate(aspect_terms):
            compact_term = _compact(term)
            if compact_term in meta_text:
                score += max(5, 18 - index * 2)
            if compact_term in text:
                score += max(4, 14 - index * 2)
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        if meta.get("meta_source") == "textbook_structured":
            score += 4
        if meta.get("type") in {"concept", "textbook"}:
            score += 3
        candidates.append((score, -len(text), row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _option_text(value: Any) -> str:
    return re.sub(r"^[A-Da-d][.、．]\s*", "", str(value or "").strip())


def _split_material_question(stem: str) -> tuple[str | None, str]:
    text = str(stem or "").strip()
    first, separator, rest = text.partition("。")
    if separator and len(first) >= 16 and len(rest.strip()) >= 8:
        return first + "。", rest.strip()
    for marker in ("这最能说明", "该材料最适合说明", "由此应怎样", "这些变化最能说明"):
        index = text.find(marker)
        if index >= 16:
            return text[:index].rstrip("，,；;。") + "。", text[index:]
    return None, text


def _curated_entry(tag: str):
    """Resolve the reviewed AutoTutor pack without importing its runtime state machine."""
    from agents.autotutor_content import build_learning_objective, find_curated_content, load_curated_content

    objective = build_learning_objective(tag)
    entry = find_curated_content(objective)
    if entry is not None:
        return entry
    compact_entity = _compact(objective.entity or tag)
    same_entity = [item for item in load_curated_content() if _compact(item.entity) == compact_entity]
    return same_entity[0] if len(same_entity) == 1 else None


def build_curated_review_question(
    tag: str,
    *,
    is_variant: bool = False,
    seed_question: dict[str, Any] | None = None,
    target_difficulty: str | None = None,
    selection_seed: str = "",
) -> dict[str, Any] | None:
    """Convert one curriculum-reviewed assessment into the review contract."""
    entry = _curated_entry(tag)
    if entry is None:
        return None
    practice = list(entry.practice_items)
    exit_items = list(entry.exit_ticket_items)
    if is_variant and target_difficulty != "easy":
        candidates = [*exit_items, *practice]
    else:
        candidates = practice
    if target_difficulty:
        matched = [item for item in candidates if item.difficulty == target_difficulty]
        if matched:
            candidates = matched
    previous_id = str((seed_question or {}).get("question_id") or "")
    fresh = [item for item in candidates if item.assessment_id != previous_id]
    if fresh:
        candidates = fresh
    if not candidates:
        return None

    def candidate_key(item: Any) -> tuple[int, int, int, str]:
        lengths = [len(_compact(option.text)) for option in item.options]
        balance = max(lengths) - min(lengths) if lengths else 999
        variant_priority = 0 if (is_variant and (item.kind == "exit_ticket" or item.variant_of)) else 1
        cognition_priority = 0 if item.cognitive_action in {"explain", "compare", "apply"} else 1
        digest = hashlib.sha256(f"{selection_seed}:{item.assessment_id}".encode("utf-8")).hexdigest()
        return variant_priority, cognition_priority, balance, digest

    source_label = entry.source_refs[0].label if entry.source_refs else entry.lesson
    for item in sorted(candidates, key=candidate_key):
        if is_variant and item.review_prompt and item.feedback_material:
            material = item.feedback_material.strip()
            question = item.review_prompt.strip()
            material_timing = "after_answer"
        else:
            material, question = _split_material_question(item.stem)
            material_timing = "before_answer" if material else None
        options = [f"{_LETTERS[index]}. {option.text}" for index, option in enumerate(item.options)]
        correct = next(option.option_id for option in item.options if option.is_correct)
        feedback = {option.option_id: option.feedback for option in item.options}
        result = {
            "question_id": item.assessment_id,
            "tag": str(tag or "").strip(),
            "material": material,
            "material_timing": material_timing,
            "question": question,
            "options": options,
            "answer": correct,
            "explanation": feedback[correct],
            "option_feedback": feedback,
            "difficulty": item.difficulty,
            "cognitive_action": item.cognitive_action,
            "lesson_label": entry.lesson,
            "source_label": source_label,
            "done": False,
            "correct": None,
            "is_variant": is_variant,
            "generation_source": "curriculum_reviewed",
            "quality_contract_version": QUALITY_CONTRACT_VERSION,
            "quality_status": "verified",
        }
        if not review_question_quality_reasons(result, require_variant=is_variant):
            return result
    return None


def review_question_quality_reasons(
    data: dict[str, Any] | None,
    *,
    require_variant: bool | None = None,
) -> list[str]:
    """Deterministic gate for student-facing junior-history choice questions."""
    if not isinstance(data, dict):
        return ["question_not_object"]
    reasons: list[str] = []
    question = str(data.get("question") or "").strip()
    options = data.get("options")
    answer = str(data.get("answer") or "").strip().upper()[:1]
    if not question or not isinstance(options, list) or len(options) != 4 or answer not in _LETTERS:
        return ["choice_structure_invalid"]
    normalized_options = [_option_text(option) for option in options]
    if not all(normalized_options):
        reasons.append("choice_option_empty")
    if len({_compact(option) for option in normalized_options}) != 4:
        reasons.append("choice_options_not_unique")
    combined = " ".join([question, str(data.get("material") or ""), *normalized_options])
    if any(marker in combined for marker in _PLACEHOLDER_MARKERS):
        reasons.append("placeholder_content")
    if any(marker in combined for marker in _LOW_QUALITY_MARKERS):
        reasons.append("implausible_distractor")
    correct_index = _LETTERS.index(answer)
    correct_length = len(_compact(normalized_options[correct_index]))
    distractor_lengths = [len(_compact(value)) for index, value in enumerate(normalized_options) if index != correct_index]
    if distractor_lengths and correct_length > max(distractor_lengths) + 14 and correct_length > min(distractor_lengths) * 1.8:
        reasons.append("answer_length_giveaway")
    variant_required = bool(data.get("is_variant")) if require_variant is None else require_variant
    if variant_required:
        if not data.get("is_variant"):
            reasons.append("variant_flag_missing")
        if len(str(data.get("material") or "").strip()) < 16:
            reasons.append("variant_material_missing")
        if data.get("material_timing") != "after_answer":
            reasons.append("variant_material_timing_invalid")
        if any(marker in question for marker in _HIDDEN_MATERIAL_REFERENCES):
            reasons.append("question_depends_on_hidden_material")
        if str(data.get("cognitive_action") or "") not in {"explain", "compare", "apply"}:
            reasons.append("variant_cognitive_level_too_low")
    if str(data.get("difficulty") or "") not in {"easy", "medium", "hard"}:
        reasons.append("difficulty_missing")
    if str(data.get("cognitive_action") or "") not in {"recall", "explain", "compare", "apply"}:
        reasons.append("cognitive_action_missing")
    return list(dict.fromkeys(reasons))


def is_usable_choice_question(data: dict[str, Any] | None) -> bool:
    return not review_question_quality_reasons(data)


def public_review_question(task: dict[str, Any], *, reveal_answer: bool = False) -> dict[str, Any]:
    """Hide answer-bearing fields until the server has judged the submission."""
    allowed = {
        "question_id", "tag", "question", "options", "difficulty", "material_timing",
        "cognitive_action", "lesson_label", "source_label", "done", "correct",
        "is_variant", "generation_source", "quality_contract_version", "quality_status",
        "adaptive_message", "pending_generate", "blocked_message",
    }
    public = {key: value for key, value in task.items() if key in allowed}
    if task.get("material_timing") == "before_answer":
        public["material"] = task.get("material")
    if reveal_answer:
        public.update({
            "material": task.get("material"),
            "answer": task.get("answer"),
            "explanation": task.get("explanation"),
            "selected_feedback": task.get("selected_feedback"),
        })
    return public


def blocked_review_question(tag: str, reason: str) -> dict[str, Any]:
    return {
        "tag": str(tag or "历史知识点").strip() or "历史知识点",
        "question": "",
        "options": [],
        "answer": "",
        "explanation": "",
        "done": False,
        "correct": None,
        "pending_generate": True,
        "quality_contract_version": QUALITY_CONTRACT_VERSION,
        "quality_status": "blocked",
        "blocked_reason": reason,
        "blocked_message": "当前缺少达到练习标准的可靠题目，本题不会计入掌握结果。",
    }


def build_grounded_review_question(
    tag: str,
    *,
    is_variant: bool = False,
    seed_question: dict[str, Any] | None = None,
    target_difficulty: str | None = None,
    selection_seed: str = "",
) -> dict[str, Any]:
    normalized_tag = str(tag or "历史知识点").strip() or "历史知识点"
    curated = build_curated_review_question(
        normalized_tag,
        is_variant=is_variant,
        seed_question=seed_question,
        target_difficulty=target_difficulty,
        selection_seed=selection_seed,
    )
    if curated is not None:
        return curated
    topic, aspect, aspect_terms = _split_tag(normalized_tag)
    row = _best_corpus_row(normalized_tag, topic, aspect_terms)
    if row is None:
        return blocked_review_question(normalized_tag, "reviewed_content_missing")
    # A corpus paragraph can support generation, but it cannot by itself prove
    # that three synthetic distractors are historically valid. Fail closed
    # instead of shipping the old generic/absurd-option fallback.
    return blocked_review_question(normalized_tag, "reviewed_assessment_missing")
