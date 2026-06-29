from textbook_learning.schema import SummaryMode, TextbookLessonResponse

ACTION_QUESTIONS = {
    "explain": "请解释这个知识点。",
    "importance": "为什么这个知识点重要？",
    "exam": "这个知识点容易怎么考？",
}

SUMMARY_TITLES: dict[SummaryMode, str] = {
    "overview": "本课概要",
    "exam_points": "考点梳理",
    "mistakes": "易错提醒",
    "compare": "对比归纳",
}

SUMMARY_INSTRUCTIONS: dict[SummaryMode, str] = {
    "overview": "用 4—6 条概括本课核心内容，并给出一个学习提醒。",
    "exam_points": "按中考/课堂检测思路列出重点、关键词和常见问法。",
    "mistakes": "列出容易混淆、容易漏记或容易因果倒置的地方，并说明纠正方法。",
    "compare": "找出本课内容中适合对比记忆的对象，用表格或条目说明差异。",
}


def lesson_context(lesson: TextbookLessonResponse) -> str:
    lines = [
        f"教材：{lesson.grade} · {lesson.book}",
        f"单元：{lesson.unit_title}",
        f"课程：{lesson.lesson_title}",
        "知识点：",
    ]
    for item in lesson.items:
        lines.append(f"- [{item.id}] {item.topic}（{item.type}，约第 {item.page} 页）：{item.text}")
    return "\n".join(lines)


def ask_messages(
    lesson: TextbookLessonResponse,
    question: str,
    selected_text: str | None,
    item_text: str | None,
    sources_context: str,
    history: list[dict],
) -> list[dict]:
    user_parts = [f"学生问题：{question}"]
    if selected_text:
        user_parts.append(f"学生选中的内容：{selected_text}")
    if item_text:
        user_parts.append(f"当前知识点：{item_text}")
    if sources_context:
        user_parts.append(f"可参考的检索材料：\n{sources_context}")
    user_parts.append(f"当前课程学习文档：\n{lesson_context(lesson)}")

    return [
        {
            "role": "system",
            "content": (
                "你是初中历史 AI 学习助手。当前材料是教材同步知识点学习文档，不是教材原文或 PDF 原文。"
                "回答要面向初中生，准确、简洁、分层，必要时提醒以课堂教材和老师讲解为准。"
                "不要编造页码或史料来源；如果依据不足，明确说明。"
            ),
        },
        *history[-8:],
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def summary_messages(lesson: TextbookLessonResponse, mode: SummaryMode) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "你是初中历史 AI 学习助手。请基于教材同步知识点学习文档生成学习辅助内容，"
                "不要把材料称为教材原文。输出中文，结构清晰，适合课后复习。"
            ),
        },
        {
            "role": "user",
            "content": f"请生成《{lesson.lesson_title}》的{SUMMARY_TITLES[mode]}。要求：{SUMMARY_INSTRUCTIONS[mode]}\n\n{lesson_context(lesson)}",
        },
    ]


def quiz_messages(lesson: TextbookLessonResponse, question_types: list[str], count: int, focus_text: str | None) -> list[dict]:
    focus = f"\n重点围绕：{focus_text}" if focus_text else ""
    return [
        {
            "role": "system",
            "content": (
                "你是初中历史测验出题助手。只基于给定的教材同步知识点学习文档出题。"
                "优先返回严格 JSON，不要使用 Markdown 代码块。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"请为《{lesson.lesson_title}》生成 {count} 道自测题，题型从 {', '.join(question_types)} 中选择。{focus}\n"
                "返回 JSON：{\"questions\":[{\"id\":\"q1\",\"type\":\"single_choice\",\"question\":\"...\","
                "\"options\":[\"A...\",\"B...\"],\"answer\":\"...\",\"explanation\":\"...\",\"source_item_ids\":[\"lesson-1-item-1\"]}]}。\n\n"
                f"{lesson_context(lesson)}"
            ),
        },
    ]
