# EduAgent AutoTutor 教学内容可信闭环 v1.35 Spec

**创建时间：** 2026-08-21
**分析基线：** `main@1d33652`
**状态：** Development Complete（Milestone 0–3，本地）· Release Validation Pending · 尚未标记 Implemented
**生产状态：** NOT_RUN；尚无真实 LLM、教师盲审、学生试用或 production canary 证据

## 实施快照（2026-08-21）

已完成的本地开发范围：

- 保留 `backend/agents/auto_tutor.py` 单一教学状态机和 Runtime v2 主链；
- 落地 objective/evidence/teaching/assessment/content validation 合同与 fail-closed 门禁；
- 建立 5 个 pilot 知识点的项目课程基线内容包、两套练习变体和独立退出票；
- practice 与 verified mastery 分层，只有有效练习和独立退出票均通过才写掌握证据；
- 学生页默认隐藏 trace 和内部策略，展示具体选项反馈、掌握层级与安全阻断；
- 效果统计按唯一会话计算完成率、verified mastery 和 blocked rate，保留 legacy 指标但不混算。

当前本地证据：

- `python3 eval/run_core_evals.py --quick --no-report`：56/57 suites passed，267/268 cases；唯一 skipped suite 为需要外部模型凭证的 `history_character_smoke`；
- AutoTutor trajectory：13/13；teaching quality：6/6；objective alignment：5/5；assessment validity：6/6；exit ticket independence：6/6；tutor effectiveness：9/9；
- false mastery、content blocked API、session recovery、question handoff、CAS/idempotency、Runtime v2 checkpoint/concurrency/resume 均通过本地 deterministic smoke；
- 前端 ESLint、21/21 unit tests、Next.js production build、3/3 AutoTutor Playwright 场景通过。

证据边界：

- 内容包的 `curriculum_reviewed` 是本项目课程基线工作流状态，不等同于第 13.2 节要求的独立历史教师盲审；教师盲审仍为 `NOT_RUN`；
- SQLite/既有 Runtime migration smoke 已通过；PostgreSQL migration smoke 为 `NOT_RUN`；
- 真实 LLM 样本、学生可理解性小样本、24 小时延迟保持、staging shadow、production canary 均为 `NOT_RUN`；
- 因完成定义第 6 项尚未满足，当前不能把 v1.35 标记为正式 `Implemented` 或发布完成。

## 1. 决策

v1.35 不扩展开放式规划、更多学科、语音交互或 Agent 委派。本轮只解决 AutoTutor 当前最严重的产品风险：

> 运行流程完成，不等于学生学会；没有通过内容有效性门禁的讲解和题目，不得生成掌握证据。

保留 `backend/agents/auto_tutor.py` 作为唯一教学状态机与执行源，在现有
`plan → act → observe → judge → reflect → re-plan → exit ticket → finalize`
主链中加入内容契约和强制门禁，不创建第二套 AutoTutor 执行链。

目标链路：

```text
学生画像 / 错题 / 聚焦知识点
  → 受控课时计划（1 个主目标 + 最多 1 个相关支持目标）
  → LearningObjective：entity + aspect + grade + misconception
  → 结构化检索
  → TeachingEvidenceGate
      ├─ sufficient：只使用 answer-bearing evidence
      └─ partial/none：补充已审定内容包或 content_blocked
  → TeachingContent 生成 + ContentValidator
  → AssessmentItem 生成 + AssessmentValidator
  → 学生作答
  → 基于选项语义和错因的反馈 / 重教
  → 与练习题不同的 exit ticket
  → MasteryEvidenceGate
      ├─ valid：写 verified mastery / weakpoint evidence
      └─ invalid：只记录过程，不改变掌握状态
```

## 2. 当前问题与复现证据

### 2.1 截图案例

目标知识点为“戊戌变法失败原因”，当前离线输出却存在三层错位：

1. 检索得到的是“戊戌变法的影响”，不是失败原因；
2. 讲解说明思想启蒙作用，没有回答失败原因；
3. 题目退化为固定占位选项：
   - `A. <知识点>的基本史实`
   - `B. 与史实不符的说法`
   - `C. 张冠李戴的说法`
   - `D. 完全无关的说法`

当前代码把 `ToolResult.ok=true` 且存在任意 sources 视为取材成功，但本次真实检索诊断为：

```json
{
  "query": "戊戌变法失败原因",
  "entity": "戊戌变法",
  "aspect": "cause",
  "retrieval_status": "partial",
  "source_count": 4,
  "answer_bearing_source_count": 0
}
```

随后选择练习题 A 和退出票 A，系统会得到：

```json
{
  "lesson_status": "mastered",
  "exit_ticket_passed": true,
  "mastery_rate": 100.0,
  "verified_content": false
}
```

这是 P0 数据正确性问题：无效内容可以污染错题本、复习计划、学生掌握度和教师端效果统计。

### 2.2 根因

| 环节 | 当前行为 | 风险 |
| --- | --- | --- |
| 计划 | 直接拼接错题、薄弱主题和近期主题，最多 4 项 | 一节课可能混入跨年级、跨时代且互不相关的主题 |
| 目标 | `knowledge_point` 是自由文本 | “戊戌变法失败原因”没有稳定拆成 entity=`戊戌变法`、aspect=`cause` |
| 取材 | 只看工具是否成功、sources 是否非空 | 忽略 `partial/none` 和 `answer_bearing_source_count=0` |
| 讲解 fallback | 直接使用第一条 snippet | 检索错维度时，讲解稳定跑题 |
| 出题 fallback | 固定 A/B/C/D 占位语句 | 题目不可用于形成性评价，正确答案恒为 A |
| 判分 | 只比较学生字母和答案字母 | 无法识别具体误区，也无法判断题目本身是否有效 |
| 掌握 | 一道题答对即把 step 标记为 mastered | 无效题也能产生掌握证据 |
| 退出票 | 复用同一个问题生成器 | 可能与练习题完全相同，不能证明迁移或保持 |
| 效果统计 | 聚合 `success` 事件 | 把流程成功误当学习有效 |

### 2.3 现有评测边界

当前离线聚焦评测可以全部通过：

- `auto_tutor_trajectory_eval`：11/11；
- `autotutor_teaching_quality_eval`：5/5；
- `tutor_effectiveness_smoke`：8/8。

这些结果分别证明状态机轨迹、基本文本结构和聚合计算正确，不证明：

- 教学目标与讲解维度一致；
- 题目真的考查目标知识；
- 正确选项能被来源支持；
- 干扰项对应真实误区；
- 退出票与练习题不同；
- 学生在延迟测试或迁移任务中仍然掌握。

## 3. 学生需求与产品目标

### 3.1 核心学生需求

1. **学对内容：** 讲解必须直接回答当前薄弱点，不混淆原因、结果、影响和意义。
2. **做有效题：** 学生必须依赖知识作答，不能通过选项措辞猜答案。
3. **获得具体反馈：** 答错后知道错在哪里，而不只是“再讲一遍”。
4. **负担可控：** 一节课聚焦少量相关目标，并明确本节要学会什么。
5. **掌握可信：** 只有经过独立检验的结果才改变错题本和掌握度。
6. **资料不足可感知：** 系统应诚实说明当前材料不足，不用占位内容假装完成。

### 3.2 v1.35 目标

- 每个教学步骤都有结构化 `LearningObjective`；
- 所有可评分题目至少绑定一条 answer-bearing evidence；
- 目标、讲解、题目和解析通过同一个 objective alignment gate；
- 禁止固定占位题进入学生界面；
- 无效题答对不得写入 mastered、correct streak 或 verified mastery；
- 练习题和退出票必须为不同 assessment item；
- 默认课时只包含 1 个主目标和最多 1 个相关支持目标；
- 学生界面默认隐藏 Agent Trace，突出目标、讲解、反馈和进度；
- 新增能够直接拦截截图案例的 deterministic eval。

### 3.3 非目标

- 重写为 LangGraph 或创建第二套 Runtime；
- 增加多 Agent 协作、Agent-as-tool 或动态 fan-out；
- 扩展到语文、数学、英语等新学科；
- 用真实 LLM 替代确定性内容门禁；
- 一次性补齐全部历史知识点；
- 把离线评测通过描述为真实学生学习增益。

## 4. 领域合同

建议新增 `backend/agents/autotutor_content.py`，只负责内容模型、生成和验证；会话推进仍由 `auto_tutor.py` 控制。

### 4.1 LearningObjective

复用 `backend/rag/history_query.py` 的 `HistoryQuery`、entity catalog 和 aspect 解析。

当前 `HistoryAspect` 没有 `purpose`，导致“洋务运动目的”只能退化为 fact 或与 cause 混用。v1.35 必须同步扩展：

```python
HistoryAspect = Literal[
    # existing values ...
    "purpose",
]
```

并在 `_ASPECT_TERMS`、`_ASPECT_QUERY_LABEL`、question type、aspect-compatible evidence terms 和评测数据中注册“目的/目标/意图”。`purpose` 不得与事件发生原因自动合并。

```python
class LearningObjective(BaseModel):
    schema_version: Literal[1] = 1
    objective_id: str
    raw_tag: str
    source_tag: str | None
    entity: str
    entity_id: str | None
    aspect: HistoryAspect
    question_type: HistoryQuestionType
    grade: str | None
    lesson: str | None
    target_outcome: str
    misconception_code: str | None = None
    confidence: float
    reason_codes: list[str] = []
```

规则：

- “戊戌变法失败原因”必须解析为 entity=`戊戌变法`、aspect=`cause`；
- `confidence < 0.8`、entity 缺失或 aspect=`unknown` 时不得直接生成可评分题；
- `source_tag` 保留原错题标签，用于兼容错题本写回；
- objective 进入 session state，后续讲解、题目、反馈和事件都引用同一 `objective_id`。

### 4.2 TeachingEvidenceDecision

```python
class TeachingEvidenceDecision(BaseModel):
    status: Literal["sufficient", "partial", "none"]
    objective_id: str
    source_ids: list[str] = []
    answer_bearing_source_ids: list[str] = []
    source_count: int = 0
    answer_bearing_source_count: int = 0
    entity_match: bool = False
    aspect_match: bool = False
    reason_codes: list[str] = []
```

门禁：

```text
可生成可评分教学内容 =
  objective.confidence >= 0.8
  AND evidence.status == sufficient
  AND evidence.entity_match
  AND evidence.aspect_match
  AND evidence.answer_bearing_source_count >= 1
```

`ToolResult.ok=true` 只表示工具调用成功，不等于教学证据充分。

### 4.3 TeachingContent

```python
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
```

要求：

- 只把 answer-bearing sources 传给生成器；
- 每条关键教学 claim 至少绑定一个 source ID；
- `cause` 目标的核心句必须解释原因，不能只有影响、意义或过程；
- fallback 不得拼接任意第一条 snippet；
- 禁止把“本轮采用的讲法是……”等运行策略当教学内容展示给学生；
- 示例必须帮助理解该目标，不得直接复述 strategy 字符串。

### 4.4 AssessmentItem

```python
class AssessmentOption(BaseModel):
    option_id: Literal["A", "B", "C", "D"]
    text: str
    is_correct: bool
    misconception_code: str | None = None
    feedback: str
    source_ids: list[str] = []

class AssessmentItem(BaseModel):
    schema_version: Literal[1] = 1
    assessment_id: str
    objective_id: str
    kind: Literal["practice", "exit_ticket"]
    stem: str
    options: list[AssessmentOption]
    difficulty: Difficulty
    cognitive_action: Literal["recall", "explain", "compare", "apply"]
    source_ids: list[str]
    variant_of: str | None = None
    generation_mode: Literal["curated", "llm", "deterministic_fallback"]
```

Assessment Validator 必须验证：

- 恰好四个、归一化后不重复的选项；
- 恰好一个正确选项；
- 正确选项和题目均能被绑定来源支持；
- stem 与 objective 的 entity/aspect 一致；
- 选项不得包含“基本史实”“与史实不符”“张冠李戴”“完全无关”等占位语句；
- 干扰项必须有明确误区或事实混淆来源；
- answer 不得因为生成失败默认回落到 A；
- 正确答案位置按稳定 seed 打散，并监控 A/B/C/D 分布；
- exit ticket 的 `assessment_id`、stem、选项集合必须与 practice 不同；
- exit ticket 至少提高一个认知动作或更换情境，不能只换措辞。

### 4.5 ContentValidation

```python
class ContentValidation(BaseModel):
    schema_version: Literal[1] = 1
    status: Literal["verified", "blocked"]
    objective_alignment: bool
    evidence_verified: bool
    assessment_valid: bool
    answer_unique: bool
    student_readable: bool
    reason_codes: list[str] = []
```

只有 `status=verified` 的 assessment 才能进入 `_judge()`。

## 5. 课时规划策略

### 5.1 默认课时范围

```text
默认：1 个主目标
可选：1 个相关支持目标
禁止：无关系的 3-4 个近期主题直接拼成一节课
```

主目标优先级：

1. URL/API 显式传入的 `focus_tags[0]`；
2. 最近作业错题；
3. 当前错题本最高权重知识点；
4. 学生明确选择的复习目标。

支持目标必须满足至少一项：

- 同一 entity 的相邻 aspect；
- 知识图谱中的直接 prerequisite；
- 同一教材 lesson；
- 经教师审核的易混淆对比项。

近期主题只能用于排序或选择相关支持目标，不能无条件加入课程。

### 5.2 聚焦案例

输入：

```json
{
  "focus_tags": ["戊戌变法失败原因"],
  "focus_reason": "概念模糊：把失败原因和历史影响混淆"
}
```

目标计划：

```json
{
  "primary_objective": "戊戌变法/cause",
  "support_objective": "戊戌变法/impact",
  "strategy": "先区分失败原因与历史影响，再分别检验",
  "max_minutes": 12
}
```

不得同时自动加入赤壁之战、洋务运动和长平之战。

## 6. 内容来源策略

### 6.1 来源顺序

1. `search_history_knowledge` 返回的 L1/L2 answer-bearing 教材证据；
2. 教研审核的 AutoTutor 内容包；
3. 证据不足，进入 `content_blocked`。

不得在可评分路径中使用“模型自有知识继续出题”。

### 6.2 教研内容包

建议新增：

```text
knowledge_base/history/autotutor_content.json
```

内容结构：

```json
{
  "objective_id": "history:戊戌变法:cause:v1",
  "entity": "戊戌变法",
  "aspect": "cause",
  "grade": "八年级上",
  "lesson": "第6课 戊戌变法",
  "claims": [],
  "key_points": [],
  "examples": [],
  "practice_items": [],
  "exit_ticket_items": [],
  "source_refs": [],
  "review_status": "teacher_reviewed",
  "reviewed_by": "teacher-or-editor-id",
  "content_version": "v1"
}
```

首批只覆盖 pilot 高频知识点，不追求全量：

- 戊戌变法失败原因；
- 洋务运动目的；
- 赤壁之战影响；
- 辛亥革命历史意义；
- 鸦片战争影响。

未审核条目不能作为 deterministic fallback。

## 7. 状态机和掌握证据

### 7.1 状态扩展

```python
StepStatus = Literal[
    "pending", "active", "practiced", "mastered", "struggling", "content_blocked"
]

SessionStatus = Literal["awaiting_answer", "needs_content", "completed"]
SessionPhase = Literal["lesson", "exit_ticket", "content_blocked", "completed"]
```

兼容规则：已有 session JSON 缺少新字段时按 legacy state 加载，不能自动补成 verified。

### 7.2 练习题答对

- practice 答对只把 step 标记为 `practiced`；
- 不立即调用 `record_correct_evidence()`；
- 保存 `practice_correct` 和 assessment ID；
- 答题反馈必须返回正确理由，以及学生所选项对应的解释。

### 7.3 练习题答错

反思输入必须包含：

- objective；
- 题干；
- 学生所选选项的文本和 `misconception_code`；
- 正确选项文本与依据；
- 历史 root cause；
- 当前教学内容与尝试次数。

不得仅凭“学生选 B、正确答案 A”诊断概念模糊、粗心或题目超纲。

### 7.4 退出票

- 只为主目标生成；
- 必须与 practice 使用不同 assessment ID；
- 必须通过同一 ContentValidation；
- 题目无效时进入 `needs_content`，不生成失败或成功掌握证据；
- 退出票通过后，主目标才能从 `practiced` 进入 `mastered`。

### 7.5 MasteryEvidenceGate

```text
verified_mastery =
  practice.content_validation == verified
  AND practice.is_correct
  AND exit_ticket.content_validation == verified
  AND exit_ticket.is_correct
  AND practice.assessment_id != exit_ticket.assessment_id
  AND objective_id 一致
```

只有 `verified_mastery=true` 时：

- 调用 `record_correct_evidence()`；
- 写 `auto_tutor_verified_mastery`；
- 更新教师端 verified mastery 指标；
- 允许从错题本累计移除证据。

内容阻断、生成失败和题目校验失败：

- 不记为学生答错；
- 不增加 wrong_count；
- 不增加 correct streak；
- 写 `auto_tutor_content_blocked`，供教研补内容。

## 8. API 合同

保留现有 API：

- `POST /api/autotutor/start`
- `POST /api/autotutor/answer`
- `GET /api/autotutor/session/{session_id}`
- `GET /api/autotutor/student/{student_id}/latest-session`

### 8.1 Start 请求

现有字段保持兼容，新增可选字段：

```json
{
  "student_id": "student-x",
  "grade": "八年级上册",
  "focus_tags": ["戊戌变法失败原因"],
  "focus_reason": "概念模糊：把原因与影响混淆",
  "lesson_id": "lesson-6",
  "max_minutes": 12,
  "idempotency_key": "autotutor:start:..."
}
```

`lesson_id/max_minutes` 均为可选；缺失时使用 session policy 默认值。

### 8.2 current_question

不泄露答案，但增加公开内容状态：

```json
{
  "kind": "practice",
  "assessment_id": "assessment_x",
  "objective": {
    "objective_id": "history:戊戌变法:cause:v1",
    "label": "戊戌变法失败原因"
  },
  "content_status": "verified",
  "evidence_label": "依据教材第6课与已审核辅导材料",
  "teaching": {},
  "question": "...",
  "options": ["A. ...", "B. ...", "C. ...", "D. ..."]
}
```

禁止向学生返回 source ID、内部 reason code、正确答案或系统 prompt。

### 8.3 Answer 响应

新增：

```json
{
  "last_answer_correct": false,
  "answer_feedback": {
    "selected_option": "B",
    "message": "你选择的是历史影响，不是失败原因。",
    "correction": "先区分直接原因和历史影响。",
    "misconception_code": "cause_impact_confusion"
  },
  "mastery": {
    "status": "not_yet_verified",
    "practice_verified": true,
    "exit_ticket_verified": false
  }
}
```

### 8.4 content_blocked 响应

```json
{
  "status": "needs_content",
  "phase": "content_blocked",
  "current_question": null,
  "content_blocked": {
    "objective_label": "戊戌变法失败原因",
    "message": "当前教材证据不足，暂不生成题目，也不会改变你的掌握记录。",
    "reason": "missing_answer_bearing_evidence",
    "suggested_actions": ["换一个相关知识点", "进入随问继续提问"]
  }
}
```

学生端只展示可理解 message；内部 reason 仅进 trace/admin response。

## 9. 前端交互

改动文件：`frontend/app/(student)/student/auto-tutor/page.tsx`。

### 9.1 默认学生视图

保留：

- 本节学习目标；
- 当前讲解；
- 有效练习；
- 答题反馈；
- “我有疑问 / 换个例子 / 讲简单一点”；
- 学习进度与退出票。

调整：

- 计划默认只显示主目标和相关支持目标；
- 正确作答后先展示解析，再进入下一步；
- 明确区分“练习答对”和“已验证掌握”；
- `content_blocked` 显示安全说明和下一步操作；
- 不显示 latency、Trace ID、工具状态和内部 Agent 术语。

### 9.2 Trace 可见性

Agent Trace 默认从学生页面隐藏，仅在以下条件显示：

```text
NODE_ENV == development AND query.debug == 1
```

生产教师/管理员诊断复用 AgentOps 或独立 debug 页面，不通过学生主界面展示。

## 10. 数据和指标

### 10.1 LearningEvent

新增事件：

- `auto_tutor_content_verified`
- `auto_tutor_content_blocked`
- `auto_tutor_practice_answered`
- `auto_tutor_exit_ticket_answered`
- `auto_tutor_verified_mastery`

事件 metadata 至少包含：

```json
{
  "objective_id": "history:戊戌变法:cause:v1",
  "aspect": "cause",
  "content_version": "v1",
  "assessment_id": "assessment_x",
  "assessment_kind": "practice",
  "content_validation_status": "verified",
  "mastery_eligible": true,
  "generation_mode": "curated"
}
```

不得写入完整题目、学生敏感内容、原始 prompt 或未经裁剪的教材正文。

### 10.2 效果统计

`backend/services/tutor_effectiveness_service.py` 分离：

- `practice_completion_rate`：过程指标；
- `practice_accuracy`：有效练习正确率；
- `verified_mastery_rate`：通过独立退出票的目标比例；
- `content_blocked_rate`：内容覆盖缺口；
- `false_mastery_count`：内容无效却写 mastery 的次数，必须为 0；
- `delayed_retention_rate`：24 小时或下次复习仍答对的比例。

legacy `auto_tutor_step.success` 只显示为 `legacy_practice_result`，不得合并进 verified mastery。

## 11. 实现切片

### 11.1 模块改动矩阵

| 文件 | 改动 |
| --- | --- |
| `backend/rag/history_query.py` | 新增 `purpose` aspect 及解析合同 |
| `backend/tools/history_search.py` | 补齐 purpose evidence 判定；继续输出 retrieval/answer-bearing 诊断 |
| `backend/agents/autotutor_content.py` | 新增 objective、teaching、assessment、validation 模型和纯函数 |
| `backend/agents/auto_tutor.py` | 在单一状态机中接入内容门禁、practiced/mastered 和 blocked 状态 |
| `backend/api/routers/learning.py` | 扩展 start 请求和公开响应，不新增第二套 endpoint |
| `backend/services/weakpoint_service.py` | 保持通用接口；AutoTutor 仅在 verified mastery 后调用一次 correct evidence |
| `backend/services/tutor_effectiveness_service.py` | 分离 legacy practice、有效练习和 verified mastery |
| `knowledge_base/history/autotutor_content.json` | 首批教研审定教学内容、练习题和退出票 |
| `frontend/app/(student)/student/auto-tutor/page.tsx` | 学生反馈、blocked 状态、掌握层级和默认隐藏 trace |
| `.env.example` | 登记 content gate 模式、BPS 和 kill switch |
| `eval/` | 增加 alignment、assessment、false mastery、API 和 E2E 评测 |

AutoTutor 状态主体存储在既有 `autotutor_sessions.state_json`，新增可选字段不要求新表。实现时仍须运行 SQLite/PostgreSQL migration smoke，确认旧 state JSON、status 字符串和索引兼容；如果最终引入独立教研审核表，必须另开 migration，不允许运行时自动建生产表。

### Milestone 0：失败用例与合同

- 新增 objective/content/assessment Pydantic 模型；
- 把截图案例固化为失败测试；
- 证明 `answer_bearing=0` 时当前链路会产生 false mastery；
- 不改变产品行为。

### Milestone 1：证据门禁和安全阻断

- AutoTutor 使用结构化 HistoryQuery；
- 读取 `retrieval_status/answer_bearing_source_count`；
- primary objective 证据不足时进入 `content_blocked`；
- 禁止占位题、禁止无效 mastery 写入；
- 保持现有 CAS、revision、idempotency 和 Runtime v2 milestone 合同。

### Milestone 2：审定内容与题目

- 建立首批 `autotutor_content.json`；
- 实现 TeachingContent/AssessmentItem validator；
- 生成带误区反馈的 practice 和独立 exit ticket；
- 正确答案位置稳定打散。

### Milestone 3：掌握模型与学生 UI

- practice correct 改为 `practiced`；
- 通过 exit ticket 后才写 verified mastery；
- 教师统计区分 practice 和 verified mastery；
- 学生页隐藏 trace，增加答案反馈和 content blocked 状态。

### Milestone 4：真实质量证据与灰度

- 真实 LLM 样本评测；
- 历史教师盲审；
- 学生可理解性小样本；
- staging shadow 与 production allowlist canary。

## 12. 评测设计

### 12.1 新增数据集

```text
eval/datasets/autotutor_content_alignment_cases.json
eval/datasets/autotutor_assessment_cases.json
```

首批 alignment cases：

| 输入 | entity | aspect | 预期 |
| --- | --- | --- | --- |
| 戊戌变法失败原因 | 戊戌变法 | cause | 影响材料不能通过原因门禁 |
| 洋务运动目的 | 洋务运动 | purpose | 讲解和题目必须回答目的 |
| 赤壁之战的影响 | 赤壁之战 | impact | 不得只讲经过 |
| 长平之战逐日行军路线 | 长平之战 | process | 当前资料不足，安全阻断 |
| 辛亥革命历史意义 | 辛亥革命 | significance | 讲解和题目绑定直接证据 |

### 12.2 新增评测

- `autotutor_objective_alignment_eval`
- `autotutor_assessment_validity_eval`
- `autotutor_false_mastery_smoke`
- `autotutor_content_blocked_api_smoke`
- `autotutor_exit_ticket_independence_eval`
- `autotutor_student_ui_e2e`

### 12.3 必须扩展的现有评测

`autotutor_teaching_quality_eval` 增加：

- entity/aspect alignment；
- teaching claim source binding；
- explanation 不得只命中其他 aspect；
- question validity；
- forbidden placeholder options；
- practice/exit ticket independence。

`auto_tutor_trajectory_eval` 增加：

- invalid content 不进入 `_judge`；
- content blocked 不写弱点和掌握；
- practice correct 只到 `practiced`；
- valid exit ticket 后才到 `mastered`；
- legacy session 能继续恢复但不标 verified。

## 13. 验收矩阵

### 13.1 P0 确定性验收

- [x] “戊戌变法失败原因”解析为 entity=`戊戌变法`、aspect=`cause`；
- [x] 仅有 impact 来源时返回 `content_blocked`；
- [x] `answer_bearing_source_count=0` 时不生成可评分题；
- [x] 学生界面永不出现四类占位选项；
- [x] 无效题选择 A 不会产生 mastered、correct streak 或 verified mastery；
- [x] practice 和 exit ticket 的 assessment ID 不同；
- [x] 练习答对后先展示解析，状态为 `practiced`；
- [x] 退出票通过后才写 verified mastery；
- [x] content blocked 不增加 wrong_count；
- [x] 同一 answer transition 的 CAS/idempotency 行为保持不变；
- [x] Runtime v2 checkpoint 不持久化答案和完整题目；
- [x] 旧 session JSON 可加载。

### 13.2 教师盲审

至少 50 条，覆盖 5 个 pilot 知识点、easy/medium/hard、practice/exit ticket。

| 指标 | 门槛 |
| --- | ---: |
| 目标—讲解一致率 | >=95% |
| 题目—目标一致率 | >=95% |
| 正确答案事实准确率 | 100% |
| 干扰项可解释率 | >=90% |
| 学生可理解性通过率 | >=90% |
| practice/exit 重复率 | 0% |
| false mastery | 0 |

### 13.3 学生小样本

不能用内部事件直接替代。至少记录：

- 讲解后即时正确率；
- exit ticket 正确率；
- 24 小时延迟保持率；
- “仍不理解”反馈率；
- 学生主动请求“讲简单/换例子”的比例；
- 退出率和单课完成时长。

学生样本不足时状态必须是 `NOT_RUN`，不能写“教学有效”。

## 14. 灰度与开关

新增：

```dotenv
EDU_AGENT_AUTOTUTOR_CONTENT_GATE_MODE=off
EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS=0
EDU_AGENT_AUTOTUTOR_CONTENT_GATE_KILL_SWITCH=false
```

模式：

- `off`：仅本地兼容旧逻辑；不能作为生产验证模式；
- `shadow`：记录门禁判断，但结果只计 practice，不写 verified mastery；
- `enforce`：内容无效时阻断题目和 mastery；
- kill switch：停止创建新的 AutoTutor 课程，已有课程可只读恢复或安全结束，不回退到占位题。

灰度顺序：

1. 本地 deterministic gate 100%；
2. staging `shadow=100%`，核对 reason code 和覆盖率；
3. staging `enforce=100%`；
4. production pilot allowlist；
5. 1% enforce，至少 100 个 verified assessments；
6. 10% enforce，连续 48 小时无 false mastery；
7. 100% 前完成教师盲审和内容覆盖门禁。

生产门禁：

| 指标 | 门槛 |
| --- | ---: |
| invalid assessment served | 0 |
| false mastery | 0 |
| graded assessment answer-bearing coverage | 100% |
| content blocked 写入 wrong/correct evidence | 0 |
| duplicate answer transition | 0 |
| unexpected failure rate | <=2% |
| p95 相对旧链路增加 | <=20% |

## 15. 回滚

内容门禁属于掌握数据安全边界，回滚不能恢复固定占位题和未验证 mastery。

推荐回滚：

```dotenv
EDU_AGENT_AUTOTUTOR_CONTENT_GATE_KILL_SWITCH=true
EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS=0
```

行为：

- 停止新课程；
- 保留 session/run/event/checkpoint；
- 已开始且内容已验证的题可以完成；
- 内容未验证的题不再评分，不写掌握证据；
- 不删除历史学习事件，legacy 事件在统计中标记为 unverified。

## 16. 完成定义

只有同时满足以下条件，v1.35 才能标记 Implemented：

1. P0 确定性验收全部通过；
2. 截图案例稳定进入有效教学或安全阻断，不能再产生占位题；
3. false mastery smoke 为 0；
4. 现有 AutoTutor trajectory、CAS、恢复、Runtime v2 测试无回归；
5. 前端 unit/build/Playwright 通过；
6. 教师盲审完成并达到门槛；
7. 真实 LLM 与生产 canary 未运行时，文档明确保留 `NOT_RUN`。

当前完成判断：第 1–5、7 项已有本地证据；第 6 项教师盲审为 `NOT_RUN`。因此代码开发切片完成，但 v1.35 尚不满足正式 `Implemented` 定义。
