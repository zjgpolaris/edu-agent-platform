"""AI 出题结构质检（确定性，不调用 LLM）。

对 AI 生成的题目做可机检的结构校验，把问题在教师审阅前显式标注出来。
只做确定性检查（选项数量、答案合法性、题干为空等）；语义质检（歧义、
答案是否真的正确）留给教师人工判断或后续 LLM 质检。

用法：
    from services.question_quality import check_question, summarize_quality
    q["quality"] = check_question(q)
"""
from __future__ import annotations

from typing import Any

OBJECTIVE_CHOICE = "single_choice"
_MIN_PROMPT_LEN = 6
_VALID_TF_ANSWERS = {"正确", "错误"}


def _norm(v: Any) -> str:
    return str(v or "").strip()


def check_question(q: dict[str, Any]) -> dict[str, Any]:
    """校验一道题，返回 {"level": ok|warn|error, "issues": [...]}.

    level 取所有 issue 中的最高级别：有 error → error；仅 warn → warn；无 → ok。
    """
    errors: list[str] = []
    warns: list[str] = []

    q_type = _norm(q.get("type")) or OBJECTIVE_CHOICE
    prompt = _norm(q.get("prompt"))

    # ── 通用：题干 ──────────────────────────────────────────────
    if not prompt:
        errors.append("题干为空")
    elif len(prompt) < _MIN_PROMPT_LEN:
        warns.append("题干过短，可能不完整")

    # ── 单选题 ──────────────────────────────────────────────────
    if q_type == "single_choice":
        options = [_norm(o) for o in (q.get("options") or [])]
        non_empty = [o for o in options if o]
        if len(non_empty) != 4:
            errors.append(f"选项应为 4 个，当前 {len(non_empty)} 个")
        if len(non_empty) != len(set(non_empty)):
            warns.append("存在重复选项")
        answer = _norm(q.get("answer")).upper()[:1]
        valid_letters = [chr(65 + i) for i in range(len(non_empty))]
        if answer not in {"A", "B", "C", "D"} or (valid_letters and answer not in valid_letters):
            errors.append("正确答案字母无效")

    # ── 判断题 ──────────────────────────────────────────────────
    elif q_type == "true_false":
        if _norm(q.get("answer")) not in _VALID_TF_ANSWERS:
            errors.append("判断题答案必须是「正确」或「错误」")

    # ── 简答题 ──────────────────────────────────────────────────
    elif q_type == "subjective":
        ref = _norm(q.get("reference_answer")) or _norm(q.get("explanation"))
        if not ref:
            warns.append("缺少参考答案要点")

    level = "error" if errors else ("warn" if warns else "ok")
    return {"level": level, "issues": errors + warns}


def summarize_quality(questions: list[dict[str, Any]]) -> dict[str, int]:
    """统计一批题目的质检结果（题目需已带 quality，否则现场计算）。"""
    error_count = 0
    warn_count = 0
    for q in questions:
        quality = q.get("quality") if isinstance(q.get("quality"), dict) else check_question(q)
        level = quality.get("level")
        if level == "error":
            error_count += 1
        elif level == "warn":
            warn_count += 1
    return {"error_count": error_count, "warn_count": warn_count}


# --------------------------------------------------------------------------- #
# LLM 语义质检（可选，结构质检之上的第二层）
# --------------------------------------------------------------------------- #
_LEVEL_RANK = {"ok": 0, "warn": 1, "error": 2}


def check_question_semantic(q: dict[str, Any], *, llm: Any = None, bad_examples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """用 LLM 判定题目的语义问题（歧义、答案是否自洽/正确、干扰项是否合理）。

    - opt-in：仅在调用方显式传入 llm 时才跑；无 llm 或调用失败 → 降级为
      {"level": "ok", "issues": [], "checked": False}（不误报、不阻断）。
    - checked=False 表示未真正跑 LLM，用于区分"查过且无问题"与"没查"。
    - bad_examples：该教师历史上人工判定为『题目有问题』的样例，作为 few-shot
      反例注入 prompt，帮助模型识别同类问题（自改进闭环）。为空则行为不变。
    """
    if llm is None:
        return {"level": "ok", "issues": [], "checked": False}

    q_type = _norm(q.get("type")) or OBJECTIVE_CHOICE
    prompt_text = _norm(q.get("prompt"))
    options = [_norm(o) for o in (q.get("options") or []) if _norm(o)]
    answer = _norm(q.get("answer"))
    ref = _norm(q.get("reference_answer")) or _norm(q.get("explanation"))

    if q_type == "single_choice":
        focus = "检查：标注的正确答案是否真的正确、是否存在多个正确或无正确选项、干扰项是否明显不合理、题干是否有歧义。"
        body = f"题干：{prompt_text}\n选项：{options}\n标注正确答案：{answer}"
    elif q_type == "true_false":
        focus = "检查：陈述句与标注答案（正确/错误）是否自洽、陈述是否有歧义。"
        body = f"陈述：{prompt_text}\n标注答案：{answer}"
    else:
        focus = "检查：题干是否可作答、是否有歧义、参考答案要点是否对应题干。"
        body = f"题干：{prompt_text}\n参考答案要点：{ref or '（无）'}"

    try:
        from pydantic import BaseModel as _BM
        from structured_output import invoke_structured

        class _SemanticVerdict(_BM):
            has_issue: bool
            severity: str = "warn"   # warn | error
            issues: list[str] = []

        fewshot = ""
        for ex in (bad_examples or [])[:3]:
            ex_prompt = _norm(ex.get("prompt"))[:80]
            if not ex_prompt:
                continue
            ex_note = _norm(ex.get("note"))
            fewshot += f"\n- 题干：{ex_prompt}" + (f"（问题：{ex_note[:40]}）" if ex_note else "")
        fewshot_block = (
            "\n以下是该教师此前人工判定为『题目有问题』的样例，供参考其易错模式"
            "（不要照搬内容，只借鉴问题类型）：" + fewshot
        ) if fewshot else ""

        messages = [
            {"role": "system", "content": (
                "你是初中历史命题审校专家。判断给定题目在语义上是否有问题。"
                f"{fewshot_block}\n"
                f"{focus}\n"
                "只输出 JSON：{\"has_issue\":false,\"severity\":\"warn\",\"issues\":[\"简短中文问题描述\"]}。"
                "若无问题，has_issue=false 且 issues 为空。severity 仅 warn 或 error（答案本身错误用 error）。"
            )},
            {"role": "user", "content": body},
        ]
        verdict = invoke_structured(llm, messages, model=_SemanticVerdict, fallback=None)
    except Exception:
        verdict = None

    if verdict is None:
        return {"level": "ok", "issues": [], "checked": False}
    if not verdict.has_issue or not verdict.issues:
        return {"level": "ok", "issues": [], "checked": True}
    level = "error" if _norm(verdict.severity) == "error" else "warn"
    return {"level": level, "issues": [i.strip() for i in verdict.issues if i.strip()], "checked": True}


def merge_quality(structural: dict[str, Any], semantic: dict[str, Any]) -> dict[str, Any]:
    """合并结构质检与语义质检结果：level 取较高，语义 issue 加「语义：」前缀。"""
    issues = list(structural.get("issues") or [])
    issues += [f"语义：{i}" for i in (semantic.get("issues") or [])]
    level = max(
        (structural.get("level", "ok"), semantic.get("level", "ok")),
        key=lambda lv: _LEVEL_RANK.get(lv, 0),
    )
    merged: dict[str, Any] = {"level": level, "issues": issues}
    if "checked" in semantic:
        merged["semantic_checked"] = bool(semantic["checked"])
    return merged
