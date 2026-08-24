# EduAgent AutoTutor 学生安全交接与事务化自适应闭环 v1.36 Spec

**创建时间：** 2026-08-24
**分析基线：** `main@abb5e2e`
**状态：** Development Complete（local deterministic）· Release Validation Pending
**生产状态：** NOT_RUN；尚无真实 PostgreSQL migration、真实 LLM、教师盲审、学生试用、staging 或 production canary 证据
**实施基线：** `main@abb5e2e` 起开发；工作区尚未提交

## 0. 证据边界

本 Spec 最初来自 `main@abb5e2e` 的实时代码链路检查和受控故障复现；本节同时记录 2026-08-24 的本地实施结果，不把本地 deterministic 通过等同于生产证明。

当前已确认：

- AutoTutor 仍以 `backend/agents/auto_tutor.py` 为唯一教学状态机和业务执行源；
- v1.35 的 objective、内容门禁、有效练习和独立退出票合同已在代码中存在；
- 答题入口已有 session revision、CAS、inflight idempotency claim 和 response replay；
- Runtime v2 已有 run、event、artifact、checkpoint、side-effect ledger、policy 和 capability registry；
- 当前 Runtime v2 开关默认关闭，且本机部署 schema readiness 不能作为生产就绪证据；
- 既有本地专项评测结果只能证明确定性合同，没有真实学生学习增益证据。

当前基线证据快照：

- 本轮 pre-Spec AutoTutor/Runtime 针对性 deterministic 评测：16/16 suites、39/39 cases；
- 最近一次跨 Agent 产品专项评测：5/5 suites、6/6 cases；
- v1.35 已提交文档记录的 full quick gate：56/57 suites、267/268 cases，唯一 skip 为依赖外部模型凭证的 `history_character_smoke`；该 full quick gate 本轮仅作为既有基线引用，尚未针对 v1.36 重新运行；
- 上述结果不覆盖本文三个新失败合同，不能作为 v1.36 通过证据。

2026-08-24 本地实施结果：

- 已实现 AutoTutor → 随问的显式 public DTO，并在 assistant session 写入和读取两端执行 allowlist 裁剪；
- 已实现按真实 difficulty、已用 assessment ID 和 cognitive action 选择题目，五个 pilot objective 均补齐 remedial item；
- 已实现 answer transition 内 learning events、weakpoint evidence、review memory、可选 Runtime side effect 与 session CAS 的单事务提交；
- 已实现同 key 同 payload replay、同 key 不同 payload conflict、并发提交和五个事务故障点 rollback；
- 已将非 tool capability 的 step kind、side effect、risk 和 timeout 设为权威 binding 合同；
- 已新增 migration `009` 并完成 SQLite upgrade/downgrade/legacy NULL/index/readiness 覆盖；
- 已通过 `python3 eval/run_core_evals.py --quick --no-report`：61/62 suites、278/279 cases；唯一 skip 为依赖外部模型凭证的既有 `history_character_smoke`；
- 已通过 frontend lint、7 files / 21 tests、Next.js production build，以及 AutoTutor Playwright 2/2。

仍为 `NOT_RUN`：真实 PostgreSQL migration/concurrency、真实 LLM、教师盲审、学生试用、staging fault injection、production canary 和学习效果保持评测。因此当前只能标记为 `Development Complete（local deterministic）`，不能标记为正式生产 `Implemented`。

## 1. 决策

v1.36 不扩展新 Agent、新学科、动态多 Agent 编排或第二套 AutoTutor 链路。本轮只完成一条学生可验证的纵向闭环：

```text
审定内容与学生当前状态
  → 按目标难度选择真实匹配的新题
  → 学生作答
  → 纯函数判定、反思和重规划
  → 暂存 AnswerTransitionEffects
  → 同一个数据库事务
      ├─ 校验 session revision + inflight idempotency key
      ├─ 幂等写 learning events
      ├─ 幂等应用 weakpoint/mastery evidence
      ├─ 幂等 upsert review memory
      └─ CAS 完成 session + 保存 replay response
  → 返回学生安全响应
  → 可选进入随问时，只持久化公开教学上下文
```

核心原则：

> 界面显示的难度必须等于学生实际作答题目的难度；一次答题的业务副作用必须全部提交一次或全部不提交；跨功能交接只能传递学生需要的教学信息。

Runtime v2 继续承担运行治理和审计，但不能替代业务数据库的 exactly-once 合同。即使 Runtime v2 rollout 为 `0 BPS`，AutoTutor 的学生数据仍必须安全。

## 2. 当前问题与实时复现

### 2.1 AutoTutor → 随问交接泄露内部教学字段

当前调用链：

```text
POST /api/learning/assistant/sessions
  → get_learning_assistant_context(source_session_id)
  → 仅 pop student_id
  → assistant_sessions.context_json
  → create/get/resume API 原样返回 context
```

`get_learning_assistant_context()` 当前返回 `strategy` 和完整 `teaching`。`TeachingContent` 包含 `claims[].source_ids`，因此虽然直接题目答案已被删除，以下内部字段仍可跨边界持久化和返回：

- 教学 strategy / rationale；
- claims；
- source IDs；
- 未来新增在 teaching 对象中的内部字段。

既有 `autotutor_question_handoff_smoke` 只检查答案字段，没有递归检查 strategy、claims 和 source IDs，因而会产生“测试通过但公开合同仍不安全”的假阴性。

受控复现“戊戌变法失败原因”时，context 顶层包含 `strategy`、`teaching`，且 `teaching.claims[].source_ids` 可见。

### 2.2 “降低难度”没有约束实际选题

当前链路：

```text
reflect/re-plan 修改 LessonStep.difficulty
  → prepare_content(..., variant_index=attempts)
  → pool[variant_index % len(pool)]
  → 返回 AssessmentItem 自己声明的 difficulty
```

选题只按变体序号轮转，不接收目标难度，也不排除已作答题目。受控复现“洋务运动目的”时：

```json
{
  "initial_plan_difficulty": "medium",
  "initial_assessment_difficulty": "easy",
  "reflection_adjustment": "reteach",
  "replanned_step_difficulty": "easy",
  "new_assessment_difficulty": "medium",
  "new_cognitive_action": "compare"
}
```

即系统文字上“降低难度”，实际却给出更难题。当前五个 pilot objective 中，除“戊戌变法失败原因”外，其余 objective 的 practice pool 均缺少第二道 easy remedial item；因此不能只改 selector，还必须补齐内容覆盖。

### 2.3 session CAS 不能保证教学副作用 exactly-once

当前答题入口先 `_claim_answer_transition()`，但退出链路按以下顺序执行：

```text
judge exit ticket
  → _finalize()
      ├─ record learning events
      ├─ record_correct_evidence / record_weakpoint
      └─ record_typed_memory
  → _complete_answer_transition() CAS session
```

上述写入分别开启数据库连接；若副作用已成功、但 session CAS 前进程失败，恢复或重试会再次执行副作用。`learning_events` 每次生成新 UUID；`record_weakpoint()` 会累加 `wrong_count`；`record_correct_evidence()` 会累加 streak。

受控故障恢复模拟重复执行同一 pre-finalize state 后得到：

```json
{
  "duplicate_exit_ticket_events": 2,
  "duplicate_answered_events": 2,
  "weakpoint_wrong_count": 2
}
```

`_autotutor_side_effect_ledger()` 只是从最终 state 合成“committed”记录，无法证明真实写入仅发生一次；Runtime plan 还把 `auto_tutor.finalize` 声明为 `side_effect="none"`，与业务事实不一致。

## 3. 学生需求与产品目标

### 3.1 学生需求

1. **隐私和可理解性：** 随问只看到当前知识点、讲解和问题，不看到 Agent 策略、推理、来源内部 ID 或答案。
2. **真实适配：** 点击“讲简单一点”或答错后触发降难度，下一题必须是新的、实际不更难的题。
3. **结果可信：** 刷新、超时、并发提交或服务恢复不能重复增加错题次数、掌握证据和统计事件。
4. **安全失败：** 没有合适的新题时明确进入“内容待补充”，不能用更难题假装完成适配。
5. **连续学习：** 从 AutoTutor 进入随问后保留足够的教学上下文，但不暴露开发和治理信息。

### 3.2 v1.36 目标

- 建立 AutoTutor handoff 的显式 public DTO，并在写入和读取边界双重裁剪；
- 所有公开 context 递归禁止 strategy、rationale、claims、source IDs、answer 和 runtime trace；
- 选题由 `target_difficulty`、历史 assessment IDs 和认知动作共同约束；
- `LessonStep.difficulty == current AssessmentItem.difficulty` 始终成立；
- 每个 pilot objective 至少有两道可用于 easy remediation 的不同 practice item；
- 无合适新题时进入 `needs_content/content_blocked`，不评分、不改变 mastery；
- practice、exit ticket 和 finalize 的持久化副作用都纳入 answer transition exactly-once 合同；
- Runtime capability/policy 能正确声明和拒绝非 tool 写副作用错配；
- 固化当前三个失败复现为 deterministic eval。

### 3.3 非目标

- AutoTutor LangGraph 重写或新增第二套状态机；
- 新增开放式 Agent 规划、Agent-as-tool、动态 fan-out 或多 Agent 委派；
- 扩展五个 pilot objective 之外的全量历史内容；
- 改造历史人物、辩论、作文、地图、推荐和游戏的产品 Runtime 合同；
- 本轮完成 queued worker、跨实例 job recovery、全平台 budget enforcement 或 artifact purge；
- 用 deterministic eval 替代教师盲审、真实 LLM、学生样本和延迟保持评测；
- 在没有 PostgreSQL 和 canary 证据时宣称生产 exactly-once。

## 4. 目标架构

保持 `auto_tutor.py` 为唯一状态机，只新增领域纯函数和持久化服务：

```text
auto_tutor.py
  ├─ plan/act/observe/judge/reflect/re-plan（既有单一状态机）
  ├─ select_assessment()                （纯函数）
  ├─ build_answer_transition()          （纯函数，更新内存 state）
  └─ commit_autotutor_transition()      （单一事务边界）
        ├─ learning_events(effect_key)
        ├─ student_profiles / event-derived memory（仅首次 event）
        ├─ weakpoint_evidence(evidence_key)
        ├─ weakpoints aggregate
        ├─ typed memory deterministic upsert
        └─ autotutor_sessions CAS/replay
```

公开交接为独立的序列化边界，不复制教学执行逻辑：

```text
AutoTutorState
  → build_public_assistant_context()
  → sanitize_public_assistant_context()
  → assistant_sessions.context_json
  → sanitize_public_assistant_context() again
  → API response / prompt source context
```

## 5. 学生公开交接合同

### 5.1 Public DTO

建议在 `backend/agents/autotutor_public.py` 定义：

```python
class PublicTeachingContext(BaseModel):
    explanation: str
    key_points: list[str] = []
    example: str | None = None

class AutoTutorAssistantContextPublic(BaseModel):
    schema_version: Literal[1] = 1
    autotutor_session_id: str
    phase: Literal["lesson", "exit_ticket", "content_blocked", "completed"]
    knowledge_point: str
    difficulty: Difficulty
    teaching: PublicTeachingContext | None = None
    question: str | None = None
    return_path: Literal["/student/auto-tutor"] = "/student/auto-tutor"
```

只允许：

- `schema_version`；
- `autotutor_session_id`；
- `phase`；
- `knowledge_point`；
- 实际选中 assessment 的 `difficulty`；
- `teaching.explanation/key_points/example`；
- 不含选项、答案和解析的 `question` 文本；
- 固定 `return_path`。

递归禁止：

```text
student_id, strategy, rationale, reason, reason_codes,
claims, source_id, source_ids, sources,
answer, correct, correct_answer, is_correct,
options, feedback, misconception_code,
trace, trace_id, runtime, run_id, steps,
prompt, tool_result, side_effect_ledger
```

禁止合同按字段语义和嵌套路径执行，不能只在顶层 `pop()`。

### 5.2 双边界裁剪

写入边界：

- `learning_assistant_create_session` 在鉴权完成后只把 public DTO 交给 `create_session()`；
- `create_session()` 对 `source_feature="auto_tutor"` 再执行一次模型校验和 `extra="forbid"`；
- `student_id` 只存储在 `assistant_sessions.student_id` 列，不进入 `context_json`。

读取边界：

- `_session()`、`get_session()`、`get_latest_session()` 和 active source resume 都对 legacy `context_json` 重新裁剪；
- 旧记录即使包含内部字段，也不得通过 create/get/resume API 返回；
- 本轮不要求批量回填旧行；可在安全读取后异步/惰性重写，但响应必须先安全；
- 学习助手 `_source_context_text` 只能读取 public DTO，不得依赖被删除字段。

### 5.3 兼容行为

- direct AutoTutor API 的既有公开响应保持字段兼容；
- handoff context `schema_version=1` 为新增字段；前端应忽略未知公开字段；
- legacy standalone assistant session 不套用 AutoTutor DTO，但继续执行通用敏感字段裁剪；
- 缺少必需公开字段的 legacy AutoTutor context 返回最小安全 context，而不是原样透传。

## 6. 自适应选题合同

### 6.1 难度顺序

```python
DIFFICULTY_RANK = {"easy": 0, "medium": 1, "hard": 2}
COGNITIVE_RANK = {"recall": 0, "explain": 1, "compare": 2, "apply": 3}
```

`LessonStep.difficulty` 不再是展示建议，而是当前题目的强合同。每次 `prepare_content()` 完成后必须执行：

```text
step.difficulty == prepared.assessment.difficulty
public current_question.difficulty == prepared.assessment.difficulty
handoff context.difficulty == prepared.assessment.difficulty
```

### 6.2 Selector

在 `autotutor_content.py` 新增纯函数：

```python
def select_assessment(
    pool: list[AssessmentItem],
    *,
    kind: Literal["practice", "exit_ticket"],
    target_difficulty: Difficulty,
    excluded_assessment_ids: set[str],
    preferred_cognitive_actions: list[CognitiveAction],
    seed: str,
) -> AssessmentSelection:
    ...
```

`AssessmentSelection` 至少包含：

```python
class AssessmentSelection(BaseModel):
    status: Literal["selected", "blocked"]
    assessment: AssessmentItem | None = None
    target_difficulty: Difficulty
    reason_codes: list[str] = []
```

选择规则：

1. 排除本 session 已出现的 `assessment_id`；
2. 只选择 kind、objective 和 content validation 均匹配的题；
3. 正常首次出题优先精确命中 target difficulty；
4. `reteach/lower_difficulty` 后，`new difficulty rank <= previous difficulty rank`；
5. remediation 优先 `recall/explain`，认知动作不得无说明地提高；
6. 候选同级时使用稳定 seed 排序，重试和恢复得到同一选择；
7. 不允许“没有 easy 就回退 medium/hard”；
8. 没有合适且未使用的题时返回 `blocked`。

### 6.3 重教不变量

触发 `reteach` 或 `lower_difficulty` 后必须同时满足：

```text
new_assessment_id != previous_assessment_id
rank(new_assessment.difficulty) <= rank(previous_assessment.difficulty)
new_assessment.objective_id == current_objective.objective_id
new_assessment.content_validation.status == verified
```

不满足时：

- step 进入 `content_blocked`；
- session 进入 `needs_content`；
- 返回学生可理解提示和 `reason_code=no_fresh_remedial_item`；
- 不进入 `_judge()`；
- 不写答错、weakpoint、correct streak 或 mastery；
- 可写一次幂等的 `auto_tutor_content_blocked` 过程事件。

### 6.4 Pilot 内容覆盖

`knowledge_base/history/autotutor_content.json` 的五个 pilot objective 均必须至少包含：

- 两道不同的 easy practice/remedial item；
- assessment ID、stem 和选项集合互不重复；
- 至少一题为 `recall` 或 `explain`；
- 既有 medium practice 可保留，用于正常进阶；
- exit ticket 继续独立，至少为 `medium/apply`，不得被 remediation selector 使用。

新增内容仍必须通过 v1.35 的 objective/evidence/assessment/content gate；仅补数量不能视为有效。

## 7. Answer Transition exactly-once 合同

### 7.1 纯状态与副作用意图

`_judge()`、`_reflect_and_replan()` 和 `_finalize()` 不再直接写数据库。它们生成更新后的 state、公开 response 和副作用意图：

```python
class LearningEventIntent(BaseModel):
    effect_key: str
    event: LearningEvent

class WeakpointEvidenceIntent(BaseModel):
    evidence_key: str
    student_id: str
    knowledge_tag: str
    evidence_type: Literal["wrong", "verified_correct"]
    source_feature: Literal["auto_tutor"] = "auto_tutor"
    source_session_id: str
    assessment_id: str

class AutoTutorTransitionEffects(BaseModel):
    contract_version: Literal[2] = 2
    session_id: str
    claimed_revision: int
    idempotency_key: str
    learning_events: list[LearningEventIntent] = []
    weakpoint_evidence: list[WeakpointEvidenceIntent] = []
    review_memory: dict | None = None
```

practice answer、exit-ticket answer、verified mastery、content blocked 和 finalize 均通过同一 transition 提交器落库。

### 7.2 唯一事务提交

新增 `backend/services/autotutor_transition_service.py`：

```python
def commit_autotutor_transition(
    *,
    previous_revision: int,
    idempotency_key: str,
    next_state: AutoTutorState,
    response: dict[str, Any],
    effects: AutoTutorTransitionEffects,
) -> TransitionCommitResult:
    ...
```

同一个 `get_connection()` 事务内按顺序执行：

1. `SELECT` session 并验证 `revision`、`inflight_idempotency_key` 和 student ID；
2. 若 `last_idempotency_key` 相同，直接返回 `last_response_json`；
3. 以 `effect_key` 幂等插入 learning events；
4. 只有 learning event 首次插入时才更新 `student_profiles` 和该事件派生的 memory；
5. 以 `evidence_key` 幂等插入 weakpoint evidence；
6. 只有 evidence 首次插入时才更新 weakpoints aggregate；
7. 使用稳定 memory entry ID 幂等 upsert review memory；
8. CAS 更新 `autotutor_sessions.state_json/revision/status/last_response_json` 并清理 inflight claim；
9. transaction commit 后才更新进程内 `_store` 并返回 response。

任一步异常必须整体 rollback。禁止提交一部分副作用后再调用独立 session CAS。

### 7.3 确定性 effect key

```text
learning event:
autotutor:{session_id}:revision:{claimed_revision}:{event_type}:{assessment_id_or_step}

weakpoint evidence:
autotutor:{session_id}:revision:{claimed_revision}:weakpoint:{evidence_type}:{assessment_id}

review memory:
autotutor:{session_id}:review_goal:v2
```

相同业务事实必须生成相同 key；不同事件不得共享 key。key 不包含答案文本、学生敏感内容、prompt 或随机 UUID。

### 7.4 并发、故障与 replay

- 同 idempotency key 顺序或并发提交只允许一个事务产生业务变更；
- 同 key 同 payload 返回已保存 response；
- 同 key 不同 answer/payload 返回 409 `idempotency_payload_conflict`；
- 同 key 的旧 revision 先按 payload 判定 replay/conflict；其他 stale revision 保持既有兼容响应并标记 `stale_answer_ignored`，不触发任何 effect；
- 故障发生在任意 effect 和 session CAS 之间时，数据库应保持零部分写入；
- transaction commit 成功但 HTTP response 丢失时，重试返回 `last_response_json`；
- inflight claim 超时恢复不得盲目重放未确认副作用；应根据 session/effect key 判断 committed、retryable 或 conflict；
- `_fail_answer_transition()` 不得用“revision+1 且 retryable=false”掩盖可安全回滚的事务失败。

### 7.5 连接复用

以下底层函数增加可选的现有 connection/transaction 参数，或拆出 `_with_conn` 内部实现：

- learning event insert；
- student profile update 和 event-derived memory upsert；
- weakpoint evidence insert 与 aggregate update；
- correct evidence update；
- typed memory upsert；
- session CAS/replay。

transition service 内禁止调用会自行开启并提交新连接的高层 helper。

## 8. Migration 009

新增：

```text
backend/alembic/versions/009_autotutor_transition_effects.py
```

### 8.1 learning_events.effect_key

```sql
ALTER TABLE learning_events ADD COLUMN effect_key TEXT NULL;
CREATE UNIQUE INDEX uq_learning_events_effect_key
  ON learning_events(effect_key);
```

规则：

- legacy event 的 `effect_key=NULL`，不做强制数据回填；
- 新 AutoTutor transition event 必须非空；
- 其他 feature 可继续为空，后续单独迁移；
- PostgreSQL 和 SQLite 都必须验证多个 NULL legacy 行可共存。

### 8.2 weakpoint_evidence

```sql
CREATE TABLE weakpoint_evidence (
  evidence_key TEXT PRIMARY KEY,
  student_id TEXT NOT NULL,
  knowledge_tag TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  source_feature TEXT NOT NULL,
  source_session_id TEXT,
  assessment_id TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_weakpoint_evidence_student_tag_created
  ON weakpoint_evidence(student_id, knowledge_tag, created_at);
```

只有 `INSERT weakpoint_evidence` 首次成功时才允许改变 `weakpoints.wrong_count/correct_streak`。`weakpoints` 仍是查询聚合表，`weakpoint_evidence` 是幂等事实账本。

### 8.3 Schema 与部署要求

- 同步更新 `backend/db/schema.py`；
- 本地 `ensure_tables()` 只用于开发兼容，不能替代 Alembic；
- readiness 的目标 revision 从 `008` 更新为 `009`；
- migration 必须验证 `008 → 009 → downgrade 008 → upgrade 009`；
- downgrade 前若存在 effect 数据，必须明确记录数据丢失风险，生产默认不执行 downgrade；
- 完成真实 PostgreSQL migration smoke 前，release 状态保持 `NOT_RUN`。

## 9. Runtime v2 对齐

### 9.1 CapabilityBinding

为非 tool capability 增加权威合同：

```python
class CapabilityBinding(BaseModel):
    # existing fields ...
    side_effect: Literal[
        "none", "read", "write", "session_create", "external_call"
    ] = "none"
    risk_level: Literal["low", "medium", "high"] = "low"
    default_timeout_seconds: int
```

- tool binding 继续从 `ToolSpec` 获取 side effect、risk 和 timeout；
- function/generation/subgraph 也必须显式声明，不再由 plan 任意填写；
- binding 直接显式声明 `step_kind`，允许同为 function 的 critic 使用 `verification`、finalize 使用 `control`；tool binding 强制为 `tool`；
- 既有非 AutoTutor binding 在本轮只补与当前行为一致的声明，不改变业务流程。

`auto_tutor.finalize` 必须声明：

```json
{
  "operation": "auto_tutor.finalize",
  "kind": "function",
  "side_effect": "write",
  "risk_level": "medium",
  "durability_mode": "resumable"
}
```

对应 `AgentStep` 必须带稳定 idempotency key。

### 9.2 Policy

`validate_plan_policy()` 对每个 step 校验：

- kind 与 binding 一致；
- side effect 与 binding 一致；
- risk level 与 binding 一致；
- timeout 与 binding 一致；
- write step 存在非空 idempotency key；
- budget 仍按既有 max steps/tool/LLM 合同执行。

任何错配必须在执行前 fail closed。

### 9.3 Side-effect ledger

- 删除 `_autotutor_side_effect_ledger()` 的事后合成真相；
- Runtime active 时，ledger 记录真实 transition effect key 和最终 commit status；
- checkpoint 中只保留 effect 引用和裁剪后的状态，不保留题目答案、完整教学 claims 或学生原始输入；
- Runtime inactive 时不要求创建 run/ledger，但业务 effect key 和事务合同照常工作；
- Runtime ledger 与业务表发生不一致时，业务表为学生数据真相，readiness/AgentOps 报警而不是自动重复执行。

## 10. API 与学生界面合同

### 10.1 既有 API

不新增第二套 endpoint：

- `POST /api/autotutor/start`
- `POST /api/autotutor/answer`
- `GET /api/autotutor/session/{session_id}`
- `GET /api/autotutor/student/{student_id}/latest-session`
- `POST /api/learning/assistant/sessions`
- `GET /api/learning/assistant/sessions/{session_id}`

### 10.2 AutoTutor response

公开 `current_question` 增加/校准：

```json
{
  "assessment_id": "westernization-purpose-practice-3",
  "difficulty": "easy",
  "cognitive_action": "explain",
  "adaptation": {
    "type": "lower_difficulty",
    "student_message": "换一道更基础的新题，先确认核心概念。"
  }
}
```

不得返回 selector reason、候选池、内部 rank、正确答案、misconception code 或完整策略。

### 10.3 needs_content

```json
{
  "status": "needs_content",
  "phase": "content_blocked",
  "content_blocked": {
    "code": "no_fresh_remedial_item",
    "message": "当前没有合适的新练习题，本次不会计入掌握结果。"
  }
}
```

前端：

- 不再显示可提交的旧题；
- 提供“进入随问”和“返回今日学习”；
- 不展示 Agent、trace、策略或开发 reason code；
- 刷新后保持 blocked 状态，不重复写事件。

## 11. 实现切片

### Milestone 0：失败测试与合同

- 固化 handoff 内部字段泄露；
- 固化“降难度后实际题更难”；
- 固化 finalize 故障导致 event/weakpoint 重复；
- 新增 public DTO、selection 和 effects Pydantic 模型；
- 此阶段不改变产品行为。

### Milestone 1：公开交接安全

- 实现 AutoTutor public context allowlist；
- create/get/latest/resume 写读双裁剪；
- legacy context 安全读取；
- 学习助手仅消费公开教学字段；
- handoff API 和前端网络响应 forbidden fields 为 0。

### Milestone 2：真实自适应选题

- selector 接收 target difficulty、历史题和认知动作；
- 补齐五个 pilot objective 的 easy remediation 内容；
- 状态、题目和公开 UI 难度强一致；
- 无新题时 fail closed；
- v1.35 内容门禁和 exit-ticket independence 无回归。

### Milestone 3：事务化 answer transition

- migration 009；
- 纯 effects builder；
- learning event、weakpoint evidence、memory 和 session CAS 同事务；
- 顺序、并发、故障和 response-loss replay 测试；
- 移除事后合成 ledger。

### Milestone 4：Runtime 合同与本地发布门禁

- 非 tool capability side-effect/risk/timeout 校验；
- AutoTutor finalize 声明 write + idempotency；
- schema readiness 目标更新为 009；
- 本地全量回归、frontend unit/build/Playwright；
- 生成可复核的 per-suite 和 per-case 报告。

### Milestone 5：外部验证与灰度

- 真实 PostgreSQL migration smoke；
- 真实 LLM 样本；
- 历史教师盲审；
- staging fault injection / shadow；
- production pilot allowlist/canary；
- 学生小样本和延迟保持。

## 12. 模块改动矩阵

| 文件 | 计划改动 |
| --- | --- |
| `backend/agents/autotutor_public.py` | 新增 public handoff DTO 和递归 allowlist sanitizer |
| `backend/agents/autotutor_content.py` | 新增 difficulty-aware selector、selection contract 和验证 |
| `backend/agents/auto_tutor.py` | 接入 selector、effects builder、事务提交；移除直接 finalize 写入和合成 ledger |
| `backend/services/autotutor_transition_service.py` | 新增单事务 answer transition 提交器 |
| `backend/services/learning_assistant_session_service.py` | AutoTutor context 写读双裁剪和 legacy 安全读取 |
| `backend/api/routers/learning.py` | 使用 public DTO；保持 owner/student 鉴权与 API 兼容 |
| `backend/student_profile.py` | learning event 支持 effect key 和现有 transaction |
| `backend/services/weakpoint_service.py` | evidence ledger、幂等 aggregate 和现有 transaction |
| `backend/user_memory.py`、`backend/student_profile.py` | review memory 复用事务和现有稳定 memory ID upsert |
| `backend/agent_runtime/capability_registry.py` | 非 tool side-effect/risk/timeout 权威声明 |
| `backend/agent_runtime/policy.py` | 所有 step 强校验，write step 强制 idempotency |
| `backend/db/schema.py` | `learning_events.effect_key`、`weakpoint_evidence` schema |
| `backend/alembic/versions/009_autotutor_transition_effects.py` | migration 009 |
| `knowledge_base/history/autotutor_content.json` | 五个 pilot objective 的 easy remediation 内容 |
| `frontend/app/(student)/student/auto-tutor/page.tsx` | 展示真实难度、适配提示和 fail-closed 状态 |
| `eval/` | 新增 handoff、adaptive difficulty、transaction、fault injection、policy 和 migration 评测 |

矩阵中的持久化服务只复用既有 `student_profile.py` / `user_memory.py` 业务实现，不授权创建重复的 memory 执行链。

## 13. 评测设计

### 13.1 新增专项评测

`autotutor_handoff_public_contract_smoke`：

- create/get/latest/resume 全路径；
- lesson、exit ticket、blocked、completed phase；
- legacy raw context 注入 strategy/claims/source IDs/answers/trace；
- 递归 forbidden-key 扫描为 0；
- 学习助手仍能基于公开 explanation 回答。

`autotutor_adaptive_difficulty_eval`：

- 覆盖五个 pilot objective；
- 初始 step/assessment/public difficulty 一致；
- 答错触发 reteach/lower difficulty；
- 新 assessment ID 不同；
- difficulty rank 不增加；
- remediation cognitive action 符合约束；
- 人为移除候选时进入 needs_content，mastery/weakpoint 不变。

`autotutor_transition_idempotency_smoke`：

- practice、exit ticket、verified mastery、failed exit ticket；
- 同 key 顺序 replay；
- 同 key 并发 replay；
- 同 key 不同 payload conflict；
- 每个 effect key、weakpoint evidence 和 memory 各一份；
- revision 只增加一次，response 完全相同。

`autotutor_finalize_fault_injection_smoke`：

- 在每个 staged effect 前后和 session CAS 前注入异常；
- 数据库零部分写入；
- retry 后只提交一次；
- commit 后模拟响应丢失，replay 不新增副作用。

`agent_runtime_non_tool_policy_smoke`：

- 非 tool kind/side-effect/risk/timeout 错配均拒绝；
- write step 无 idempotency key 拒绝；
- AutoTutor finalize write plan 通过；
- 既有 tool policy 无回归。

`autotutor_transition_migration_smoke`：

- SQLite `008 → 009 → 008 → 009`；
- legacy learning events 的多个 NULL effect keys；
- unique effect/evidence key 冲突行为；
- schema readiness 缺列/缺表/旧 revision fail closed；
- 真实 PostgreSQL 版本单独报告，未运行必须显示 `NOT_RUN`。

### 13.2 必须回归

- AutoTutor trajectory、teaching quality、objective alignment；
- assessment validity、exit ticket independence、false mastery；
- content blocked API、session recovery、question handoff；
- AutoTutor CAS/idempotency 和 Runtime v2 checkpoint/concurrency/resume；
- learning assistant session/auth/security；
- frontend lint、unit、production build；
- AutoTutor 和随问核心 Playwright flow；
- `eval/run_core_evals.py --quick --no-report` 全量 quick gate。

### 13.3 P0 不变量

| 指标 | 门槛 |
| --- | ---: |
| public context forbidden fields | 0 |
| `difficulty_contract_violation_total` | 0 |
| lower-difficulty 后更难题 | 0 |
| remediation 重复 assessment ID | 0 |
| 无候选时继续评分 | 0 |
| partial transition writes | 0 |
| duplicate learning effect key | 0 |
| duplicate weakpoint evidence | 0 |
| duplicate mastery/review memory | 0 |
| false mastery | 0 |
| completed exit ticket 对应 answered event | 恰好 1 |

## 14. 验收矩阵

### 14.1 本地开发完成

- [x] 三个当前失败复现已固化并转绿；
- [x] public DTO 写读双裁剪和 legacy 安全读取通过；
- [x] 五个 pilot objective 的真实降难度不变量通过；
- [x] 无候选 fail closed 且不改变 mastery/weakpoint；
- [x] answer transition fault injection 零部分写入；
- [x] 顺序/并发/replay 无重复副作用；
- [x] Runtime 非 tool policy 与 finalize write 合同通过；
- [x] migration 009 SQLite smoke 通过；
- [x] 既有 AutoTutor/learning assistant/Runtime v2 回归无失败；
- [x] frontend lint/unit/build/Playwright 通过；
- [x] 文档记录命令、exit code、suite totals、case totals 和 optional skip。

全部满足后，状态只能更新为：

```text
Development Complete（local deterministic）
Release Validation Pending
```

### 14.2 发布完成

- [ ] 真实 PostgreSQL migration 009 smoke；
- [ ] staging 真实数据库并发与 fault injection；
- [ ] staging 网络 response payload 安全抽检；
- [ ] 教师盲审新增 remedial items；
- [ ] 真实 LLM 路径不绕过 selector/content gate；
- [ ] production pilot allowlist；
- [ ] canary 期间 duplicate/partial/forbidden 字段均为 0；
- [ ] 至少一个学生小样本验证“讲简单一点”确实更易理解；
- [ ] 24 小时或下次复习保持结果单独报告。

未满足任一项时，production/release 状态保持 `NOT_RUN` 或 `Pending`，不得标记为正式 `Implemented`。

## 15. 灰度与兼容

### 15.1 合同版本

新 session state 增加：

```json
{
  "transition_contract_version": 2,
  "assessment_history": ["assessment-id-1"]
}
```

- 新 v1.36 session 使用 version 2；
- legacy session 缺省为 version 1，可继续只读恢复；
- legacy session 下一次 mutation 前执行安全升级检查；无法建立确定性 assessment/effect key 时进入 retryable safe stop，不写 mastery；
- public context sanitizer 对所有版本无条件生效。

### 15.2 Rollout

实施决策：不新增以下 BPS 开关：

```dotenv
EDU_AGENT_AUTOTUTOR_TRANSITION_V2_BPS=0
EDU_AGENT_AUTOTUTOR_ADAPTIVE_SELECTOR_BPS=0
```

原因是公开裁剪、真实难度和 answer transition 原子性均为安全合同，不能通过灰度回退到泄露、伪适配或部分写入版本。新建及可安全恢复的 session 统一使用 `transition_contract_version=2`；无法验证内容合同的 legacy session 继续 fail closed。外部发布仍按以下顺序验证：

1. 本地 deterministic 100%；
2. staging 新 session 100%，旧 session 只读/安全迁移；
3. production pilot allowlist；
4. 1% 新 session，至少 100 个 answer transitions；
5. 10% 连续 48 小时；
6. 达到 P0 门槛后再扩大。

公开 context 裁剪属于安全边界，不受 BPS 控制，也不得通过 kill switch 回退到泄露版本。

content gate 继续遵守 v1.35 的 off/shadow/enforce 合同；v1.36 不擅自把 production content gate 改为 enforce。

## 16. 回滚

回滚不得恢复内部字段泄露、伪降难度或非幂等 mastery 写入。

推荐：

- public sanitizer 保持启用；
- 停止创建 transition contract v2 的新 session；
- 已进入 v2 的 session 继续使用事务路径，或进入可恢复维护状态；
- adaptive selector 无安全候选时继续 fail closed，不回退 `variant_index` 轮转；
- migration 009 表和 effect 数据保留，不做生产 downgrade；
- Runtime v2 rollout 可保持 0 BPS，不影响业务事务安全；
- 若事务路径出现 P0，停止新答题 mutation，允许读取已有课程和安全进入随问。

## 17. 风险与后续版本

### 17.1 本轮风险

- SQLite 与 PostgreSQL 对 unique NULL、并发和隔离级别行为不同；
- 旧 session 没有 assessment history，不能推断已出现题目；
- transaction 变长可能增加数据库锁等待；
- Runtime ledger 与业务 effect ledger 形成双账本，必须明确业务真相来源；
- 内容补齐如果未经独立教师审核，只能算项目内 curriculum-reviewed，不算教师盲审。

缓解：

- 真实 PostgreSQL smoke 和并发测试是 release gate；
- legacy session 无法安全升级时 fail closed；
- 事务内禁止 LLM、检索和网络调用，只提交已构造 effects；
- Runtime ledger 只引用 business effect key；
- 教师盲审保持独立 `NOT_RUN` 状态。

### 17.2 v1.37 Backlog：Runtime Product Contract Closure

以下已识别问题不塞入 v1.36：

- 历史人物、辩论 UI 的 auth/idempotency/terminal consumption；
- 作文 Runtime/artifact 的 flag 语义、UI 和 idempotency；
- 产品 wrapper 的真实 budget enforcement；
- artifact retention/purge 调度；
- queued worker、stale job recovery 和 timeout cancellation；
- 全平台非 tool capability 风险标注复核；
- AgentOps 对业务 effect 和 Runtime ledger 的一致性告警。

v1.37 应在 v1.36 本地与 staging 证据稳定后，按单一产品 Agent 纵向推进，不做一次性全平台重写。

## 18. 完成定义

v1.36 只有在以下条件全部满足后，才可以标记为正式 `Implemented`：

1. 学生公开交接 forbidden fields 为 0，含 legacy context；
2. 五个 pilot objective 的降难度题目真实不更难且不重复；
3. 无合适题时稳定 fail closed，不污染学习证据；
4. 所有 answer transition 业务副作用具备单事务、幂等和 replay 证据；
5. Runtime finalize side-effect 合同与实际业务一致；
6. migration 009 在 SQLite 和真实 PostgreSQL 均通过；
7. 既有 AutoTutor、学习助手、Runtime、前端和 E2E 无回归；
8. 教师盲审、真实 LLM、staging 和 production canary 的实际状态被准确记录；
9. 没有把 deterministic 通过描述为学生学习效果或生产证明。

本文 2026-08-24 完成判断：本地开发与 deterministic 验证已完成；第 6 项仅完成 SQLite，真实 PostgreSQL 仍为 `NOT_RUN`；教师盲审、真实 LLM、staging、production canary 和学习效果证据仍为 `NOT_RUN`。因此本 Spec 是可复核的本地开发完成记录，但还不是生产发布完成证明。
