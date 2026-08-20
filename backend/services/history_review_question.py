"""Grounded deterministic questions for the student review flow.

The review page must remain answerable when the external model is unavailable.
This module builds one conservative multiple-choice question from the local
history corpus instead of exposing an unusable placeholder to students.
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


CORPUS_PATH = Path(__file__).resolve().parents[2] / "knowledge_base" / "history" / "corpus.json"
_LETTERS = "ABCD"
_PLACEHOLDER_MARKERS = ("选项一", "选项二", "选项三", "选项四", "暂无选项", "题目内容")
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


def _clean_sentence(value: str, max_chars: int = 110) -> str:
    text = re.sub(r"\s+", " ", value).strip(" ，,；;。")
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    if len(text) <= max_chars:
        return text
    shortened = text[:max_chars]
    boundary = max(shortened.rfind("，"), shortened.rfind("；"), shortened.rfind("。"))
    return shortened[:boundary].strip(" ，,；;。") if boundary >= max_chars // 2 else shortened.rstrip(" ，,；;。")


def _extract_claim(row: dict[str, Any], topic: str, aspect: str, aspect_terms: tuple[str, ...]) -> str:
    text = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    if aspect in {"目的", "根本目的"}:
        match = re.search(r"(?:根本)?目的(?:是|在于)([^，。；]+)", text)
        if match:
            return _clean_sentence(match.group(1), 70)
        match = re.search(r"旨在[“\"]?([^，。；”\"]+)", text)
        if match:
            return _clean_sentence(match.group(1), 70)

    sentences = [part.strip() for part in re.split(r"(?<=[。！？；])", text) if part.strip()]
    ranked: list[tuple[int, int, str]] = []
    for sentence in sentences:
        compact_sentence = _compact(sentence)
        score = (8 if topic in compact_sentence else 0) + sum(
            3 for term in aspect_terms if _compact(term) in compact_sentence
        )
        ranked.append((score, -len(sentence), sentence))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return _clean_sentence(ranked[0][2] if ranked else text)


def _question_text(topic: str, aspect: str, *, is_variant: bool) -> str:
    prefix = "换一个角度思考：" if is_variant else ""
    if aspect in {"目的", "根本目的"}:
        return f"{prefix}根据教材，{topic}的根本目的是什么？"
    if aspect in {"历史意义", "意义", "影响"}:
        return f"{prefix}下列哪一项准确概括了{topic}的{aspect}？"
    if aspect in {"原因", "失败原因", "背景"}:
        return f"{prefix}下列哪一项符合教材对{topic}{aspect}的说明？"
    if aspect in {"主要内容", "内容", "措施"}:
        return f"{prefix}下列哪一项属于{topic}的{aspect}？"
    if aspect == "结果":
        return f"{prefix}{topic}产生了怎样的结果？"
    return f"{prefix}下列哪一项是教材对{topic}的准确表述？"


def _distractors(topic: str, aspect: str) -> list[str]:
    if aspect in {"目的", "根本目的"}:
        return [
            "推翻清政府并建立资产阶级共和国",
            "彻底完成反帝反封建的历史任务",
            "建立社会主义制度并消灭封建土地制度",
        ]
    if aspect in {"历史意义", "意义", "影响"}:
        return [
            "使中国立即摆脱了半殖民地半封建社会",
            "彻底完成了反帝反封建的历史任务",
            "直接建立了社会主义制度",
        ]
    if aspect in {"原因", "失败原因", "背景"}:
        return [
            "完全由单一人物的个人意愿决定",
            "与当时的社会矛盾和时代背景无关",
            "教材没有提供任何可以判断的历史条件",
        ]
    if aspect in {"主要内容", "内容", "措施"}:
        return [
            f"彻底否定并停止与{topic}有关的一切活动",
            "把其他历史时期的制度直接照搬到当时",
            "只提出口号，没有采取任何实际措施",
        ]
    return [
        f"{topic}没有产生任何历史影响",
        f"{topic}与当时的社会背景完全无关",
        "把不同历史时期的事件混为一谈",
    ]


def _rotate_options(tag: str, correct: str, distractors: list[str], seed: str = "") -> tuple[list[str], str]:
    offset = hashlib.sha256(f"{tag}|{seed}".encode("utf-8")).digest()[0] % 4
    values = distractors[:3]
    values.insert(offset, correct)
    options = [f"{_LETTERS[index]}. {value}" for index, value in enumerate(values)]
    return options, _LETTERS[offset]


def is_usable_choice_question(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return False
    question = str(data.get("question") or "").strip()
    options = data.get("options")
    answer = str(data.get("answer") or "").strip().upper()[:1]
    if not question or not isinstance(options, list) or len(options) != 4 or answer not in _LETTERS:
        return False
    combined = question + " " + " ".join(str(option) for option in options)
    return all(str(option).strip() for option in options) and not any(marker in combined for marker in _PLACEHOLDER_MARKERS)


def build_grounded_review_question(
    tag: str,
    *,
    is_variant: bool = False,
    seed_question: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_tag = str(tag or "历史知识点").strip() or "历史知识点"
    topic, aspect, aspect_terms = _split_tag(normalized_tag)
    row = _best_corpus_row(normalized_tag, topic, aspect_terms)
    if row:
        claim = _extract_claim(row, topic, aspect, aspect_terms)
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        source = str(meta.get("source") or "本地历史教材语料")
        generation_source = "trusted_corpus"
    else:
        claim = f"应依据教材中的人物、事件、原因和影响来核对“{normalized_tag}”"
        source = "复习方法"
        generation_source = "study_strategy"
        aspect = "核心史实"

    seed = str((seed_question or {}).get("question") or "")
    options, answer = _rotate_options(normalized_tag, claim, _distractors(topic, aspect), seed)
    return {
        "tag": normalized_tag,
        "question": _question_text(topic, aspect, is_variant=is_variant),
        "options": options,
        "answer": answer,
        "explanation": f"教材依据：{claim}。来源：{source}。",
        "done": False,
        "correct": None,
        "is_variant": is_variant,
        "generation_source": generation_source,
    }
