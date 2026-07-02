# AI 出题 LLM 语义质检开发文档

**创建日期：** 2026-07-02 18:10
**目标：** 在 P2 确定性结构质检之上加一层可选的 LLM 语义质检，把结构规则查不到的语义问题（答案是否自洽、题干歧义、干扰项合理性）在教师审阅前标出。

---

## 一、背景

P2 的 `check_question` 只做确定性结构校验（选项数、答案字母合法、题干空）。"题好不好"的关键在语义层，结构规则查不了。本轮加**可选**的 LLM 语义质检，opt-in、可降级、结果并入同一 `quality` 字段（前端徽标无需改）。

---

## 二、后端 `services/question_quality.py`

- `check_question_semantic(q, *, llm=None) -> {level, issues, checked}`：
  - `llm=None` → 降级 `{"level":"ok","issues":[],"checked":False}`（不误报）。
  - 按题型给不同侧重 prompt（单选：答案是否真对/多对/无对、干扰项、歧义；判断：陈述与 answer 是否自洽；简答：可答性、参考答案对应）。
  - 用 `invoke_structured` + `_SemanticVerdict{has_issue,severity,issues}`；解析失败/异常 → `checked=False` 降级。
  - `checked` 区分"查过无问题"与"没查"。
- `merge_quality(structural, semantic)`：issues 合并（语义条目加「语义：」前缀），level 取两者最高（error>warn>ok），带 `semantic_checked`。

## 三、后端 `api/main.py`

- `GenerateQuestionsRequest.semantic_check: bool = False`。
- `_with_quality`：结构质检照旧；`semantic_check=True` 时对每题追加 `check_question_semantic(..., llm=llm_fast)` 并 `merge_quality`，失败降级为仅结构。
- 语义质检是阻塞 LLM 调用 → `_gen_one` 三个分支的 `_with_quality` 改为 `await run_in_threadpool(_with_quality, ...)`，避免堵塞事件循环；仍走原 `asyncio.gather` 并发。

## 四、前端 `(teacher)/teacher/assignments/page.tsx`

- AI 出题区加「深度质检（AI 复核题目语义，较慢）」勾选框（`aiSemantic` state），请求体带 `semantic_check`。
- 徽标渲染无需改（issues 已含「语义：」条目）。CSS `.tasg-ai-semantic`。

## 五、测试

`eval/question_quality_smoke.py` 10→15 例：新增 `_StubLLM`（离线返回预置 JSON），用例覆盖——无 llm 降级 checked=False、检出 error、无问题 ok、merge 取最高 level 且加前缀、双清 ok。

回归：assignment_smoke 12/12、build 52/52。

---

## 六、后续
1. 语义质检可缓存（同题重复生成不重复调用）。
2. 教师改题 diff 记录，作为出题/质检微调数据。
3. 语义质检可扩展到"知识点对齐度"（题目是否真考该知识点）。
