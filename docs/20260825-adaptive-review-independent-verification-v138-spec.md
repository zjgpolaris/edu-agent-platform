# EduAgent 自适应复习独立验证与延迟保持闭环 v1.38 Spec

**创建时间：** 2026-08-25
**分析基线：** `main@82eefa9`
**状态：** Implemented · 本地开发与工作区门禁通过；clean-HEAD release seal 待提交后生成
**本地实现证据：** PASS（2026-08-25，详见 18.1）；真实外部证据仍为 NOT_RUN
**生产状态：** NOT_RUN；尚无真实 PostgreSQL、教师盲审、学生保持效果、staging 或 production canary 证据

## 0. 决策摘要

v1.38 不新增 Agent、不扩展全册题库，也不回到 Runtime v2 横向迁移。本轮只修复自适应复习主链中的一个 P0 学习证据问题：

> 学生一次答对只能证明当前作答正确；看过反馈后在另一道题上答对，才能形成即时独立验证；至少 24 小时后再通过一份独立保持题，系统才有资格把该知识点从薄弱点中移除。

目标学习链路：

```text
独立检索作答 retrieval
  → 服务端判分
  → 展示对照材料与解析 feedback
  → 学生确认继续
  → 不同题目的即时验证 verification
  → 验证通过后安排至少 24 小时后的保持题 retention
  → 独立保持题通过
  → 写入 retention_verified
  → 更新全局薄弱点掌握状态
```

核心原则：

1. 相同题目、相同内容指纹或同一阶段的重复正确不能构成两份掌握证据；
2. 看过答案、材料或解析的题目不能同时充当自己的独立验证题；
3. 即时验证不能替代延迟保持；
4. 没有足够独立题目时 fail closed，保留薄弱点；
5. 所有状态推进、题目追加和证据写入必须事务化、幂等、可重放；
6. 本地模拟时钟通过只能证明调度合同，不能证明真实学生学习保持。

## 1. 当前基线与失败证据

### 1.1 已有能力

截至 `main@82eefa9`，自适应复习已经具备：

- 五个 pilot 历史知识目标的审定内容包；
- 题目质量合同 v3；
- 未审定内容 fail closed；
- 按薄弱点状态选择 easy 基础辨析或 medium 先答后证题；
- 作答前隐藏答案、解析和作答后对照材料；
- 服务端根据 `selected_answer` 判分；
- session CAS、weakpoint evidence 和 learning event 同事务写入；
- 同题同答案重放、改答案冲突；
- 学生端“先作答 → 看材料与解析 → 下一题”交互。

v1.37 已记录的本地确定性基线为：

- full quick gate：62/63 suites、286/287 cases；
- 唯一 skip：依赖外部模型凭证的既有 `history_character_smoke`；
- frontend lint、8 files / 22 tests、Next.js production build；
- 教师盲审、真实学生效果、真实 PostgreSQL 和 canary 均为 `NOT_RUN`。

上述证据证明题目结构、公开合同和工程幂等，不证明延迟保持或真实学习效果。

### 1.2 当前执行链

```text
GET /api/students/{student_id}/review/today
  → get_today_session / create_today_session
  → weakpoints(wrong_count, correct_streak)
  → review_service._pick_question
  → autotutor_content.json 审定 assessment
  → review_sessions.tasks_json
  → public_review_session

POST /api/students/{student_id}/review/submit
  → 服务端判分
  → task.done/correct
  → review_sessions tasks_json CAS
  → apply_weakpoint_evidence_with_connection
      → correct: verified_correct
      → wrong: wrong
  → record_learning_event_with_connection
  → 返回本题材料、答案和解析
```

### 1.3 P0 失败：同题重复正确可以形成假掌握

当前 `review_service.submit_answer()` 对任意正确复习题直接写入：

```text
evidence_type = verified_correct
```

当前 `weakpoint_service` 的掌握逻辑只计算：

```text
correct_streak += 1
correct_streak >= 2 → DELETE weakpoint
```

该逻辑没有校验：

- assessment 是否不同；
- stem/options 内容指纹是否不同；
- 是否来自不同阶段；
- 是否在反馈前独立完成；
- 是否跨 session 或跨时间；
- 是否满足保持间隔。

2026-08-25 在隔离 SQLite 中执行的确定性复现：

```json
{
  "assessment_id": "wuxu-cause-practice-1",
  "first": {
    "removed": false,
    "correct_streak": 1
  },
  "second": {
    "removed": true,
    "correct_streak": 2
  },
  "after_second": [],
  "false_mastery_reproduced": true
}
```

两条 evidence key 不同，但 `assessment_id`、日期、session 和题目均相同，第二次仍删除了薄弱点。这说明现有幂等合同只能阻止同一 effect 重放，不能证明两份证据在教学上相互独立。

最小复现步骤：

```python
record_weakpoint(student, tag, source="spec_baseline")
apply_weakpoint_evidence_with_connection(
    conn,
    evidence_key="review:first",
    evidence_type="verified_correct",
    assessment_id="wuxu-cause-practice-1",
    ...,
)
apply_weakpoint_evidence_with_connection(
    conn,
    evidence_key="review:second",
    evidence_type="verified_correct",
    assessment_id="wuxu-cause-practice-1",
    ...,
)
assert get_weakpoints(student) == []  # 当前错误行为
```

### 1.4 “下一题”尚未成为验证合同

v1.37 前端测试已经证明材料只在判分后显示，点击“下一题”后材料消失。但下一题目前只是 session 中下一个未完成 task：

- 可能属于另一个知识点；
- 没有 `retrieval / verification / retention` 角色；
- 没有绑定前一题的 feedback；
- 没有独立性校验；
- 没有到期时间；
- 不能证明学生在看完材料后能够重新提取和迁移。

### 1.5 内容与证据覆盖边界

当前内容包只有五个 pilot objective，每个 objective 包含：

- 3 道 practice；
- 1 道 exit ticket。

这足以验证 v1.38 的三阶段 pilot，但不代表全册覆盖。未审定目标继续 blocked，不允许使用 LLM 草稿或通用干扰项补位。

数量上已有三阶段候选，但当前 practice items 尚未配置作答后 `feedback_material`。v1.38 必须为每个 pilot objective 至少补齐一道“题干可独立作答、材料仅用于答后对照”的 retrieval practice；不能为了沿用现有数量而省略反馈材料。

当前 `eval/reports/latest.md` 仍停留在 2026-08-20 的 dirty revision，且 LLM calls 为 0。v1.38 必须在 clean HEAD 上生成新的正式报告；不能只把 `--no-report` 终端汇总写进 Spec。

## 2. 学生需求与产品目标

### 2.1 学生需求

1. **先自己想：** 作答前不能看到会直接提示答案的材料或解析。
2. **答后能纠偏：** 提交后应看到针对自己选项的反馈和对照材料。
3. **确认真的会：** 看懂材料后要用另一道题重新回答，而不是把“看懂了解析”当成掌握。
4. **过一段时间还记得：** 当天会做不代表形成稳定记忆，系统应安排延迟复测。
5. **进度可信：** 重复点击、刷新、同题重做或系统恢复不能制造多份掌握证据。
6. **失败安全：** 缺题、过早作答或证据不足时保留薄弱点，不做乐观推断。

### 2.2 v1.38 产品目标

- 建立 `retrieval → feedback → verification → retention` 状态机；
- 题目角色、内容指纹、父证据和到期时间成为领域合同；
- retrieval 正确只记录非掌握型正确证据；
- verification 必须使用独立题目，正确后只进入 retention due；
- retention 至少间隔 24 小时，正确后才允许移除薄弱点；
- review 与 AutoTutor 共用新的证据语义，但不复制 AutoTutor 状态机；
- 旧 `verified_correct` 不自动提升为 retention evidence；
- API 继续保持答案、材料、解析和内部证据字段的公开边界；
- 建立 deterministic、迁移、并发、前端和 clean-HEAD 报告证据。

### 2.3 非目标

- 扩展五个 pilot objective 之外的全册题库；
- 新建教师审题工作台或题包发布审批流；
- 动态 LLM 出题并直接发布；
- 主观题、综合材料题自动评分；
- 新增 Agent、Agent-as-tool、动态 fan-out 或开放式规划；
- 历史人物、辩论、作文 Runtime wrapper 横向迁移；
- 用模拟 24 小时时钟证明真实学生保持效果；
- 在没有真实 PostgreSQL 和 canary 时宣称生产 exactly-once。

## 3. 学习证据合同 v2

### 3.1 EvidenceStage

```python
ReviewEvidenceStage = Literal[
    "retrieval",
    "verification",
    "retention",
]

ReviewEvidenceType = Literal[
    "wrong",
    "retrieval_correct",
    "independent_correct",
    "retention_correct",
]
```

语义：

| evidence type | 是否改变 wrong_count | 是否推进掌握 | 是否允许移除薄弱点 |
|---|---:|---:|---:|
| `wrong` | 是，且重置验证状态 | 否 | 否 |
| `retrieval_correct` | 否 | 进入 feedback/verification | 否 |
| `independent_correct` | 否 | 安排 retention | 否 |
| `retention_correct` | 否 | 完成保持验证 | 仅满足完整证据链时允许 |

不得继续把所有正确统一写为 `verified_correct`。legacy `verified_correct` 只能被解释为“历史即时正确”，不能自动视为 retention evidence。

### 3.2 ReviewMasteryState

```python
class ReviewMasteryState(BaseModel):
    schema_version: Literal[1] = 1
    student_id: str
    knowledge_tag: str
    status: Literal[
        "needs_retrieval",
        "awaiting_feedback",
        "verification_pending",
        "retention_due",
        "retention_verified",
        "needs_support",
        "content_blocked",
    ]
    retrieval_evidence_key: str | None = None
    verification_evidence_key: str | None = None
    retention_evidence_key: str | None = None
    retention_due_at: str | None = None
    revision: int = 0
    updated_at: str
```

`weakpoints` 继续作为学生薄弱点查询 read model；`weakpoint_evidence` 和 `review_mastery_state` 是掌握推进的事实与状态来源。

### 3.3 掌握判定

只有同时满足以下条件，才能写入 `retention_verified` 并移除 weakpoint：

1. 存在同一 student + knowledge tag 的 `independent_correct`；
2. independent evidence 来自 verification 阶段；
3. retention evidence 来自不同 assessment ID；
4. verification 和 retention 的 assessment fingerprint 不同；
5. retention 作答时间 `>= retention_due_at`；
6. retention 题未在作答前暴露答案、材料或解析；
7. 两份证据均来自 quality verified 的审定 assessment；
8. evidence key、父证据和状态 revision 均匹配；
9. 当前没有更新的 wrong evidence 使该证据链失效。

`correct_streak` 可以保留为兼容展示字段，但不再单独触发 weakpoint 删除。

### 3.4 错误处理

- retrieval 错误：写 `wrong`，展示反馈，仍允许进入 verification；
- verification 错误：写 `wrong`，状态进入 `needs_support`，不安排 retention；
- retention 错误：写 `wrong`，状态回到 `needs_retrieval`，保留薄弱点；
- 任一阶段重复提交同答案：返回已保存响应，不追加证据；
- 任一阶段同 key 改答案：返回 409；
- 过早提交 retention：返回 409 `retention_not_due`，不写任何业务副作用。

## 4. Assessment 独立性合同

### 4.1 AssessmentFingerprint

不能只靠 assessment ID 判断独立性。新增稳定指纹：

```text
sha256(
  objective_id
  + normalized_stem_or_review_prompt
  + canonical_sorted_option_texts
  + cognitive_action
  + source_ids
)
```

指纹不包含：

- 正确答案字母；
- 学生答案；
- 随机 seed；
- session ID；
- 展示顺序；
- 内部 prompt 或 trace。

只换 assessment ID、选项顺序或题干前缀不能形成新指纹。

### 4.2 阶段选题规则

| 阶段 | 候选 | 材料时机 | 独立性要求 |
|---|---|---|---|
| retrieval | 带 `feedback_material` 的 `practice` | 作答后显示 | 本轮首次出现 |
| verification | 不同 `practice` | 作答前禁止 | 与 retrieval ID、指纹均不同 |
| retention | `exit_ticket` 优先 | 作答前禁止 | 与 retrieval、verification 均不同 |

通用规则：

1. objective 必须一致；
2. content validation 必须为 verified；
3. 排除当前证据链已用 assessment ID 和 fingerprint；
4. verification 优先 `recall/explain/compare`，不能依靠刚展示的材料原句作答；
5. retention 优先 `compare/apply`，用于保持与迁移；
6. 选择使用稳定 seed，重试和恢复结果一致；
7. 不允许候选不足时复用旧题；
8. 不允许从未审定 LLM 输出补位；
9. 没有安全候选时进入 `content_blocked`。

### 4.3 五个 pilot 内容门禁

五个 pilot objective 必须各自证明：

- 至少有两道互相独立的 practice，可用于 retrieval 和 verification；
- retrieval practice 必须配置 `review_prompt + feedback_material`，且 review prompt 不依赖隐藏材料；
- 至少有一道与两道 practice 独立的 exit ticket；
- 三个阶段的 assessment fingerprint 全部不同；
- verification 题干不引用已隐藏材料；
- retention 题在不展示反馈材料时仍可独立作答；
- 原因、影响、意义、目的等 objective aspect 不错位。

当前每个 objective 的 3 practice + 1 exit ticket 只能作为候选数量基线；practice 的反馈材料覆盖仍未完成，必须与上述指纹和语义门禁一起补齐。

## 5. 复习状态机

### 5.1 状态流

```text
needs_retrieval
  → retrieval submitted
      ├─ wrong → wrong evidence
      └─ correct → retrieval_correct
  → awaiting_feedback
  → student acknowledges feedback
  → verification_pending
  → verification submitted
      ├─ wrong → needs_support
      └─ correct → independent_correct + retention_due_at
  → retention_due
  → retention submitted after due
      ├─ wrong → needs_retrieval
      └─ correct → retention_correct → retention_verified
```

### 5.2 Feedback acknowledge

材料显示后不立即把 verification 题当作普通下一题展示。学生点击：

```text
看完了，做一道验证题
```

服务端才推进 `awaiting_feedback → verification_pending`。该动作：

- 不写掌握证据；
- 不改变 weakpoint；
- 使用 session revision + idempotency key；
- 选择并持久化独立 verification task；
- 刷新后仍能恢复到正确阶段；
- 不依赖“前端已经渲染材料”作为掌握事实。

### 5.3 Retention 调度

默认合同：

```text
retention_due_at = verification_correct_at + 24 hours
```

- 数据库存储 UTC ISO 8601；
- API 返回 UTC 时间和学生时区展示字符串；
- 本地 eval 使用注入 clock，不执行真实 sleep；
- `GET review/today` 只在 due_at 已到时发布 retention task；
- 到期前学生端只显示“已安排明日保持检验”，不显示题干；
- 到期时 retention 优先于新的普通 weakpoint task；
- 同一知识点同一时刻只允许一条 active evidence chain。

24 小时是 v1.38 pilot 默认值，不宣称为所有学科和学生的最优间隔。后续可基于真实数据调整，但不得由 LLM 临时决定。

### 5.4 Session 完成语义

今日 session 的 completed 只代表“今日可完成任务已处理”，不等于知识点已掌握。

公开状态区分：

```text
today_completed
verification_pending
retention_scheduled
retention_due
retention_verified
```

周报、打卡和连续学习天数不能把 `today_completed` 直接解释为 mastery。

## 6. 数据模型与 Migration 010

新增：

```text
backend/alembic/versions/010_review_independent_verification.py
```

### 6.1 weakpoint_evidence 扩展

建议增加 nullable 字段以兼容 legacy rows：

```sql
ALTER TABLE weakpoint_evidence ADD COLUMN evidence_stage TEXT NULL;
ALTER TABLE weakpoint_evidence ADD COLUMN assessment_fingerprint TEXT NULL;
ALTER TABLE weakpoint_evidence ADD COLUMN parent_evidence_key TEXT NULL;
ALTER TABLE weakpoint_evidence ADD COLUMN eligible_at TEXT NULL;
ALTER TABLE weakpoint_evidence ADD COLUMN occurred_at TEXT NULL;
```

索引：

```sql
CREATE INDEX idx_weakpoint_evidence_chain
ON weakpoint_evidence(
  student_id,
  knowledge_tag,
  evidence_stage,
  assessment_fingerprint,
  occurred_at
);
```

`evidence_key` 继续作为 effect 幂等主键。教学独立性不能只依赖唯一索引，事务提交器必须读取当前 chain 并校验父证据、指纹、到期时间和 revision。

### 6.2 review_mastery_state

```sql
CREATE TABLE review_mastery_state (
  student_id TEXT NOT NULL,
  knowledge_tag TEXT NOT NULL,
  status TEXT NOT NULL,
  retrieval_evidence_key TEXT,
  verification_evidence_key TEXT,
  retention_evidence_key TEXT,
  retention_due_at TEXT,
  revision INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(student_id, knowledge_tag)
);

CREATE INDEX idx_review_mastery_due
ON review_mastery_state(status, retention_due_at);
```

### 6.3 review_sessions 扩展

为显式状态推进和 response replay 增加：

```sql
ALTER TABLE review_sessions ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE review_sessions ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE review_sessions ADD COLUMN last_idempotency_key TEXT NULL;
ALTER TABLE review_sessions ADD COLUMN last_request_hash TEXT NULL;
ALTER TABLE review_sessions ADD COLUMN last_response_json TEXT NULL;
```

现有 `tasks_json` 保持兼容，但 task 必须增加：

```json
{
  "task_role": "retrieval | verification | retention",
  "evidence_chain_id": "...",
  "assessment_fingerprint": "sha256:...",
  "parent_task_id": null,
  "feedback_acknowledged": false,
  "due_at": null
}
```

### 6.4 Legacy 策略

- legacy weakpoint evidence 保持原样，不伪造 stage、fingerprint 或 due time；
- legacy `verified_correct` 不自动转成 `retention_correct`；
- 已经被历史逻辑删除的 weakpoint 缺少可靠反向证据，本轮不自动复活；
- 未完成 legacy review session 在下一次读取时升级为 retrieval task；
- 无法建立稳定 assessment fingerprint 的 legacy task fail closed；
- migration 不修改题目答案、学生答案或 learning event 原始数据；
- SQLite 自动建表仅服务本地开发，生产必须运行 Alembic 010。

Migration 验证至少覆盖：

- `009 → 010 → 009 → 010`；
- legacy NULL rows；
- SQLite 与 PostgreSQL nullable/index 行为；
- 旧 review session 升级；
- readiness revision 更新为 010；
- downgrade 数据丢失风险说明。

## 7. 事务与幂等合同

### 7.1 单一提交器

新增或抽取：

```python
def commit_review_transition(
    *,
    student_id: str,
    session_id: str,
    expected_revision: int,
    idempotency_key: str,
    request_hash: str,
    transition: ReviewTransition,
) -> ReviewTransitionResult:
    ...
```

同一数据库事务内：

1. owner/student scope 已在 API 层校验；
2. 读取并校验 review session revision；
3. 同 key 同 hash 返回 last response；
4. 同 key 不同 hash 返回 conflict；
5. 校验当前 mastery state 和 parent evidence；
6. 校验 assessment fingerprint 独立性；
7. 校验 retention due time；
8. 插入 weakpoint evidence；
9. 仅首次 evidence 改变 weakpoint/mastery aggregate；
10. CAS 更新 mastery state；
11. CAS 更新 review session tasks/status/revision；
12. 保存公开 replay response；
13. commit 后返回。

事务内禁止：

- LLM 调用；
- RAG 检索；
- 网络请求；
- 动态生成题目；
- 非确定性随机选择。

选题和 transition 构造必须在事务前完成，提交器只验证并写入已构造意图。

### 7.2 Effect key

内部 `chain_id` 使用稳定派生值，不使用每次重试重新生成的随机 UUID：

```text
chain_id = sha256(student_id | knowledge_tag | retrieval_effect_key)[:32]
```

`chain_id` 只保存在内部状态和数据库，不进入学生公开响应。

```text
retrieval:
review:{session_id}:{task_id}:retrieval:{assessment_id}

feedback acknowledge:
review:{session_id}:{task_id}:feedback_ack

verification:
review:{session_id}:{task_id}:verification:{assessment_id}

retention:
review:{chain_id}:retention:{assessment_id}
```

effect key 不包含答案文本、学生原始输入、prompt、随机 UUID 或材料全文。

### 7.3 并发与恢复

- 相同提交并发只有一个事务成功写 evidence；
- 第二个相同请求返回 replay；
- 改答案或改 action 返回 409；
- feedback acknowledge 重复点击不追加第二道 verification；
- retention scheduler 重复运行不追加第二道 retention；
- transaction commit 后 HTTP 丢失，重试返回相同公开响应；
- 任何 evidence/session/mastery CAS 之间的故障必须整体 rollback；
- stale revision 不能写 weakpoint、learning event 或 mastery state。

## 8. API 合同

保持既有 endpoint，不新增第二套 review API 根路径。

### 8.1 GET 今日复习

```text
GET /api/students/{student_id}/review/today
```

公开 task 增加：

```json
{
  "task_index": 0,
  "task_role": "retrieval",
  "tag": "戊戌变法失败原因",
  "question": "...",
  "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
  "difficulty": "easy",
  "phase": "answering",
  "session_revision": 3
}
```

作答前禁止返回：

- `answer`；
- `material`；
- `explanation`；
- `option_feedback`；
- `assessment_fingerprint`；
- `evidence_key`；
- `parent_evidence_key`；
- `retention_due_at` 的内部精确策略原因；
- source IDs、strategy、trace 和候选池。

当 retention 未到期时，可以返回学生可理解的摘要：

```json
{
  "scheduled_reviews": [
    {
      "knowledge_tag": "戊戌变法失败原因",
      "available_at": "2026-08-26T10:00:00+08:00",
      "message": "明天再确认一次，看看是否真正记住。"
    }
  ]
}
```

不返回未到期题干和选项。

### 8.2 POST 作答

```text
POST /api/students/{student_id}/review/submit
```

请求：

```json
{
  "task_index": 0,
  "selected_answer": "A",
  "expected_revision": 3,
  "idempotency_key": "review-client-turn-..."
}
```

retrieval 响应：

```json
{
  "is_correct": false,
  "phase": "awaiting_feedback",
  "task": {
    "material": "...",
    "answer": "A",
    "selected_feedback": "...",
    "explanation": "..."
  },
  "next_action": {
    "type": "acknowledge_feedback",
    "label": "看完了，做一道验证题"
  },
  "session_revision": 4
}
```

verification 正确响应：

```json
{
  "is_correct": true,
  "phase": "retention_scheduled",
  "mastery": {
    "status": "not_yet_retained",
    "student_message": "这次已经理解，明天再确认一次是否真正记住。"
  },
  "available_at": "2026-08-26T10:00:00+08:00",
  "session_revision": 7
}
```

retention 正确响应才允许：

```json
{
  "is_correct": true,
  "phase": "retention_verified",
  "mastery": {
    "status": "retention_verified",
    "student_message": "经过间隔复测，你已经稳定掌握这个知识点。"
  }
}
```

### 8.3 POST feedback advance

新增同一根路径下的阶段推进 endpoint：

```text
POST /api/students/{student_id}/review/advance
```

请求：

```json
{
  "task_index": 0,
  "action": "continue_after_feedback",
  "expected_revision": 4,
  "idempotency_key": "review-feedback-..."
}
```

响应只返回新的公开 verification task，不返回内部 parent evidence、fingerprint 或答案。

### 8.4 错误合同

| HTTP | code | 含义 |
|---:|---|---|
| 400 | `invalid_review_transition` | 当前阶段不允许该动作 |
| 409 | `stale_review_revision` | session 已变化，需刷新 |
| 409 | `idempotency_payload_conflict` | 同 key 请求内容不同 |
| 409 | `retention_not_due` | 保持题尚未到期 |
| 409 | `evidence_chain_conflict` | 父证据或状态不匹配 |

公开错误不得包含答案、指纹、evidence key、SQL、候选池或内部 reason stack。

无独立 assessment 不是客户端参数错误。服务端返回 200 的安全业务状态：

```json
{
  "phase": "content_blocked",
  "content_blocked": {
    "message": "当前没有合适的新验证题，本次不会计入掌握结果。"
  }
}
```

## 9. 学生端交互

### 9.1 Retrieval

- 首屏显示“先独立作答”；
- 不显示材料；
- 选择后由服务端判分；
- 判分前不能通过客户端字段推断正确答案。

### 9.2 Feedback

- 保留学生已选答案和正确答案标记；
- 展示“对照材料”；
- 展示针对所选项的反馈；
- 主按钮为“看完了，做一道验证题”；
- 不直接跳到其他知识点。

### 9.3 Verification

- 使用同一知识点的独立题；
- 页面标签显示“验证理解”；
- 作答前不再显示刚才材料；
- 不显示“已掌握”；
- 答对后显示“明天再确认一次”；
- 答错后显示“还需巩固”，保留薄弱点。

### 9.4 Retention

- 到期后显示“保持检验”；
- 不提示昨日答案和材料；
- 答对后才显示“稳定掌握”；
- 答错后回到巩固路径，不使用失败性文案；
- 未到期时不提供绕过入口。

### 9.5 完成页

分开显示：

- 今日已完成题数；
- 待验证知识点；
- 已安排保持检验；
- 已稳定掌握知识点。

禁止把今日正确率直接标成“掌握率”。

## 10. AutoTutor 与共享证据兼容

AutoTutor 已有 `practice → independent exit ticket → verified_mastery` 单 session 合同。本轮不重写 AutoTutor 状态机，但必须调整全局 weakpoint evidence 语义：

- AutoTutor 的独立 exit ticket 正确映射为 `independent_correct`；
- AutoTutor session 内仍可展示“本节验证通过”；
- 不再仅凭 AutoTutor 的一次 session verified mastery 删除全局 weakpoint；
- 由自适应复习调度 retention task；
- AutoTutor 和 review 使用相同 assessment fingerprint 算法；
- 跨 feature 证据可以组成同一 chain，但 verification 与 retention 仍必须 assessment 独立且满足时间间隔；
- content gate 为 off/shadow 时产生的非 mastery evidence 不得被升级为 retention evidence。

业务真相仍在 weakpoint evidence/mastery state；Runtime ledger 只引用 effect key，不负责推断学生掌握。

## 11. Learning Events 与指标

### 11.1 新增事件

```text
review_retrieval_answered
review_feedback_acknowledged
review_verification_answered
review_retention_scheduled
review_retention_answered
review_retention_verified
review_independent_question_blocked
review_retention_not_due_rejected
```

事件 metadata 允许：

- objective ID；
- assessment ID；
- task role；
- difficulty；
- cognitive action；
- is_correct；
- content version；
- due interval bucket；
- source feature。

事件 metadata 禁止：

- 正确答案；
- 学生答案全文；
- 材料全文；
- source IDs；
- assessment fingerprint 原值；
- internal strategy / trace。

### 11.2 工程指标

- duplicate evidence count；
- invalid transition count；
- stale revision count；
- early retention rejection count；
- independent question blocked rate；
- session/evidence/mastery consistency；
- transaction rollback count；
- response replay count。

### 11.3 学习过程指标

- retrieval accuracy；
- feedback → verification conversion；
- verification accuracy；
- 24h retention attempt rate；
- 24h retention accuracy；
- wrong-after-verification rate；
- content blocked coverage；
- false mastery count。

没有真实学生数据时，上述学习指标状态必须为 `NOT_RUN`，不能用 deterministic fixture 计算后宣称有效。

## 12. 实现模块

| 文件 | 计划改动 |
|---|---|
| `backend/services/review_service.py` | 接入阶段状态、独立选题、retention 调度和 transition 提交 |
| `backend/services/review_mastery_service.py` | 新增证据链纯函数、状态机、指纹和掌握判定 |
| `backend/services/weakpoint_service.py` | 支持新 evidence type；correct streak 降为兼容 read model |
| `backend/services/history_review_question.py` | 按 task role 选择独立 assessment，并执行 fingerprint 门禁 |
| `backend/agents/autotutor_content.py` | 提供共享 assessment fingerprint 和独立性校验 |
| `backend/agents/auto_tutor.py` | 将 session verified evidence 映射为 independent，而非 retention |
| `backend/api/routers/review_checkin.py` | 扩展 submit 合同，新增 feedback advance |
| `backend/db/schema.py` | migration 010 对应 schema |
| `backend/alembic/versions/010_review_independent_verification.py` | 证据链、mastery state、review session revision |
| `knowledge_base/history/autotutor_content.json` | 为五个 pilot 补齐 material-bearing retrieval practice 和三阶段独立性 |
| `backend/services/tutor_effectiveness_service.py` | 增加 verification/retention 指标并保留 NOT_RUN |
| `frontend/app/(student)/student/review/ReviewTab.tsx` | 三阶段 UI、scheduled retention 和结果分层 |
| `frontend/components/__tests__/ReviewTab.test.tsx` | 作答、材料、验证题、保持题完整交互 |
| `eval/review_mastery_evidence_eval.py` | 新增 P0 假掌握与证据链评测 |
| `eval/review_retention_scheduler_smoke.py` | 注入 clock 的 due/priority/idempotency 评测 |
| `eval/review_transition_fault_injection_smoke.py` | 单事务和故障恢复 |
| `eval/review_migration_smoke.py` | 009/010、legacy、readiness、PostgreSQL 状态 |
| `eval/run_core_evals.py` | 注册新 suites 和 release profile |

不得为 review 创建第二套内容真相源或第二套 weakpoint 聚合逻辑。

## 13. 实施里程碑

### Milestone 0：失败测试与合同

- 固化“同 assessment 两次正确删除 weakpoint”；
- 固化“同指纹不同 ID仍被当成独立题”；
- 固化“verification 正确立即删除 weakpoint”；
- 固化“retention 未到期仍可提交”；
- 定义 EvidenceStage、EvidenceType、ReviewMasteryState 和 fingerprint；
- 此阶段不改变产品行为。

### Milestone 1：Migration 010 与证据服务

- 扩展 weakpoint evidence；
- 新增 review mastery state；
- review session revision/replay；
- 纯函数 evidence chain validator；
- legacy 安全读取；
- SQLite upgrade/downgrade/readiness。

### Milestone 2：即时独立验证

- retrieval 正确不再直接写 verified mastery；
- 五个 pilot 补齐 material-bearing retrieval practice；
- feedback acknowledge；
- 独立 verification selector；
- 无独立题 fail closed；
- review submit/advance 事务和幂等。

### Milestone 3：延迟保持

- retention due 调度；
- 到期前不发布题目；
- retention 独立性与时间门禁；
- retention 正确才移除 weakpoint；
- 时区和跨日 session 行为。

### Milestone 4：AutoTutor 兼容与学生 UI

- AutoTutor verified mastery 映射为 independent evidence；
- 跨 feature chain；
- ReviewTab retrieval/feedback/verification/retention UI；
- 完成页区分今日完成和稳定掌握；
- 公开 payload forbidden fields 回归。

### Milestone 5：工程验证与证据报告

- deterministic eval；
- concurrency/idempotency/fault injection；
- frontend lint/unit/build/Playwright；
- full quick gate；
- clean HEAD 生成正式 eval report；
- 真实 PostgreSQL 单独报告，未运行保留 `NOT_RUN`。

### Milestone 6：外部验证

- 历史教师审核三阶段题目独立性；
- 真实初中生可理解性样本；
- 至少 24 小时真实保持数据；
- staging shadow；
- production allowlist/canary。

Milestone 6 不得由本地 deterministic 测试替代。

## 14. 评测设计

### 14.1 review_mastery_evidence_eval

至少覆盖：

1. 同 assessment ID 两次正确不能移除 weakpoint；
2. 不同 ID、相同 fingerprint 不能构成独立证据；
3. retrieval 正确只写 `retrieval_correct`；
4. verification 与 retrieval 不同题；
5. verification 正确只进入 retention due；
6. retention 未通过前 weakpoint 始终存在；
7. retention 到期且独立答对后才移除；
8. verification/retention 任一错误保留 weakpoint；
9. 更新的 wrong evidence 使旧 chain 失效；
10. 五个 pilot objective 均有完整独立候选；
11. 无候选 fail closed；
12. legacy verified evidence 不自动升级。

### 14.2 review_retention_scheduler_smoke

- 注入 UTC clock；
- `23h59m59s` 不发布；
- `24h` 发布；
- timezone 展示不改变 UTC 判定；
- due retention 优先于普通任务；
- scheduler 重复运行不重复追加；
- 多进程等价 CAS；
- 到期前提交返回 conflict 且零副作用。

### 14.3 review_transition_fault_injection_smoke

在以下位置逐点注入异常：

- evidence insert 前后；
- mastery state CAS 前后；
- weakpoint aggregate 前后；
- review session CAS 前后；
- learning event 前后；
- commit 后 response 返回前。

每个故障点必须证明：

- rollback 时零部分写入；
- retry 后只提交一次；
- response-loss replay 不新增证据；
- session、evidence、mastery 和 weakpoint 一致。

### 14.4 API 与前端

- GET 作答前 forbidden fields 为 0；
- submit 后才返回本题材料和解析；
- feedback acknowledge 后才出现 verification；
- verification 题不显示上一题材料；
- retention 未到期不返回题干；
- retention 到期后可作答；
- UI 不暴露 Agent、evidence key、fingerprint、reason stack；
- 刷新恢复各阶段；
- 最后一题反馈先显示，再进入今日完成页。

### 14.5 必须回归

- `adaptive_review_question_quality_eval`；
- `review_system_smoke`；
- `assignment_review_loop_smoke`；
- `variant_question_smoke`；
- `weakpoints_smoke`；
- AutoTutor false mastery、exit ticket independence、adaptive difficulty；
- AutoTutor transition idempotency/fault injection；
- learning closure 和 tutor effectiveness；
- Runtime schema readiness；
- frontend lint、unit、production build；
- review/AutoTutor 核心 Playwright；
- full quick gate。

## 15. 验收矩阵

### 15.1 P0 本地确定性验收

| 验收项 | 门槛 |
|---|---:|
| 同题或同指纹假掌握 | 0 |
| verification 与 retrieval 独立 | 100% |
| retention 与前序题独立 | 100% |
| 未到期 retention 写入 | 0 |
| 无 retention 即删除 weakpoint | 0 |
| 重复 evidence | 0 |
| 部分事务写入 | 0 |
| 作答前答案/材料/解析泄露 | 0 |
| 五个 pilot 完整三阶段覆盖 | 100% |
| blocked 题改变 mastery | 0 |

### 15.2 工程验收

- migration 010 SQLite upgrade/downgrade/readiness 通过；
- 真实 PostgreSQL 若未配置必须明确 `NOT_RUN`；
- 新增专项 suites 全通过；
- full quick gate 无新增失败；
- frontend lint/unit/build/E2E 通过；
- `git diff --check` 通过；
- clean HEAD 生成 eval report，revision 与提交一致；
- report 明确 LLM calls、dataset version、skips 和 evidence profile。

### 15.3 外部证据

以下证据必须独立记录：

| 证据 | 当前状态 | 正式门槛 |
|---|---|---|
| 历史教师三阶段盲审 | NOT_RUN | 题干/答案/独立性/难度通过 |
| 初中生可理解性 | NOT_RUN | 记录样本、完成时长和误解点 |
| 真实 24h retention | NOT_RUN | 到期参与率和保持正确率 |
| PostgreSQL concurrency | NOT_RUN | duplicate/partial write 为 0 |
| staging shadow | NOT_RUN | 状态一致性和无 P0 |
| production canary | NOT_RUN | allowlist 后观察窗口无 P0 |

本地使用注入 clock 得到的 retention PASS 只能写“调度合同通过”，不能写“学生 24 小时仍能记住”。

## 16. 风险与缓解

### 16.1 题目数量不足

风险：三阶段独立性会耗尽候选池。

缓解：

- pilot 内容逐目标执行 fingerprint coverage gate；
- 候选不足时 blocked；
- 不回退重复题；
- 不自动发布 LLM 草稿。

### 16.2 学生任务变多

风险：强制 verification 和 retention 增加负担。

缓解：

- 每个知识点单次只追加一道 verification；
- retention 跨日且优先；
- UI 明确“今天理解”和“明天确认”的区别；
- 真实学生样本前不扩展到全册。

### 16.3 跨功能证据冲突

风险：AutoTutor 和 review 对 mastery 名称与资格理解不同。

缓解：

- session verified 与 retention verified 分层；
- 全局 weakpoint 只认共享 evidence contract；
- Runtime ledger 不推断 mastery；
- 新增跨 feature 回归。

### 16.4 Legacy 假掌握不可逆

风险：历史上已删除的 weakpoint 无法可靠恢复。

缓解：

- 不进行猜测性反向回填；
- v1.38 只保证新证据；
- 有真实作业/错题新证据时重新建立 weakpoint；
- 在 release note 中明确历史边界。

### 16.5 数据库锁与长事务

风险：状态、证据、session 和 learning event 同事务可能增加锁等待。

缓解：

- 事务前完成选题和纯函数计算；
- 事务内禁止网络/LLM/RAG；
- 稳定索引；
- PostgreSQL concurrency 和 p95 单独验收。

## 17. 回滚

回滚不得恢复“同题两次正确即可掌握”的行为。

推荐策略：

- 停止创建新的 v2 evidence chain；
- 已创建 chain 保持只读或继续完成；
- 暂停 submit/advance mutation 时仍允许安全读取今日任务和已保存反馈；
- 保留 migration 010 表与 evidence，不做生产数据删除；
- 无法安全选择独立题时继续 blocked；
- 不把 legacy `verified_correct` 重新作为 weakpoint 删除依据；
- 前端可回退展示，但 API 公开字段裁剪和服务端判分保持启用。

## 18. 完成定义

v1.38 本地 Development Complete 必须同时满足：

1. P0 同题重复正确假掌握用例先失败、实现后通过；
2. retrieval、verification、retention 状态机完成；
3. assessment ID 与 fingerprint 双重独立性完成；
4. verification 正确不会提前移除 weakpoint；
5. 至少 24 小时到期合同完成；
6. retention 正确且证据链完整后才移除 weakpoint；
7. review 与 AutoTutor 共享新 evidence 语义；
8. transaction、idempotency、concurrency 和 fault injection 通过；
9. API 和前端无答案、材料与内部证据泄露；
10. migration 010、全量回归和 clean-HEAD eval report 通过；
11. 真实 PostgreSQL、教师盲审、学生保持效果和 canary 状态被准确记录；
12. 没有把 deterministic 调度通过描述为真实学习效果。

### 18.1 2026-08-25 本地实施证据

已实现：

- Migration 010：扩展 weakpoint evidence、增加 review mastery state 与 review session revision/replay 字段；
- `retrieval → feedback → verification → retention` 状态机；
- assessment ID + semantic fingerprint 双重独立性；
- review submit/advance 的 revision、幂等重放、并发同 key、事务回滚和 fault injection；
- verification 正确只安排保持题，不删除 weakpoint；
- 注入时钟下未到期拒绝、到期优先、重复调度不重复追加；
- retention 独立且到期答对后才删除 weakpoint；
- AutoTutor 会话内 mastery 映射为 retrieval + independent evidence，并安排 retention；
- 五个 pilot 的 material-bearing retrieval 与三阶段独立题覆盖；
- 学生端“先答题 → 看对照材料 → 确认 → 独立验证题 → 明日保持提示”；
- review retrieval/verification/retention 本地观测指标，同时保留真实延迟保持为 `NOT_RUN`。

本地证据：

| 门禁 | 结果 |
|---|---:|
| `review_mastery_evidence_eval` | 3/3 PASS |
| `review_retention_scheduler_smoke` | PASS |
| `review_mastery_migration_smoke` | PASS |
| `adaptive_review_question_quality_eval` | 8/8 PASS |
| `auto_tutor_trajectory_eval` | 13/13 PASS |
| quick core eval | 65/66 suites PASS；289/290 cases；`history_character_smoke` optional skip；runner exit 0 |
| frontend unit | 8 files / 22 tests PASS |
| frontend lint | PASS |
| frontend production build | PASS |
| review Playwright real API flow | 1/1 PASS |
| `git diff --check` | PASS |

准确边界：

- clean-HEAD eval report 需要在提交 commit 后生成，本工作区阶段尚未执行；
- PostgreSQL migration/concurrency、教师盲审、初中生可理解性、真实 24 小时保持、staging 与 production canary 仍为 `NOT_RUN`；
- 注入时钟 PASS 只证明调度与证据合同，不证明真实学生已形成长期记忆。

当前完成判断：代码、Migration、本地专项门禁、quick gate 和前端真实 API 主流程已完成；状态为 **Implemented · 本地开发完成**。提交 seal 与所有外部/生产证据不在本次工作区实现结果内，继续按 `NOT_RUN` 管理。

## 19. 后续版本

v1.38 稳定后，建议顺序：

1. **v1.39 教师审定题包、版本发布与覆盖率治理**：解决五个 pilot 之外的内容可用性和独立教师审核；
2. **Runtime Product Contract Closure**：按历史人物、辩论或作文中的单一产品 Agent 纵向推进，不做全平台一次性重写；
3. **真实学习效果与间隔策略**：基于学生样本调整 retention interval，不由 LLM 任意决定。
