# EduAgent 智能体真实证据与灰度启用 v1.30 迭代 Spec

**创建时间：** 2026-08-14 10:24
**状态：** In Progress（2026-08-14 已完成工程基线；人工 reviewed/blind 数据与生产 canary 仍待外部证据）
**目标版本：** v1.30.0（证据基线）+ v1.30.1（语义路由灰度）+ v1.30.2（grounded completion）
**优先级：** P0
**适用范围：** `随问 · 学习助手`、Agent Eval、AgentOps、Release Gate；复用 v1.29 Router / Planner / Runtime、Tool Registry、会话、RAG、反馈和 Trace
**关联文档：**

- `docs/202608131651-agent-intelligence-upgrade-v129-spec.md`
- `docs/20260813-learning-assistant-free-question-spec.md`
- `docs/20260813-learning-assistant-conversation-first-ux-spec.md`
- `docs/202606291030-autotutor-autonomous-loop-dev.md`
- `docs/20260709-ai-agent-engineering-direction-confirmation.md`
- `docs/202608141136-agent-external-evidence-v130-report.md`

---

## 0. 决策摘要

v1.29 已把学习助手从“关键词分类 + 单工具调用”升级为具备以下能力的受控垂直 Agent：

- Pydantic 结构化混合路由；
- 主动澄清和 30 分钟待补槽位；
- 最多 3 步的确定性计划；
- operation allowlist、依赖校验和 fail-fast；
- 一次只读 repair；
- SSE 计划进度、会话恢复和 AgentOps 指标；
- Tool Registry 权限、风险、确认、审计和 Trace 治理。

但当前不能把“代码具备能力”直接等同于“生产智能已经达到发布标准”。本轮实测暴露出四个更高优先级的问题：

1. **离线路由高分存在模板同源风险。** 当前 300 条数据由有限基础句式加后缀生成，评测直接调用确定性规则，`300/300` 主要证明规则回归稳定，不足以证明真实学生表达下的语义理解能力。
2. **仓库默认仍未启用新能力。** `EDU_AGENT_ASSISTANT_SEMANTIC_ROUTER_ENABLED=false`、`EDU_AGENT_ASSISTANT_PLANNER_ENABLED=false`，默认用户结果仍主要依赖规则路由和单任务执行。
3. **生产证据为空或不稳定。** 当前 AgentOps 没有学习助手生产回答、真实 LLM、语义路由、计划完成和 repair 样本；并且“先取最近 N 条、再按 data_scope 过滤”的统计方式会被离线评测挤出生产事件，使 readiness 在没有生产改善时发生变化。
4. **完成验证仍过浅。** 学习助手目前主要用“回答非空 + execution 未失败”判断验证通过，没有真正验证关键陈述是否被来源支持、引用是否有效、来源之间是否冲突。

因此 v1.30 不继续增加 Agent 数量、新页面或开放式 Planner，而是完成以下闭环：

本 Spec 取代 v1.29 文档中“v1.30：上下文与记忆升级”的占位方向；上下文与记忆决策顺延至 v1.31。原因是当前更高优先级的阻塞项已经从“缺少能力”变为“已有能力尚未被真实证据验证和安全启用”。

```text
真实/人工盲测数据
  → 规则路由与真实语义路由分层评测
  → shadow 对比和人工标注
  → 稳定灰度分桶
  → 受限 Planner canary
  → 来源级答案验证
  → run-scoped 真实 LLM 发布盖章
  → AgentOps 生产样本与自动回滚信号
```

v1.30 成功的标志不是“又接入一个模型”，而是能够回答以下问题：

- 当前生产请求有多少真正经过语义路由？
- 新旧路由在什么表达上不一致，谁是正确的？
- 计划是否完成，repair 是否有效，失败是否诚实呈现？
- 回答中的关键结论是否被史料或教材支持？
- 本次发布是否在当前 commit、真实模型和生产依赖下被验证？
- 指标变好是因为用户体验改善，还是统计窗口发生了变化？

---

## 1. 当前项目实际基线

### 1.1 代码与发布状态

截至 2026-08-14：

| 项目 | 当前状态 | 结论 |
| --- | --- | --- |
| 当前 commit | `060c166` | 已与 `origin/main` 一致 |
| 工作区 | 仅 `.codex-pet-runs/` 未跟踪 | 不属于产品代码 |
| v1.29 Router / Planner / Runtime | 已实现并提交 | 工程能力存在 |
| 语义路由默认值 | `false` | 默认不改变用户路由 |
| Router shadow 默认值 | `true` | 仅在语义路由启用后生效 |
| Planner 默认值 | `false` | 默认只执行主任务 |
| 快速发布门禁 | `16/16 suites`、`368/368 cases` | 当前主路径稳定 |
| 当前意图评测 | `300/300` | 规则回归稳定，非真实语义盖章 |
| 当前 AutoTutor 轨迹 | `11/11` | 垂直教学闭环稳定 |

### 1.2 最新全量报告

`eval/reports/latest.md` 当前记录：

- `31/31 suites`；
- `453/453 cases`；
- `LLM execution: not_observed`；
- `0` 次真实 LLM 调用；
- 报告 revision 为 `d892829 dirty`，并非当前 `060c166` 的干净发布盖章。

结论：

- 全量离线能力没有红灯；
- 但报告不能证明当前 commit 的真实模型质量；
- 不得把该报告用于“v1.30 可以直接全量开启”的结论。

### 1.3 当前路由评测的证据边界

现有 300 条路由集由以下方式生成：

- 每个意图维护少量基础句；
- 通过句号、年级、语气后缀扩展；
- 数据标记为 `generated_reviewed`；
- train/dev/test 使用序号取模切分，但当前评测一次执行全部数据；
- 主指标直接调用 `deterministic_route()`；
- semantic safety 只验证少量 mock 结构化输出。

因此当前 `accuracy=1.0` 应解释为：

> 已知规则覆盖集内没有回归。

不得解释为：

> 真实学生自然表达、跨轮上下文和语义路由模型已经达到 100% 准确率。

### 1.4 当前 AgentOps 证据

本轮直接读取当前 AgentOps 窗口得到：

| 指标 | 当前值 |
| --- | ---: |
| readiness | `warn` |
| runtime trace coverage | `0%` |
| runtime audit events | `8` |
| runtime learning assistant answers | `0` |
| semantic routing events | `0` |
| planned answers | `0` |
| real LLM calls | `0` |
| runtime repair events | `0` |

同时，最新离线报告生成时的 AgentOps 曾显示：

- runtime audit events `51`；
- trace coverage `47.1%`；
- audit failures `7`；
- readiness `fail`。

运行更多 eval 后，readiness 变成 `warn`，但生产质量并未发生实际改善。根因是：

```text
list latest 100 mixed-scope events
  → eval 事件占据窗口
  → 再过滤 runtime
  → 旧 runtime 事件被挤出
  → readiness 样本量和结论漂移
```

v1.30 必须先修复这个统计契约，再使用 AgentOps 决定灰度比例。

### 1.5 当前完成验证边界

现有 learning assistant verification 主要检查：

- `response` 非空；
- `completion_status != failed`。

它尚未覆盖：

- 回答关键陈述是否被检索来源支持；
- citation/source ID 是否真实存在；
- 生成内容是否引入来源之外的年份、人物或因果；
- 多来源是否存在冲突；
- 无来源时是否正确标记 degraded / partial；
- 练习题答案是否可由教材或史料推出。

---

## 2. 迭代目标

### 2.1 产品目标

1. 在不要求学生记住固定关键词的情况下，提高真实自然表达的路由成功率。
2. 语义路由和组合 Planner 必须通过可观察、可停止、可回滚的灰度逐步启用。
3. 学习助手只能在关键结论有来源支持时把任务标记为 completed。
4. 学生仍获得简洁对话体验，不暴露内部 prompt、模型评分或复杂 Agent 术语。
5. 不因引入评测和验证而明显拉长所有简单问题的延迟。

### 2.2 工程目标

- 建立与规则模板解耦的 reviewed public set 和 blind private set。
- 将 rule、semantic shadow、semantic active、production canary 分成独立评测 profile。
- 为每次 eval 生成唯一 `eval_run_id`，真实 LLM 证据只统计当前 run。
- AgentOps 在 SQL/存储查询层先按 `data_scope` 过滤，再应用窗口限制。
- 区分 expected control flow 与 unexpected failure。
- 引入稳定灰度分桶、kill switch 和自动降级信号。
- 增加来源级 EvidenceVerification 契约和 grounded completion gate。
- 发布报告必须同时记录 commit、dirty、profile、run_id、模型、调用数、fallback 和数据集版本。

### 2.3 非目标

- 不引入开放式 LLM Planner。
- 不允许模型自由生成工具名、Python、SQL 或外部 URL。
- 不新增并行 fan-out、多 Agent 委派或 agent-as-tool。
- 不扩大到新学科、网页搜索、图片问答或文件上传。
- 不重写 AutoTutor 状态机。
- 不把学生“未解决”反馈自动等同于“路由错误”。
- 不以一个小规模离线 LLM judge 分数替代教师或人工抽检。
- 不在生产日志中持久化未脱敏的完整学生对话。

---

## 3. 成功指标

### 3.1 离线盲测指标

| 指标 | v1.30.0 门槛 | v1.30.1 门槛 | 阻断条件 |
| --- | ---: | ---: | --- |
| blind primary intent accuracy | `>= 90%` | `>= 92%` | 低于门槛 |
| blind macro-F1 | `>= 0.88` | `>= 0.90` | 低于门槛 |
| slot accuracy | `>= 88%` | `>= 92%` | 低于门槛 |
| clarification precision | `>= 85%` | `>= 88%` | 低于门槛 |
| clarification recall | `>= 80%` | `>= 85%` | 低于门槛 |
| multi-intent exact match | `>= 80%` | `>= 85%` | 低于门槛 |
| out-of-domain precision | `>= 95%` | `>= 97%` | 错误调用学习工具 |
| high-risk recall | `100%` | `100%` | 任一漏检 |
| semantic schema validity | `100%` | `100%` | 任一越界 operation |

### 3.2 Shadow 与 canary 指标

| 指标 | 10% canary 条件 | 扩大至 50% 条件 | 扩大至 100% 条件 |
| --- | ---: | ---: | ---: |
| 有效 route 样本量 | `>= 200` | `>= 500` | `>= 1000` |
| 人工抽检 routing accuracy | `>= 92%` | `>= 93%` | `>= 94%` |
| 高风险错误执行 | `0` | `0` | `0` |
| shadow disagreement 人工已标注率 | `>= 80%` | `>= 90%` | `>= 95%` |
| clarification resolution rate | `>= 65%` | `>= 70%` | `>= 75%` |
| plan completion rate | `>= 88%` | `>= 90%` | `>= 92%` |
| partial completion rate | `<= 8%` | `<= 5%` | `<= 5%` |
| semantic route p95 | `<= 800ms` | `<= 700ms` | `<= 650ms` |
| learning assistant end-to-end p95 | `<= 5s` | `<= 4.5s` | `<= 4s` |

### 3.3 Grounded completion 指标

| 指标 | 门槛 |
| --- | ---: |
| citation/source ID validity | `100%` |
| supported claim coverage | `>= 90%` |
| citation precision | `>= 95%` |
| unsupported critical claim rate | `<= 3%` |
| source conflict detection recall | `>= 90%` |
| no-source completed rate | `0%`（需要来源的 intent） |
| quiz answer groundedness | `>= 95%` |

### 3.4 生产观测指标

- runtime trace coverage `>= 95%`；
- route / plan / tool / generation / verification 能通过同一 trace_id 串联；
- AgentOps runtime 窗口不受任意数量 eval/demo 事件影响；
- expected confirmation 不计入 unexpected failure；
- 真实 LLM 调用数、模型、错误、fallback 和延迟可按 release/run 查询；
- 无样本时显示 `unknown / --`，不得显示误导性的 `0%`；
- 生产 readiness 至少连续 7 天不是 `fail`，才允许 100% 灰度。

---

## 4. 设计原则

1. **先证据，后启用。** 没有 blind + shadow + production sample，不扩大流量。
2. **规则保底，语义增益。** 明确高风险和高置信规则继续服务端直达。
3. **模型不能扩权。** semantic route 只能从已允许 intent 中选择；Planner 只能从 operation allowlist 构建。
4. **shadow 不产生副作用。** shadow 只能分类和记录，不执行工具、不写回答、不改变会话状态。
5. **完成是业务结论，不是函数返回。** completed 必须同时满足执行和证据标准。
6. **发布证据必须 run-scoped。** 历史 LLM 调用不能让当前 fallback-only run 通过。
7. **生产与评测分窗。** data_scope 必须在查询 limit 之前生效。
8. **灰度分桶稳定。** 同一学生/会话在配置不变时始终进入相同 bucket。
9. **默认可回退。** 任一新 flag 关闭后回到 v1.29 已验证路径。
10. **不优化虚假精度。** 0 样本不计算成功率，不用小样本 100% 宣布生产可用。

---

## 5. 版本拆分

### 5.1 v1.30.0：证据基线

范围：

- AgentOps data_scope 查询正确性；
- expected control flow 分类；
- eval_run_id；
- reviewed public / blind private 数据规范；
- clean revision / real LLM release seal；
- Eval UI 展示样本量、profile、commit 和 seal 状态。

发布结果：

- 不改变生产用户路由；
- semantic router 仍可保持关闭；
- 先保证所有指标可信。

### 5.2 v1.30.1：语义路由与 Planner 灰度

范围：

- stable bucket；
- semantic shadow；
- shadow disagreement 标注；
- semantic active 10% → 50% → 100%；
- Planner 仅对“解释后出题”组合任务灰度；
- kill switch 和自动降级。

发布结果：

- 简单高置信请求继续规则直达；
- 歧义、低置信、组合请求可进入 semantic；
- Planner 不扩展到未声明组合模板。

### 5.3 v1.30.2：Grounded completion

范围：

- 生成结果携带 source IDs；
- claim/citation 验证；
- conflict / no-source 判定；
- completed / partial / failed 与证据结果绑定；
- groundedness Eval 与发布门禁。

发布结果：

- 需要史料或教材支撑的回答，不再只凭“非空”判定完成。

---

## 6. 总体架构

```text
User Request
  │
  ├─ Input Guardrail / High-risk Rule
  │
  ├─ Deterministic Route ───────────────┐
  │                                    │
  ├─ Rollout Decision                  │ active baseline
  │    ├─ control                      │
  │    ├─ shadow                       │
  │    └─ semantic canary              │
  │                                    │
  ├─ Structured Semantic Route ────────┘
  │          │
  │          └─ Shadow Comparison Event（shadow 时不执行）
  │
  ├─ Slot / Clarification Gate
  │
  ├─ Deterministic Plan（最多 3 步）
  │
  ├─ Tool Registry / Generation Operation
  │
  ├─ Evidence Verification
  │    ├─ deterministic source/citation checks
  │    └─ optional structured verifier
  │
  ├─ completed / partial / waiting_confirmation / failed
  │
  └─ Trace + LearningEvent + AgentOps + Eval Candidate
```

---

## 7. 数据与契约设计

### 7.1 RolloutDecision

新增 `backend/agents/learning_assistant_rollout.py`：

```python
class RolloutDecision(BaseModel):
    schema_version: Literal[1] = 1
    route_mode: Literal["control", "shadow", "semantic_active"]
    planner_mode: Literal["control", "composition_active"]
    bucket: int = Field(ge=0, le=9999)
    semantic_percent_bps: int = Field(ge=0, le=10000)
    planner_percent_bps: int = Field(ge=0, le=10000)
    subject_type: Literal["student", "session", "request"]
    subject_hash: str
    reason_code: str
    config_version: str
```

分桶算法：

```python
seed = f"{rollout_salt}:{student_id or session_id or trace_id}"
bucket = int(sha256(seed.encode()).hexdigest()[:8], 16) % 10000
```

要求：

- 不使用 Python 内置 `hash()`；
- 日志只记录 `subject_hash`，不记录原始 student_id；
- 同一 config_version 下结果稳定；
- kill switch 优先级高于百分比；
- 高风险请求无条件使用规则 active route；
- semantic shadow 不改变 active route。

### 7.2 RoutingComparison

写入 learning event metadata，不新增独立业务表：

```json
{
  "schema_version": 1,
  "config_version": "v1.30.1-canary-01",
  "bucket": 731,
  "active_mode": "rule",
  "active_intents": ["history_search"],
  "shadow_mode": "semantic",
  "shadow_intents": ["history_search", "quiz_generation"],
  "agreement": false,
  "confidence_rule": 0.75,
  "confidence_semantic": 0.91,
  "latency_ms_semantic": 412.5,
  "label_status": "unlabeled"
}
```

约束：

- 不写入完整 prompt；
- 允许写入脱敏后的 message fingerprint 和语言特征；
- disagreement 才进入优先人工标注队列；
- `resolved/unresolved` 反馈不能自动填充 `routing_correct`。

### 7.3 EvidenceVerification

新增 `backend/agents/answer_verifier.py`：

```python
class VerifiedClaim(BaseModel):
    claim: str = Field(max_length=240)
    source_ids: list[str] = Field(default_factory=list, max_length=4)
    verdict: Literal["supported", "unsupported", "conflict", "not_applicable"]
    confidence: float = Field(ge=0, le=1)
    reason_code: str


class EvidenceVerification(BaseModel):
    schema_version: Literal[1] = 1
    mode: Literal["deterministic", "structured_verifier", "fallback"]
    required: bool
    source_count: int = Field(ge=0)
    citation_validity: float = Field(ge=0, le=1)
    supported_claim_coverage: float = Field(ge=0, le=1)
    citation_precision: float = Field(ge=0, le=1)
    unsupported_critical_claims: list[str] = Field(default_factory=list, max_length=6)
    conflicts: list[str] = Field(default_factory=list, max_length=6)
    claims: list[VerifiedClaim] = Field(default_factory=list, max_length=12)
    completion_allowed: bool
    completion_reason: str
```

`required=true` 的 intent：

- `history_search`；
- `textbook_qa`；
- `quiz_generation`；
- 组合任务中的解释和出题 generation step。

`required=false` 的 intent：

- `chat`；
- `review_plan` 中纯画像建议；
- `timeline_game` session create 结果；
- `character_recommendation` 的纯导航文案。

### 7.4 EvalRunEvidence

`eval/run_core_evals.py` 报告 schema 升级为 v3：

```json
{
  "schema_version": 3,
  "eval_run": {
    "run_id": "eval_...",
    "profile": "offline|blind|real_llm|production_canary",
    "started_at": "...",
    "finished_at": "...",
    "dataset_versions": {},
    "source_revision": {},
    "environment_fingerprint": "..."
  },
  "llm_execution": {
    "status": "observed|not_observed|not_run|failed",
    "run_scoped_calls": 0,
    "fallback_calls": 0,
    "models": {},
    "provider": "...",
    "p95_ms": null
  },
  "release_seal": {
    "status": "pass|fail|not_applicable",
    "reasons": [],
    "commit_matches": true,
    "clean_revision": true,
    "real_llm_observed": true,
    "required_profiles_passed": []
  }
}
```

真实模型调用只统计具有当前 `eval_run_id` 的事件或 suite 内部计数。禁止使用历史 AgentOps calls 为当前 run 盖章。

---

## 8. AgentOps 数据窗口修复

### 8.1 数据库迁移

新增：

```text
backend/alembic/versions/006_agent_evidence_scope.py
```

为以下表增加正式字段：

```text
audit_events.data_scope TEXT NOT NULL DEFAULT 'runtime'
learning_events.data_scope TEXT NOT NULL DEFAULT 'runtime'
```

增加索引：

```text
idx_audit_events_scope_created_at(data_scope, created_at)
idx_learning_events_scope_created_at(data_scope, created_at)
idx_learning_events_feature_type_created_at(feature, event_type, created_at)
```

兼容策略：

- migration 前的历史记录回填为 `runtime`；
- 过渡期读取优先使用列，列不可用时回退 metadata.data_scope；
- 写入同时设置列和 metadata，持续一个版本；
- v1.31 再移除 metadata fallback。

### 8.2 查询顺序

所有统计必须遵循：

```sql
SELECT ...
FROM events
WHERE data_scope = :scope
  AND created_at >= :since
ORDER BY created_at DESC
LIMIT :limit
```

禁止：

```text
先 LIMIT 混合 scope → Python 再过滤
```

### 8.3 Outcome 分类

新增标准字段：

```python
OutcomeClass = Literal[
    "success",
    "expected_control",
    "user_denied",
    "degraded",
    "unexpected_failure",
]
```

默认映射：

| action / result | outcome_class | readiness 失败计数 |
| --- | --- | ---: |
| `tool.allowed` | success | 否 |
| `tool.confirmation_required` | expected_control | 否 |
| 合法 guardrail block | expected_control | 否 |
| 用户取消确认 | user_denied | 否 |
| RAG 空结果后安全 fallback | degraded | 告警，不直接失败 |
| provider timeout | unexpected_failure | 是 |
| schema invalid | unexpected_failure | 是 |
| role bypass / confirmation bypass | unexpected_failure | 是，P0 |

### 8.4 Readiness 样本量

readiness 输出增加：

```json
{
  "status": "unknown|warn|pass|fail",
  "sample_sufficient": false,
  "runtime_event_count": 0,
  "minimum_runtime_events": 100,
  "window_hours": 24,
  "reasons": []
}
```

规则：

- 无样本或样本不足时为 `unknown`，不能为 `pass`；
- 安全违规、确认绕过、schema 越界不受样本量豁免，直接 `fail`；
- trace coverage `< 80%` 为 `warn`，`< 50%` 且样本充足为 `fail`；
- expected_control 不降低 tool success rate；
- runtime/eval/demo 分别显示样本数和窗口。

---

## 9. 真实盲测数据设计

### 9.1 数据分层

| 数据层 | 是否入库 | 是否对开发者可见 | 用途 |
| --- | --- | --- | --- |
| generated regression | 是 | 是 | 防止已知规则回归 |
| reviewed public | 是 | 是 | 日常开发与错误分析 |
| blind private | 否 | 否/仅 CI | 版本验收 |
| production anonymized | 否 | 受限 | 回归候选与真实分布分析 |

新增公开数据：

```text
eval/datasets/learning_assistant_reviewed_public_v1.jsonl
```

私有盲测通过以下路径注入：

```text
EDU_AGENT_BLIND_EVAL_PATH=/secure/path/learning_assistant_blind_v1.jsonl
```

私有文件不得提交到仓库或 CI artifact。

### 9.2 初始数据规模

首期合计至少 500 条唯一基础表达，其中 reviewed public 不少于 300 条、blind private 不少于 200 条；禁止用后缀机械扩充计入唯一样本：

- 单意图不少于 280 条；
- 多意图不少于 80 条；
- 多轮/指代不少于 100 条；
- out-of-domain / negative 不少于 50 条；
- 错别字、口语、短句、省略不少于 100 条；
- prompt injection / tool 越权不少于 30 条；
- 高风险表达不少于 30 条；
- 话题切换不少于 40 条；
- 无法判断、应澄清不少于 50 条。

类别允许重叠，但每条必须有明确 `challenge_tags`。

### 9.3 数据格式

```json
{
  "id": "reviewed_v1_0001",
  "source": "human_authored|production_anonymized|expert_rewrite",
  "split": "dev|test",
  "locale": "zh-CN",
  "request": {
    "message": "先把刚才那个运动讲明白，再考我两道",
    "conversation_history": [],
    "source_context": {}
  },
  "expected": {
    "primary_intent": "history_search",
    "intents": ["history_search", "quiz_generation"],
    "slots": {"count": 2},
    "needs_clarification": false,
    "allowed_operations": ["search_history_knowledge", "answer_from_sources", "quiz_from_sources"],
    "forbidden_operations": []
  },
  "challenge_tags": ["ellipsis", "multi_turn", "multi_intent"],
  "label": {
    "reviewer_count": 2,
    "adjudicated": true,
    "notes": ""
  }
}
```

### 9.4 标注质量

- 每条至少两名标注者；
- 意图一致性 Cohen's kappa `>= 0.80`；
- 分歧由第三人裁决；
- 不明确样本允许标为 `needs_clarification`，不强行分配 intent；
- 生产样本进入标注前必须去标识化；
- 不允许将学生姓名、学校、联系方式、完整 session 内容写入数据集。

---

## 10. 语义路由 Shadow 与灰度

### 10.1 路由顺序

保持 v1.29 安全优先级：

1. prompt injection / input guardrail；
2. 高风险服务端规则；
3. 明确高置信规则；
4. rollout decision；
5. 歧义、低置信、澄清或组合请求调用 semantic router；
6. Pydantic 校验和 semantic sanitizer；
7. 低置信继续澄清；
8. semantic 不可用时回到规则结果。

### 10.2 Shadow 模式

shadow 请求可以：

- 调用结构化语义路由；
- 记录 latency、confidence、schema validity；
- 对比 intent、slot、clarification 和 task order；
- 生成 routing comparison event。

shadow 请求禁止：

- 执行 shadow route 中的任何工具；
- 写入第二条 assistant message；
- 修改 pending clarification；
- 修改 AutoTutor revision、attempts 或当前步骤；
- 产生高风险 confirmation token；
- 将 shadow 结果作为 active plan 输入。

### 10.3 Canary 激活条件

只允许以下请求进入 semantic active：

- 非高风险；
- bucket 命中；
- semantic router 配置正常；
- rule route 属于 fallback、低置信、needs_clarification 或多意图；
- 最近 24 小时没有 P0 安全告警；
- 当前 config_version 没有被 kill switch 禁用。

### 10.4 Planner 灰度

v1.30 只灰度现有稳定组合：

```text
history/textbook explanation
  → quiz_generation
```

以下组合继续不支持：

- 两个高风险操作；
- 游戏创建后继续写操作；
- review plan + memory write；
- 任意自由组合三个工具；
- 模型生成 operation 名；
- 未通过 allowlist 的 MCP/tool。

### 10.5 自动停止条件

任一条件触发后将 active percent 设为 0，保留 shadow：

- 任一高风险错误执行；
- semantic schema invalid > 0；
- routing accuracy 低于 control 3 个百分点；
- plan partial rate > 10%；
- p95 延迟高于 control 50% 且持续 30 分钟；
- provider error rate > 5%；
- unexpected tool failure rate > 5%；
- trace coverage < 80% 且持续 30 分钟；
- 人工设置 kill switch。

---

## 11. Grounded Completion 设计

### 11.1 来源标准化

所有 RAG / textbook source 统一最小字段：

```json
{
  "source_id": "src_...",
  "source_type": "history_kb|textbook|material",
  "title": "...",
  "snippet": "...",
  "metadata": {
    "book_id": null,
    "lesson_id": null,
    "page": null,
    "topic": null
  }
}
```

source_id 必须由服务端生成，模型不得自造。

### 11.2 生成结果

generation operation 内部结果扩展：

```json
{
  "ok": true,
  "response": "...",
  "citations": [
    {"claim": "...", "source_ids": ["src_1"]}
  ],
  "generation_mode": "llm|fallback|template",
  "source_ids_used": ["src_1"]
}
```

对现有 SSE 文本保持兼容；citation 和 verification 通过结构化事件及 final metadata 传递。

### 11.3 两层验证

第一层：确定性检查，所有请求执行。

- source_id 是否属于当前 tool output；
- 必须引用的 intent 是否至少有一个来源；
- citation 是否引用空 snippet；
- quiz 数量、答案和解析字段是否完整；
- 教材回答是否使用当前 book_id / lesson_id；
- 回答为空或只包含兜底套话时不得 completed。

第二层：结构化 verifier，按 flag/canary 执行。

- 抽取最多 12 个关键 claim；
- 判断 supported / unsupported / conflict；
- 计算 supported claim coverage 和 citation precision；
- 只接收 Pydantic 结果；
- verifier 异常不把未验证回答升级为 completed。

### 11.4 Completion 映射

| execution | verification | 最终状态 |
| --- | --- | --- |
| completed | completion_allowed | completed |
| completed | unsupported critical claim | partial |
| completed | no source but source required | partial |
| partial | 任意 | partial |
| failed | 任意 | failed |
| waiting_confirmation | 不执行 verifier | waiting_confirmation |

partial 文案必须说明：

- 哪一步没有完成；
- 是否缺少来源；
- 学生可以怎样补充教材或换一种问法；
- 不展示内部模型分数。

---

## 12. 真实 LLM 发布盖章

### 12.1 Profile

新增评测 profile：

```text
offline          不要求真实 LLM，验证确定性回归
blind            使用私有 blind set，可使用真实 router
real_llm         必须执行当前 run 的真实 LLM suite
production_canary 读取指定生产时间窗指标，不写产品数据
```

### 12.2 Real LLM 必跑场景

- 语义路由歧义请求；
- 多意图路由；
- history grounded answer；
- textbook grounded answer；
- quiz generation；
- AutoTutor teaching + reteach；
- provider timeout/fallback；
- prompt injection in retrieved source；
- structured output invalid/repair；
- verifier supported/unsupported/conflict。

### 12.3 Release seal 条件

`release_seal.status=pass` 必须同时满足：

- 当前 working tree clean；
- report commit 等于当前 HEAD；
- offline core 全部通过；
- blind profile 达标；
- real_llm profile 达标；
- 当前 eval_run_id 的真实 LLM calls > 0；
- fallback-only run 不通过；
- required suite 无 skipped / not_run；
- source revision、dataset version、provider 和 model 均可追溯；
- production readiness 若为 release required，则不能为 fail。

### 12.4 CI 策略

PR CI：

- offline quick/core；
- frontend lint/unit/build；
- browser E2E；
- 不依赖生产密钥；
- 明确显示 `release_seal=not_applicable`。

Nightly / workflow_dispatch：

- blind private；
- real_llm；
- production readiness；
- 上传不含原始私有数据的聚合报告；
- 失败时阻止版本盖章，但不在 PR 日志输出 secrets 或原始 prompt。

---

## 13. API 与 SSE 兼容

### 13.1 Chat API

`POST /api/learning/assistant/chat` 请求保持兼容，不新增必填字段。

内部可以从以下字段选择 rollout subject：

1. `student_id`；
2. `session_id`；
3. `trace_id`。

### 13.2 Route 事件扩展

现有 `route` 事件增加可选字段：

```json
{
  "schema_version": 3,
  "mode": "rule|semantic|fallback|clarification",
  "tasks": [],
  "confidence": 0.91,
  "rollout": {
    "route_mode": "shadow",
    "bucket": 731,
    "config_version": "v1.30.1-canary-01"
  },
  "shadow": {},
  "agreement": false
}
```

旧前端继续读取既有字段，忽略新增字段。

### 13.3 Evidence 事件

新增 SSE：

```text
evidence_start
evidence_result
```

`evidence_result` 对学生前端只暴露：

```json
{
  "status": "supported|partial|not_required",
  "source_count": 3,
  "has_conflict": false,
  "completion_allowed": true
}
```

详细 claim、内部 confidence 和 verifier reason 只进入 trace/Eval 页面。

### 13.4 Final 事件

新增可选：

```json
{
  "verification_summary": {
    "status": "supported|partial|not_required",
    "source_count": 3,
    "citation_count": 2,
    "completion_allowed": true
  },
  "rollout_summary": {
    "route_mode": "semantic_active",
    "planner_mode": "composition_active",
    "config_version": "v1.30.1-canary-01"
  }
}
```

现有 `intent`、`response`、`completion_status`、`routing`、`plan_summary` 保持不变。

### 13.5 AgentOps API

扩展：

```http
GET /api/agent-ops/summary?scope=runtime&window_hours=24&limit=100
```

约束：

- `scope` 只能是 runtime/eval/demo；
- 非教师/管理员不可访问；
- 返回实际样本量和 minimum sample；
- scope 在查询层生效；
- 不返回原始学生输入。

### 13.6 Eval API

`EvalRunRequest` 增加：

```python
profile: Literal["offline", "blind", "real_llm"] = "offline"
require_clean_revision: bool = False
require_release_seal: bool = False
```

生产环境的 real_llm / release seal 仅管理员可触发。

---

## 14. 前端改动

### 14.1 学习助手页

保持对话优先，不新增复杂控制面板。

用户可见：

- 已使用资料来源；
- “依据不足，先给出可确认部分”的 partial 提示；
- 来源冲突时的温和提示；
- 现有计划步骤和完成状态。

用户不可见：

- rollout bucket；
- semantic/control 分组；
- 模型 confidence；
- verifier prompt；
- 内部 reason_code。

### 14.2 Eval 页面

新增卡片：

- Release Seal；
- 当前 commit / report commit / dirty；
- dataset version；
- run-scoped real LLM calls；
- runtime/eval/demo 独立样本量；
- shadow agreement 和 disagreement label coverage；
- semantic active percent；
- Planner active percent；
- grounded completion 指标；
- rollback reason。

无样本指标统一显示 `--`，不得显示 `0%`。

### 14.3 人工标注

Eval 页面只对 teacher/admin 增加 disagreement 标注：

- active 正确；
- shadow 正确；
- 两者都不正确；
- 应澄清；
- corrected primary intent；
- 可选短备注。

学生端“解决了 / 换种方式讲”保持不变，不增加标注负担。

---

## 15. Feature Flags

新增/调整 `.env.example`：

```dotenv
# v1.30 rollout
EDU_AGENT_ASSISTANT_ROLLOUT_CONFIG_VERSION=v1.30-control
EDU_AGENT_ASSISTANT_ROLLOUT_SALT=replace-in-production
EDU_AGENT_ASSISTANT_SEMANTIC_ROUTER_ENABLED=false
EDU_AGENT_ASSISTANT_ROUTER_SHADOW_MODE=true
EDU_AGENT_ASSISTANT_SEMANTIC_PERCENT_BPS=0
EDU_AGENT_ASSISTANT_PLANNER_ENABLED=false
EDU_AGENT_ASSISTANT_PLANNER_PERCENT_BPS=0
EDU_AGENT_ASSISTANT_ROLLOUT_KILL_SWITCH=false

# Evidence verification
EDU_AGENT_ANSWER_VERIFIER_ENABLED=false
EDU_AGENT_ANSWER_VERIFIER_PERCENT_BPS=0
EDU_AGENT_ANSWER_MIN_SUPPORTED_COVERAGE=0.90
EDU_AGENT_ANSWER_MIN_CITATION_PRECISION=0.95

# AgentOps windows
EDU_AGENT_OPS_RUNTIME_WINDOW_HOURS=24
EDU_AGENT_OPS_MIN_RUNTIME_EVENTS=100

# Eval evidence
EDU_AGENT_BLIND_EVAL_PATH=
EDU_AGENT_REQUIRE_CLEAN_RELEASE_REVISION=true
```

优先级：

```text
kill switch
  > high-risk rule
  > enabled flag
  > stable percentage bucket
  > router confidence
```

生产 `ROLLOUT_SALT` 必须通过 secret 配置，不提交真实值。

---

## 16. Trace 与指标

### 16.1 新增 Trace 事件

| event_type | 用途 |
| --- | --- |
| `rollout_decision` | 记录 bucket/config/mode |
| `semantic_route_shadow` | shadow 结果，不执行 |
| `routing_comparison` | active/shadow agreement |
| `evidence_verify_start` | 开始来源验证 |
| `evidence_verify_result` | groundedness 结果 |
| `release_eval_llm_call` | 当前 eval_run 的 LLM 证据 |
| `rollout_auto_stop` | 自动停止原因 |

### 16.2 必备 metadata

- `trace_id`；
- `data_scope`；
- `config_version`；
- `route_mode`；
- `planner_mode`；
- `eval_run_id`（仅 eval）；
- `model` / `provider`（LLM step）；
- `latency_ms`；
- `outcome_class`；
- `completion_status`；
- `source_count`；
- `verification_status`。

### 16.3 禁止记录

- API key/token；
- 完整 authorization header；
- 未脱敏学生姓名和联系方式；
- 私有 blind 样本原文；
- 完整 system prompt；
- confirmation secret；
- 未截断的教材全文。

---

## 17. 评测方案

### 17.1 新增 suite

```text
eval/learning_assistant_reviewed_eval.py
eval/learning_assistant_blind_eval.py
eval/learning_assistant_semantic_router_eval.py
eval/learning_assistant_shadow_smoke.py
eval/learning_assistant_rollout_smoke.py
eval/answer_groundedness_eval.py
eval/agent_ops_scope_smoke.py
eval/real_llm_release_eval.py
```

### 17.2 AgentOps scope cases

必须覆盖：

1. 插入 150 条 runtime，再插入 1000 条 eval，runtime limit=100 仍返回最近 100 条 runtime；
2. demo 不影响 runtime readiness；
3. confirmation_required 计为 expected_control；
4. provider timeout 计为 unexpected_failure；
5. 0 样本 readiness=unknown；
6. 样本不足不能 pass；
7. trace coverage 使用 runtime 分母；
8. 时间窗过滤在 limit 前生效；
9. legacy metadata scope 能兼容读取；
10. data scope migration 回填正确。

### 17.3 Rollout cases

- 同一 student 100 次分桶一致；
- 不同进程分桶一致；
- 0/10%/50%/100% 边界正确；
- kill switch 强制 control；
- 高风险请求强制 rule；
- shadow 不调用 tool；
- shadow 不产生第二条 assistant message；
- Planner 百分比独立于 Router；
- config_version 变化可重新分桶；
- 无 student/session 时使用 trace_id，且记录 subject_type=request。

### 17.4 Groundedness cases

- 有效 source ID；
- 伪造 source ID；
- 无来源回答；
- 部分 claim 支持；
- 关键年份不被支持；
- 两个来源冲突；
- 教材 lesson 不匹配；
- quiz 答案不可由来源推出；
- verifier timeout；
- fallback answer；
- prompt injection source；
- citation 重复和空引用。

### 17.5 Real LLM cases

- 当前 run 产生真实调用；
- 历史 LLM calls 不能让当前 run 通过；
- fallback-only 必须 fail release seal；
- provider credential 缺失为 NOT_RUN，不是 PASS；
- quota/timeout 区分 infra failure；
- invalid structured output 可控失败；
- model/provider 被写入报告；
- raw prompt 不进入报告。

### 17.6 前端测试

Unit：

- 无样本显示 `--`；
- release seal 状态；
- partial evidence 提示；
- source count；
- rollout 字段缺失时兼容 v1.29。

Playwright：

- history answer 显示来源状态；
- no-source 返回 partial；
- explain + quiz Planner canary；
- shadow 模式用户只看到一个答案；
- Eval 页面 runtime/eval 分窗；
- teacher disagreement 标注。

---

## 18. Release Gate

### 18.1 快速门禁

`scripts/release_gate.py --fast` 增加：

- `agent_ops_scope_smoke`；
- `learning_assistant_rollout_smoke`；
- `learning_assistant_shadow_smoke`；
- deterministic groundedness smoke。

目标：保持 60 秒左右，不调用真实 LLM。

### 18.2 完整离线门禁

必须包括：

- 当前 CORE suites；
- reviewed public eval；
- AgentOps scope；
- rollout；
- groundedness；
- 前端 lint/unit/build；
- Playwright。

### 18.3 发布盖章命令

建议统一入口：

```bash
PYTHONPATH=backend python3 eval/run_core_evals.py \
  --profile real_llm \
  --require-real-llm \
  --require-clean-revision \
  --require-release-seal
```

私有 blind：

```bash
EDU_AGENT_BLIND_EVAL_PATH=/secure/path/blind.jsonl \
PYTHONPATH=backend python3 eval/run_core_evals.py \
  --profile blind \
  --require-real-llm \
  --require-clean-revision
```

### 18.4 生产 readiness

继续使用：

```bash
npm run release:gate:prod -- \
  --skip-frontend \
  --ready-url https://<backend>/api/ready
```

v1.30 增加：

- deployed release/version 与 report commit 对比；
- runtime sample sufficiency；
- trace coverage；
- unexpected failure；
- semantic/planner active percent；
- kill switch 状态；
- 最近 release seal。

---

## 19. 安全与隐私

1. semantic router 只能返回 `IntentName` allowlist。
2. semantic sanitizer 继续移除 `memory_delete_demo`。
3. 高风险 route 不参与 semantic active。
4. Planner operation 必须在服务端 allowlist。
5. Evidence verifier 不执行工具，只读取本次步骤输出。
6. shadow 不执行、不确认、不写产品状态。
7. rollout subject 使用 hash，不在 trace 记录 student_id 原文。
8. production candidate 默认只保存脱敏特征和 trace_id。
9. 私有 blind 数据不得进入报告、PR 评论或 artifact。
10. 教师标注 API 必须鉴权和审计。
11. 生产 rollout salt、LLM secret、blind path 不入库。
12. 模型/验证器超时必须走安全 fallback，不阻断简单规则请求。

---

## 20. 文件改动清单

### 20.1 新增文件

| 文件 | 内容 |
| --- | --- |
| `backend/agents/learning_assistant_rollout.py` | 稳定分桶、kill switch、RolloutDecision |
| `backend/agents/answer_verifier.py` | EvidenceVerification 与两层验证 |
| `backend/alembic/versions/006_agent_evidence_scope.py` | data_scope 列和索引 |
| `eval/learning_assistant_reviewed_eval.py` | reviewed public eval |
| `eval/learning_assistant_blind_eval.py` | 私有 blind loader/eval |
| `eval/learning_assistant_semantic_router_eval.py` | 真实 semantic profile |
| `eval/learning_assistant_shadow_smoke.py` | shadow 无副作用 |
| `eval/learning_assistant_rollout_smoke.py` | bucket/kill switch |
| `eval/answer_groundedness_eval.py` | claim/citation/conflict |
| `eval/agent_ops_scope_smoke.py` | filter-before-limit 契约 |
| `eval/real_llm_release_eval.py` | run-scoped LLM seal |
| `eval/datasets/learning_assistant_reviewed_public_v1.jsonl` | 非模板公开评测集 |

### 20.2 修改文件

| 文件 | 改动 |
| --- | --- |
| `backend/agents/learning_assistant_router.py` | rollout 接入、semantic timing、comparison metadata |
| `backend/agents/learning_assistant_planner.py` | composition canary，不扩 operation |
| `backend/agents/learning_assistant_runtime.py` | evidence gate 和 verification completion |
| `backend/agents/learning_assistant.py` | SSE、final、run/config metadata |
| `backend/api/routers/learning.py` | 持久化 rollout/verification metadata |
| `backend/security/audit_log.py` | data_scope/outcome_class 列写入与查询 |
| `backend/student_profile.py` | learning event data_scope 查询 |
| `backend/agent_ops.py` | scope-first 窗口、样本量、expected control |
| `backend/api/routers/eval_ops.py` | profile、scope、release seal、标注 API |
| `eval/run_core_evals.py` | schema v3、eval_run_id、profile、seal |
| `scripts/release_gate.py` | 新 suite 和 release seal 参数 |
| `frontend/app/learning-assistant/page.tsx` | 来源/partial evidence 展示 |
| `frontend/app/eval/page.tsx` | seal、scope、rollout、groundedness |
| `frontend/components/learningAssistantComposer.ts` | evidence/rollout event helper |
| `frontend/e2e/core-flows.spec.ts` | shadow/partial/label E2E |
| `.github/workflows/ci.yml` | nightly real LLM/blind workflow |
| `.env.example` | v1.30 flags |
| `README.md` | 灰度和发布盖章命令 |
| `SCHEMA.md` | 表、API、事件、测试、环境变量 |

### 20.3 明确不修改

- AutoTutor 核心教学状态机；
- Tool Registry 现有风险/权限语义；
- 学生端导航结构；
- 现有 chat API 必填请求字段；
- 现有高风险 confirmation token 协议。

---

## 21. 实施顺序

### Milestone A：可信指标（预计 3–4 天）

1. 增加 data_scope 正式列和索引。
2. 修改 audit/learning event 查询为 scope-first。
3. 增加 outcome_class。
4. 修复 readiness 样本量语义。
5. 增加 `agent_ops_scope_smoke`。
6. Eval 页面显示 scope 窗口和样本量。
7. 保持 semantic/planner 关闭。

退出条件：

- 1000 条 eval 不改变 runtime 最近 100 条；
- expected confirmation 不再让 readiness fail；
- 0 样本显示 unknown；
- fast gate 全绿。

### Milestone B：盲测与 run-scoped seal（预计 3–4 天）

1. 定义 reviewed/blind JSONL schema。
2. 建立首批非模板 reviewed public 数据。
3. 接入私有 blind path。
4. 增加 eval_run_id。
5. 真实 LLM 调用按 run 统计。
6. 报告 schema v3 和 release seal。
7. CI 增加 nightly/workflow_dispatch profile。

退出条件：

- blind 指标达到 v1.30.0 门槛；
- 历史 LLM calls 无法让当前 run 通过；
- dirty/mismatch commit 无法获得 release seal；
- 私有数据不进入 artifact。

### Milestone C：Shadow 与 10% Canary（预计 3–4 天）

1. 实现稳定 bucket 和 config version。
2. semantic shadow 比较事件。
3. disagreement 标注 API/UI。
4. 运行至少 200 条有效 shadow 样本。
5. 达标后语义路由开启 10%。
6. Planner 只对 explain→quiz 开启 10%。
7. 验证 kill switch。

退出条件：

- shadow 无副作用；
- 人工 routing accuracy 达标；
- 高风险错误为 0；
- trace coverage 达标；
- 10% canary 连续运行至少 48 小时无 P0。

### Milestone D：Grounded Completion（预计 4–5 天）

1. 统一 source ID。
2. generation result 增加 citation。
3. 确定性验证。
4. structured verifier 灰度。
5. completion status 绑定 verification。
6. groundedness eval 和前端提示。
7. real LLM release seal 重跑。

退出条件：

- required intent 无来源时不再 completed；
- citation validity 100%；
- supported coverage / precision 达标；
- latency和成本未越过 SLO；
- CORE、fast、frontend、E2E 无回归。

---

## 22. 验收清单

2026-08-14 本地工程验收补充证据：

- Grounded Completion 确定性契约 `9/9`：伪造 ID、引用原文错配、关键声明无支持均被拒绝，结构化来源冲突降为 `partial`；可交付样本的 citation validity、supported claim coverage、citation precision 均为 `100%`，unsupported critical claim rate 为 `0%`。
- Eval report smoke 已覆盖 commit 新鲜度、provider/model/dataset hash 追溯、常见 secret 脱敏和 blind 原始输出封闭。
- Planner 合成路径只接受严格的 explain→quiz 顺序；其他多任务组合回到主任务单步计划。
- 本轮 fast gate 为 `20/20 suites`、`377/377 cases`，CORE 为 `35/35 suites`、`462/462 cases`；前端 lint、`11/11` unit、50 routes build 和 Playwright `7/7` 全绿。
- 以下已勾选项仅代表本地可重复工程证据；人工 blind、真实 LLM、生产 shadow/canary 和 runtime trace coverage 仍不得由离线结果替代。

### 22.1 AgentOps

- [x] data_scope 在查询 limit 前生效。
- [x] runtime/eval/demo 分别有独立样本量。
- [x] 1000 条 eval 不挤出 runtime 窗口。
- [x] confirmation_required 属于 expected_control。
- [x] 0 样本 readiness=unknown。
- [x] 样本不足不能显示 pass。
- [ ] runtime trace coverage `>=95%` 后才允许 100% 灰度。
- [x] AgentOps API 不返回原始学生输入。

### 22.2 数据与评测

- [ ] reviewed public 至少 300 条唯一人工表达。
- [ ] blind private 至少 200 条，public + private 合计至少 500 条。
- [ ] blind 数据不由后缀机械扩充。
- [ ] 双人标注 kappa `>=0.80`。
- [ ] blind primary accuracy `>=90%`。
- [ ] blind macro-F1 `>=0.88`。
- [ ] high-risk recall `=100%`。
- [ ] out-of-domain precision `>=95%`。
- [ ] 私有数据不进入 Git/CI artifact。

### 22.3 真实 LLM 与报告

- [x] 每次 eval 有唯一 eval_run_id。
- [x] LLM calls 只统计当前 run。
- [x] fallback-only 不能获得 release seal。
- [x] credential 缺失标记 NOT_RUN。
- [x] dirty revision 不能获得 release seal。
- [x] report commit 必须等于当前 HEAD。
- [x] 模型、provider、dataset version 可追溯。
- [x] 报告不包含 secrets 和私有 prompt。

### 22.4 Shadow 与灰度

- [x] 稳定分桶跨进程一致。
- [x] shadow 不调用工具。
- [x] shadow 不写第二条回答。
- [x] high-risk 始终规则直达。
- [x] kill switch 能立即回到 control。
- [ ] 10% canary 有至少 200 条有效样本。
- [ ] 人工 routing accuracy `>=92%`。
- [ ] 高风险错误执行为 0。
- [x] Planner 只开放 explain→quiz。
- [ ] partial rate `<=8%`。

### 22.5 Grounded Completion

- [x] 所有 required intent 输出标准 source ID（通过 `verification_summary.source_ids`）。
- [x] 伪造 source ID 被拒绝。
- [x] no-source required answer 不得 completed。
- [x] citation validity `=100%`。
- [x] supported claim coverage `>=90%`。
- [x] citation precision `>=95%`。
- [x] unsupported critical claim rate `<=3%`。
- [x] source conflict 被识别并呈现 partial。
- [x] verifier 异常不会错误升级完成状态。

### 22.6 回归与体验

- [x] v1.29 Router/Planner/Runtime 兼容测试通过。
- [x] AutoTutor trajectory `11/11` 或更高。
- [x] 学习助手多轮和 AutoTutor handoff 不回退。
- [x] 当前 fast gate 基线不回退（本轮扩展后 `20/20 suites`、`377/377 cases`）。
- [x] 当前 CORE 基线不回退（本轮扩展后 `35/35 suites`、`462/462 cases`）。
- [x] 前端 lint/unit/build 通过。
- [x] Playwright 核心 E2E `7/7` 通过。
- [x] 用户端不展示 bucket、confidence、内部 reason_code。

### 22.7 补充外部证据（不替代中文 blind）

- [x] 使用 Eedi QATD-2k test 的真实学生消息完成聚合型 OOD 探针。
- [x] 3,453 条去重学生消息中，3,453 条保持 chat 路由，错误工具路由为 0，OOD precision=100%。
- [x] 原始数据仅位于仓库外临时目录，报告仅保存来源、许可、哈希和聚合指标。
- [ ] 该英文数学数据不计入中文 in-domain blind accuracy / macro-F1，也不解除真实 LLM 和生产 canary 阻塞。

---

## 23. 回滚方案

### 23.1 语义路由回滚

```dotenv
EDU_AGENT_ASSISTANT_ROLLOUT_KILL_SWITCH=true
EDU_AGENT_ASSISTANT_SEMANTIC_PERCENT_BPS=0
EDU_AGENT_ASSISTANT_ROUTER_SHADOW_MODE=true
```

效果：

- active 立即回到规则路由；
- 可以保留 shadow 收集证据；
- 不修改会话 API 和历史 message。

### 23.2 Planner 回滚

```dotenv
EDU_AGENT_ASSISTANT_PLANNER_PERCENT_BPS=0
EDU_AGENT_ASSISTANT_PLANNER_ENABLED=false
```

效果：

- 只执行主任务；
- 保留 v1.29 单任务 plan/runtime；
- 不影响 Tool Registry。

### 23.3 Verifier 回滚

```dotenv
EDU_AGENT_ANSWER_VERIFIER_PERCENT_BPS=0
EDU_AGENT_ANSWER_VERIFIER_ENABLED=false
```

效果：

- 停止 structured verifier；
- 保留确定性 source ID、no-source 和 citation validity 检查；
- 不允许完全回滚到“只检查非空”的旧 completion 语义，除非紧急 hotfix 明确记录。

### 23.4 数据库回滚

- 新 data_scope 列为 additive，不影响旧读取；
- 应用回滚时旧版本忽略新增列；
- 不在紧急回滚中删除列或索引；
- migration downgrade 仅在维护窗口执行。

---

## 24. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| blind 数据泄漏 | 指标失真 | 私有路径、最小权限、报告只传聚合结果 |
| semantic router 延迟 | 对话变慢 | 仅歧义请求调用、timeout、fast model、稳定 fallback |
| shadow 误产生副作用 | 重复写入/确认 | 独立纯分类函数、无 ToolRunner、专项 smoke |
| 分桶不稳定 | 用户体验跳变 | SHA-256 + config_version，禁止内置 hash |
| verifier 自身幻觉 | 错误降级/升级 | 确定性检查优先、结构化 schema、人工抽检 |
| 过度验证简单聊天 | 成本和延迟 | required intent 白名单，chat 不验证 |
| expected control 被算失败 | readiness 假红 | outcome_class 标准化 |
| eval 挤出生产窗口 | readiness 漂移 | data_scope 列、WHERE before LIMIT |
| 历史 LLM 调用让新 run 误通过 | 假发布盖章 | eval_run_id、suite 内计数 |
| 小样本 100% | 错误扩大灰度 | minimum sample + 置信区间 + 连续时间门槛 |
| fallback 掩盖 provider 故障 | 质量下降未发现 | fallback rate、run-scoped model status、seal 阻断 |
| 人工标注成本高 | disagreement 积压 | 只优先 disagreement/低置信/P0 样本 |
| production 日志泄露学生信息 | 合规风险 | 去标识化、hash subject、不记录原始 prompt |

---

## 25. 后续版本边界

以下内容留给 v1.31 及以后，不阻塞 v1.30：

### v1.31：上下文与记忆决策

- 滚动会话摘要；
- 未解决目标和实体状态；
- memory 冲突、过期和置信度衰减；
- 让可信 weak point/learning preference 影响计划，而不只是建议语；
- memory 使用效果评测。

### v1.32：教学效果与策略学习

- 前测、退出票、24 小时后测；
- 掌握概率模型；
- 教学策略 A/B；
- 7 天保持率和重复错误率；
- 教师接管率。

### v1.33：更通用的受控 Runtime

- durable composite plan；
- 一次受限动态 replan；
- 并行只读 fan-out；
- 多 MCP server routing；
- agent-as-tool；
- 长任务预算和恢复。

上述能力只有在 v1.30 的真实证据、生产窗口和 release seal 稳定后才进入开发。

---

## 26. 最终成功定义

v1.30 完成后，EduAgent 应达到以下状态：

1. 规则回归、真实盲测、真实模型和生产 canary 是四套明确分层的证据，互不冒充。
2. 语义路由和 Planner 可以按稳定 bucket 灰度，并能通过 kill switch 立即回退。
3. AgentOps 的 runtime 指标不再受 eval/demo 数量影响。
4. readiness 能区分无样本、expected control、degraded 和 unexpected failure。
5. 当前 release 的 LLM 质量只能由当前 eval_run_id 和当前 commit 证明。
6. 需要来源的回答只有在关键结论被支持时才标记 completed。
7. 学生仍获得简洁、连续、可解释的学习体验。
8. AutoTutor、Tool Registry、安全确认和既有发布门禁不回退。

达到以上标准后，EduAgent 才从“具备智能能力的受控垂直 Agent”进一步升级为“智能能力已被真实数据验证、可在生产灰度、可按证据发布的教育 Agent”。
