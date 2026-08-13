#!/usr/bin/env python3
"""Generate reviewed, deterministic v1.29 learning-assistant eval datasets."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "eval" / "datasets"


def _split(index: int) -> str:
    marker = index % 10
    return "train" if marker < 6 else "dev" if marker < 8 else "test"


def _case(case_id: str, message: str, intent: str, index: int, **extra) -> dict:
    request = {"message": message, "grade": extra.pop("grade", "八年级上册")}
    for key in ("book_id", "lesson_id", "conversation_history", "source_context"):
        if key in extra:
            request[key] = extra.pop(key)
    return {
        "id": case_id,
        "source": "generated_reviewed",
        "split": _split(index),
        "request": request,
        "expected_intents": extra.pop("expected_intents", [intent]),
        "expected_primary_intent": intent,
        **extra,
    }


def build_intent_cases() -> list[dict]:
    groups: list[tuple[str, int, list[str]]] = [
        ("character_recommendation", 40, [
            "推荐一个能讲汉代的历史人物", "我想和历史人物聊聊三国", "给我推荐一位唐朝人物", "我适合和谁聊宋代历史",
            "推荐人物帮助我理解秦朝", "想找一个历史人物对话", "人物推荐：明朝", "谁适合讲清楚清朝改革",
        ]),
        ("timeline_game", 40, [
            "来一局历史时间线游戏", "开始时间排序小游戏", "玩一局中国近代史时间线", "我想玩历史排序",
            "开启时间巨轮", "用闯关游戏复习历史时间", "来一局唐朝时间线", "开始历史时间排序",
        ]),
        ("quiz_generation", 50, [
            "帮我出 3 道练习题", "针对鸦片战争来五道选择题", "给我一套历史小测", "考考我洋务运动",
            "围绕辛亥革命来几道题目", "生成两道简答题", "我想刷题复习五四运动", "出一道关于秦朝的题",
            "给我来三道选择题", "生成本课练习题",
        ]),
        ("review_plan", 45, [
            "帮我制定复习计划", "我最近错得很多，安排一下复习", "给我一些复习建议", "今天应该怎么复习",
            "按薄弱点生成学习计划", "帮我排接下来三天的复习", "我该如何复习历史", "根据错题安排复习",
            "制定今天的复习安排",
        ]),
        ("history_search", 60, [
            "鸦片战争为什么爆发", "辛亥革命有什么意义", "商鞅变法带来了哪些影响", "五四运动是怎么发生的",
            "洋务运动为什么失败", "甲午战争的结果是什么", "科举制度是怎样发展的", "安史之乱造成什么影响",
            "秦始皇为什么统一文字", "唐朝为什么会出现贞观之治", "抗日战争胜利的原因", "戊戌变法为什么失败",
        ]),
        ("textbook_qa", 30, [
            "这节课讲了什么", "这一课的重点是什么", "总结一下本课", "课文有哪些易错点", "教材这一课为什么重要", "本课主要内容是什么",
        ]),
        ("chat", 25, [
            "你好", "谢谢你", "今天天气怎么样", "你是谁", "再见", "现在几点", "讲个笑话", "你能做什么",
        ]),
        ("memory_delete_demo", 10, [
            "演示高风险工具，删除演示记忆", "删除 demo memory", "确认删除演示记忆", "删除demomemory",
        ]),
    ]
    cases: list[dict] = []
    global_index = 0
    suffixes = ["", "。", "，请说简单点", "，适合八年级", "，现在开始"]
    for intent, total, bases in groups:
        for index in range(total):
            base = bases[index % len(bases)]
            message = base + suffixes[(index // len(bases)) % len(suffixes)]
            kwargs = {}
            if intent == "textbook_qa" and index % 2 == 0:
                kwargs.update(book_id="history-grade-8a", lesson_id="lesson-1", expected_clarification=False)
            elif intent == "textbook_qa":
                kwargs.update(expected_clarification=True)
            if intent == "quiz_generation":
                if "3 道" in message or "三道" in message:
                    kwargs["expected_slots"] = {"count": 3}
                elif "五道" in message:
                    kwargs["expected_slots"] = {"count": 5, "question_type": "choice"}
                elif "两道" in message:
                    kwargs["expected_slots"] = {"count": 2, "question_type": "short_answer"}
            cases.append(_case(f"intent_{intent}_{index + 1:03d}", message, intent, global_index, **kwargs))
            global_index += 1
    assert len(cases) == 300
    return cases


def build_composition_cases() -> list[dict]:
    topics = ["洋务运动", "鸦片战争", "辛亥革命", "五四运动", "商鞅变法", "甲午战争"]
    forms = [
        "先简单解释{topic}，再给我出 3 道选择题",
        "先讲讲{topic}为什么重要，然后来两道简答题",
        "解释一下{topic}，接着给我几道练习题",
        "先说明{topic}的影响，再出一道题目考考我",
        "用简单的话讲{topic}，之后生成 5 道选择题",
    ]
    cases = []
    for index in range(30):
        message = forms[index % len(forms)].format(topic=topics[index % len(topics)])
        count = 3 if "3 道" in message else 2 if "两道" in message else 1 if "一道" in message else 5 if "5 道" in message else 3
        cases.append(_case(
            f"composition_{index + 1:03d}", message, "history_search", index,
            expected_intents=["history_search", "quiz_generation"],
            expected_slots={"count": count},
            expected_plan_operations=["search_history_knowledge", "answer_from_sources", "quiz_from_sources"],
        ))
    return cases


def build_clarification_cases() -> list[dict]:
    forms = [
        "这节课讲了什么", "这一课重点是什么", "总结一下本课", "课文哪里最容易考", "教材这课为什么重要",
    ]
    cases = []
    for index in range(25):
        cases.append(_case(
            f"clarification_{index + 1:03d}", forms[index % len(forms)] + ("？" if index % 2 else ""), "textbook_qa", index,
            expected_clarification=True,
            expected_missing_slots=["book_id", "lesson_id"],
        ))
    return cases


def main() -> None:
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "learning_assistant_intent_cases.json": build_intent_cases(),
        "learning_assistant_composition_cases.json": build_composition_cases(),
        "learning_assistant_clarification_cases.json": build_clarification_cases(),
    }
    for name, cases in outputs.items():
        (DATASET_DIR / name).write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{name}={len(cases)}")


if __name__ == "__main__":
    main()
