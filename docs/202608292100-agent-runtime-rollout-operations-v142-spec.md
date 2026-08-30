# EduAgent Runtime v2 灰度操作面与 Shadow 晋级闭环 v1.42 Spec

**日期：** 2026-08-29  
**状态：** Implemented / Operational `NOT_RUN`  
**优先级：** P0  
**目标 Agent：** `history_character`  
**前置文档：**

- `docs/202608280000-agent-runtime-langgraph-boundary-adr.md`
- `docs/202608281554-agent-runtime-rollout-evidence-v139-spec.md`
- `docs/202608281900-agent-runtime-production-evidence-v140-spec.md`
- `docs/202608291701-agent-runtime-production-shadow-v141-spec.md`

## 0. 执行摘要

v1.41 已完成 Runtime v2 生产迁移、Run provenance、rollout observation、hash-bound evidence、strict readiness 与 GitHub Actions 证据工作流。当前生产环境已经从“部署不可用”进入“可用但尚未获得 Runtime 放量证据”阶段。

2026-08-29 线上快照：

| 检查 | 状态 |
| --- | --- |
| deployed commit | `a2ef40c1306c78724ee02b68fb16083c8cde5f21` |
| environment | `production` |
| Runtime config | `v1.41-history-control` |
| PostgreSQL / Alembic | `011` / ready |
| deployment provenance | PASS |
| production RAG shallow health | PASS，`history` 2850 documents |
| rollout observation writes | PASS，近 15 分钟 0 failure |
| Runtime enabled | false |
| rollout evidence | disabled / missing |
| strict Runtime readiness | FAIL，唯一 blocking check 为 `rollout_evidence` |

这一状态不表示应用部署失败：`/api/health` 和默认 shallow `/api/ready` 仍是应用可用性信号。它表示 Runtime v2 还不具备进入 Shadow 后的放量证据。

v1.42 不继续横向增加 Agent、动态规划或第二套执行引擎。本轮把现有的底层门禁组装成运营者可理解、可预检、可复盘的灰度操作面，并安全完成 `history_character` 的 control 到 shadow 晋级闭环。

## 1. 问题定义

### 1.1 底层指标已有，但无法直接回答“下一步做什么”

现有系统已能计算：

- control observation 延迟与样本数；
- Runtime terminal runs、event coverage 和 terminal consistency；
- Run commit/environment provenance coverage；
- duplicate side effect、invalid transition 和 high-risk violation；
- control baseline 与 shadow p95 regression；
- offline、real LLM 和 production RAG evidence profile；
- per-agent rollout gate。

但这些信号分布在 `/api/ready`、`rollout-readiness`、AgentOps summary、数据表和 GitHub Actions 中。运营者仍需要人工推断：

- 当前是 `collecting_control` 还是 `collecting_shadow`；
- control 还差多少样本；
- baseline 是否已可封印；
- 当前阻塞是配置、样本、安全、延迟还是证据 profile；
- 下一步应继续收集、切换 Shadow、运行 evidence 还是紧急停止。

### 1.2 Shadow 配置是多变量合取，缺少统一预检

`history_character` Shadow 至少同时受以下变量影响：

- Runtime enabled / kill switch；
- global BPS 与 per-agent BPS；
- shadow mode；
- event persistence 与 artifact persistence；
- config version；
- target/baseline commit 与 environment；
- 其他 Agent 的 BPS。

当前只有局部 fail-closed；不合法组合可能造成“Runtime 开启但没有样本”、“非目标 Agent 被意外放量”或“误进入 active”。

### 1.3 AgentOps 尚未显性化 rollout 闭环

`agent_ops.py` 已返回 `rollout_gates`、`rollout_observations`、`release_evidence_count` 和 Runtime 安全计数，但 Eval/AgentOps 页面仍主要展示通用 readiness、trace、LLM、RAG 和学习助手指标。运营者无法从 UI 一眼看出 Runtime rollout 阶段与阻塞项。

### 1.4 最终 evidence 工作流已有，但缺少前置阶段检查

`Runtime Rollout Evidence` 工作流适合在 control 和 target 样本都充足后生成最终证据。它不应被迫同时承担“样本是否充足”、“现在能否切 Shadow”这类日常诊断。

## 2. 目标与非目标

### 2.1 目标

1. 为 `history_character` 提供单一、可审计的 rollout status 合同。
2. 在修改生产环境变量前证明配置组合安全。
3. 让 AgentOps 显示 control/shadow 样本、evidence、gate 和 next action。
4. 增加只读 rollout preflight，不赋予 CI 直接修改 Render 的权限。
5. 只对 `history_character` 启用 observable Shadow，其他 Agent 保持 0 BPS。
6. 完成 control >=100、shadow >=100、evidence PASS 和 48 小时观察的运营闭环。

### 2.2 非目标

本轮不实现：

- Runtime active canary；
- 学习助手、AutoTutor、作文批改或辩论 Agent 放量；
- 动态 re-plan、read fan-out 或 Agent 委派；
- 为了收集样本重复执行第二次 LLM/RAG；
- 第二套 LangGraph 或 Runtime 图调度器；
- 用 eval、demo seed、数据库直写或伪造请求补齐生产样本；
- 教师盲审、初中生可理解性或 24h retention 评估；
- 在页面上提供绕过审批的“一键放量”按钮。

## 3. 总体流程

```text
production health/schema/provenance PASS
  -> collect real control observations
  -> control samples >= 100
  -> rollout config preflight PASS
  -> deploy history_character shadow config
  -> collect real shadow terminal runs >= 100
  -> run offline + real LLM + production RAG profiles
  -> build and persist hash-bound evidence
  -> per-agent rollout gate PASS
  -> strict Runtime readiness PASS
  -> observe 48 hours without P0/P1
```

Runtime v2 在 Shadow 阶段仍是治理与观测层：

- 历史人物仍只调用一次已有 compiled LangGraph；
- stream 和 non-stream 仍消费同一 `stream_character_graph_events()` 执行源；
- Shadow 记录 Run/Event/Artifact 和 completion，不生成第二份学生回答；
- Runtime 失败不得导致重复业务执行或重复写操作。

## 4. P0：Rollout Status 合同

### 4.1 API

新增：

```http
GET /api/admin/agent-runtime/rollout-status?agent_type=history_character
```

可选查询参数：

| 参数 | 默认 | 限制 |
| --- | --- | --- |
| `agent_type` | required | 1-80 chars，v1.42 仅允许 `history_character` |
| `window_hours` | 168 | 1-744 |
| `minimum_samples` | 100 | 100-100000，production 不得低于 100 |

权限：

- `EDU_AGENT_AUTH_REQUIRED=true` 时仅 admin 可访问；
- 未鉴权生产请求返回 401/403；
- 返回体不含 actor/student/session ID、学生正文、prompt、Artifact 内容或确认令牌。

### 4.2 返回合同

```json
{
  "schema_version": 1,
  "phase": "collecting_control",
  "status": "blocked",
  "agent_type": "history_character",
  "deployment": {
    "commit": "a2ef40c...",
    "environment": "production",
    "config_version": "v1.41-history-control",
    "runtime_enabled": false,
    "runtime_mode": "shadow",
    "kill_switch": false
  },
  "control": {
    "commit": "a2ef40c...",
    "config_version": "v1.41-history-control",
    "terminal_samples": 42,
    "minimum_samples": 100,
    "sample_sufficient": false,
    "p50_ms": 4200,
    "p95_ms": 9800,
    "baseline_ready": false
  },
  "shadow": {
    "terminal_runs": 0,
    "minimum_terminal_runs": 100,
    "run_provenance_coverage": null,
    "event_coverage": null,
    "terminal_consistency": null,
    "p95_regression": null
  },
  "safety": {
    "duplicate_side_effects": 0,
    "invalid_transitions": 0,
    "high_risk_without_confirmation": 0,
    "observation_write_failures": 0
  },
  "evidence": {
    "present": false,
    "fresh": false,
    "profiles": {
      "offline": "unknown",
      "real_llm": "unknown",
      "production_rag": "unknown"
    }
  },
  "gate": {
    "status": "unknown",
    "reasons": ["control_samples_insufficient"]
  },
  "blockers": ["control_samples_insufficient"],
  "next_action": "continue_collecting_control"
}
```

### 4.3 Phase 状态机

`phase` 只允许：

| Phase | 判定 |
| --- | --- |
| `deployment_blocked` | schema、deployment provenance、Runtime config 或 observation health 存在 blocking error |
| `collecting_control` | control 样本不足 100 |
| `control_ready` | control 样本充足且 baseline 可构建，但尚未部署 Shadow |
| `collecting_shadow` | 已启用 Shadow，terminal runs 不足 100 |
| `evidence_pending` | Shadow 样本充足，但 evidence 缺失、过期或 profile 未通过 |
| `shadow_observing` | gate PASS/WARN，但 48h 稳定观察未完成 |
| `shadow_complete` | gate PASS 且完成 48h 无 P0/P1 观察 |
| `stopped` | kill switch 或人工停止标记生效 |

`status` 使用 `pass | warn | blocked | unknown`，与 `phase` 分离：阶段是进度，状态是健康度。

### 4.4 Next action

`next_action` 只允许：

- `fix_deployment_contract`
- `continue_collecting_control`
- `run_shadow_preflight`
- `deploy_shadow_config`
- `continue_collecting_shadow`
- `run_rollout_evidence`
- `investigate_gate_failure`
- `continue_48h_observation`
- `stop_rollout`
- `shadow_operational_complete`

API 不返回自由文本操作指令，前端负责把稳定 code 转换为文案。

## 5. P0：灰度配置预检

### 5.1 命令

新增：

```bash
PYTHONPATH=backend python3 scripts/validate_runtime_rollout_config.py \
  --phase shadow \
  --agent-type history_character \
  --json
```

命令只读取环境变量与可选 readiness URL，不修改 Render、GitHub secrets 或数据库。

### 5.2 Shadow 必需配置

```text
EDU_AGENT_RUNTIME_V2_ENABLED=true
EDU_AGENT_RUNTIME_V2_SHADOW_MODE=true
EDU_AGENT_RUNTIME_V2_PERCENT_BPS=10000
EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS=10000
EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS=0
EDU_AGENT_RUNTIME_V2_AUTOTUTOR_BPS=0
EDU_AGENT_RUNTIME_V2_ESSAY_GRADER_BPS=0
EDU_AGENT_RUNTIME_V2_DEBATE_BPS=0
EDU_AGENT_RUNTIME_V2_PERSIST_EVENTS=true
EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED=true
EDU_AGENT_RUNTIME_V2_KILL_SWITCH=false
EDU_AGENT_RUNTIME_V2_CONFIG_VERSION=v1.42-history-shadow
EDU_AGENT_RUNTIME_ROLLOUT_AGENT_TYPE=history_character
EDU_AGENT_RUNTIME_ROLLOUT_BASELINE_CONFIG_VERSION=v1.41-history-control
EDU_AGENT_RUNTIME_ROLLOUT_BASELINE_COMMIT=<full-control-commit>
EDU_AGENT_RUNTIME_ROLLOUT_MIN_TERMINAL_RUNS=100
```

继续禁用：

```text
EDU_AGENT_RUNTIME_V2_CHECKPOINT_ENABLED=false
EDU_AGENT_RUNTIME_V2_RESUMABLE_ENABLED=false
EDU_AGENT_RUNTIME_V2_DYNAMIC_REPLAN_ENABLED=false
EDU_AGENT_RUNTIME_V2_READ_FANOUT_ENABLED=false
```

### 5.3 Fail-closed 规则

以下任一条使 preflight 失败：

1. Shadow phase 下 Runtime disabled、shadow mode false 或 kill switch true；
2. global BPS 或 `history_character` BPS 不是 10000；
3. 任一非目标 Agent BPS > 0；
4. persist events 或 artifact 关闭；
5. config version 为空、旧默认值或不含 `shadow`；
6. baseline config/commit 缺失，baseline commit 不是 40 位 SHA；
7. environment 不是 `production`；
8. dynamic re-plan、read fan-out 或 resumable 被开启；
9. 线上 deployed commit 与当前预检 commit 不一致；
10. control baseline 样本少于 100；
11. schema/provenance/observation health 不可用。

### 5.4 Active 保护

v1.42 不允许 active。新增显式保护位：

```text
EDU_AGENT_RUNTIME_V2_ACTIVE_ENABLED=false
```

当 `SHADOW_MODE=false` 且 `ACTIVE_ENABLED` 不是 true 时：

- `RuntimeV2Settings.rollout_decision()` 必须返回 inactive；
- deployment/runtime readiness 返回 `runtime_active_not_approved`；
- preflight 失败；
- 不创建 active Runtime Run。

active 的 evidence hash 绑定与审批合同留到 v1.43。

## 6. P0：AgentOps Rollout 面板

### 6.1 位置

在 `/eval` 的 `AgentOpsPanel` 中增加独立的 **Runtime Rollout** 区域，不与学习助手语义路由指标混在一起。

### 6.2 必须展示

- phase / health status；
- deployed commit 短 SHA、environment、config version；
- control samples / minimum samples；
- shadow terminal runs / minimum runs；
- provenance coverage；
- event coverage；
- terminal consistency；
- unexpected failure rate；
- p50/p95 和 p95 regression；
- duplicate executed / prevented；
- invalid transitions；
- high-risk violations；
- observation write failures；
- offline / real LLM / production RAG profile status；
- evidence freshness 与 gate status；
- blocker codes；
- next action 文案。

### 6.3 显示规则

- `unknown` 不得用绿色；
- 样本不足显示进度，不显示为故障；
- hard safety blocker 使用红色；
- warn threshold 使用黄色；
- 不展示 student/session ID 或单条 trace 内容；
- 不提供直接修改生产环境变量的按钮。

## 7. P0：Rollout Preflight 工作流

### 7.1 形态

新增 `.github/workflows/runtime-rollout-preflight.yml`，仅允许 `workflow_dispatch`，使用受保护 `production` environment。

输入：

- deployed commit；
- agent type；
- target phase；
- target config version；
- baseline config version；
- baseline commit；
- ready URL；
- minimum samples，production 最小 100。

### 7.2 步骤

1. checkout 指定 clean commit；
2. 校验 commit SHA 与 production environment；
3. 查询线上 deployed commit；
4. 查询 rollout status；
5. 运行 rollout config validator；
6. 确认 control samples >=100；
7. 确认 observation health 无写入失败；
8. 生成脱敏 `rollout-preflight.json` 和 `.md`；
9. 上传 14 天 artifact；
10. 输出建议的环境变量 diff，但不自动修改 Render。

### 7.3 安全边界

Artifact 中只允许：

- commit/config/environment；
- 聚合样本数与百分比；
- gate/blocker/next-action code；
- 脱敏的配置键名和非密密值。

Artifact 中禁止：

- API token、DATABASE_URL、DIRECT_URL、JWT_SECRET；
- actor/student/session ID；
- prompt、response、source excerpt 或 Artifact 正文；
- GitHub/Render secret value。

## 8. 指标与 Gate

### 8.1 样本边界

| 样本 | 来源 | 最小数量 | 排除 |
| --- | --- | --- | --- |
| control baseline | `agent_rollout_observations` / mode `control` | 100 | `eval`、`demo`、commit/config/environment 不匹配 |
| shadow target | `agent_runs` + terminal events / mode `shadow` | 100 | 缺失 provenance、不匹配 commit/config/environment/scope |

不得通过降低 production minimum 或修改 data scope 宣称达标。真实流量不足时状态保持 `collecting_* / unknown`。

### 8.2 Hard fail

任一条触发 gate FAIL 与停止放量：

- `duplicate_side_effect_executed > 0`；
- `invalid_transition > 0`；
- `high_risk_without_confirmation > 0`；
- terminal consistency <100%；
- unexpected failure rate >2%；
- event coverage <80%；
- p95 相对 control 回归 >10%；
- provenance coverage 非 100%；
- observation write health 不可用或有失败；
- evidence hash/profile/commit/config/environment 不匹配；
- schema/readiness 不可用。

### 8.3 Warn

- event coverage >=80% 但 <95%；
- p95 regression >5% 但 <=10%。

WARN 可继续 Shadow 观察，不得进入 active。

## 9. 文件级改造

| 文件 | 改造 |
| --- | --- |
| `backend/agent_runtime/rollout_status.py` | 新增 phase/status/blocker/next-action 聚合器 |
| `backend/agent_runtime/rollout_observations.py` | 增加按 commit/config/environment/scope 的 control progress 安全查询 |
| `backend/agent_runtime/rollout_gate.py` | 复用统一 gate 结果，不在 status 层复制阈值 |
| `backend/agent_runtime/context.py` | 增加 active 显式保护，Shadow 决策仍只对目标 Agent 生效 |
| `backend/deployment.py` | 扩展 Runtime config 组合错误代码 |
| `backend/api/routers/agent_runtime.py` | 新增 admin rollout-status API |
| `backend/agent_ops.py` | 稳定输出 rollout status 摘要 |
| `frontend/app/eval/page.tsx` | 增加 Runtime Rollout 面板、进度、blocker 和 next action |
| `scripts/validate_runtime_rollout_config.py` | 新增本地/CI 共用预检 |
| `.github/workflows/runtime-rollout-preflight.yml` | 新增只读 production preflight |
| `render.yaml` | Development Complete 后经 preflight 评审才从 control 切换为 shadow 配置 |
| `eval/agent_runtime_rollout_status_smoke.py` | phase、样本隔离、权限与脱敏合同 |
| `eval/runtime_rollout_config_smoke.py` | 安全/不安全配置矩阵 |
| `eval/runtime_evidence_workflow_smoke.py` | 增加 preflight workflow 权限、输入与 artifact 合同 |
| `frontend/e2e/*` | admin rollout 面板核心状态 E2E |

若 status 聚合不需要新 schema，本轮不新增 Alembic revision。观察开始时间优先从已封印 evidence 的 `generated_at` 和工作流 artifact 计算，不为 UI 状态重复建表。

## 10. 测试矩阵

### 10.1 确定性后端测试

1. Runtime disabled 时历史人物仍记录 control observation，不创建 Runtime Run。
2. control 99/100 返回 `collecting_control`。
3. control 100/100 且 baseline 合法返回 `control_ready`。
4. eval/demo/commit mismatch 数据不计入 control。
5. Shadow 99/100 返回 `collecting_shadow`。
6. Shadow 100/100 但 evidence 缺失返回 `evidence_pending`。
7. gate PASS 返回 `shadow_observing`。
8. hard safety signal 返回 blocked 和 `stop_rollout`。
9. 非 admin 访问 status API 返回 403。
10. status 返回体不含学生内容或 ID。

### 10.2 配置矩阵

至少覆盖：

- 合法 control；
- 合法 history-only Shadow；
- Runtime disabled + Shadow target；
- global BPS 0；
- target BPS 0；
- 非目标 Agent BPS >0；
- artifact/persist events 关闭；
- config/baseline commit 缺失；
- kill switch；
- dynamic re-plan/read fan-out/resumable 误开；
- active 未显式批准；
- deployed commit mismatch；
- control samples insufficient。

### 10.3 Parity 测试

对同一历史人物请求验证：

- control 和 shadow 的业务回答、sources、verification/fact card 合同一致；
- stream/non-stream 都只调用一次 graph；
- Shadow 只增加 Runtime Run/Event/Artifact；
- Runtime 记录失败不得重复调用 LLM/RAG；
- final output artifact 的权限和敏感度保持现有策略。

### 10.4 CI

PR CI 必须包含：

- Python compile；
- rollout status/config/workflow smoke；
- Runtime v2 安全、并发、幂等、stream parity smoke；
- frontend lint/unit/build；
- admin rollout 面板 E2E；
- Docker build；
- PostgreSQL migration/schema 专项 job。

PostgreSQL 专项 suite 不得重新混入无 PostgreSQL service 的通用 smoke。

## 11. 发布计划

### Phase 0：Control collection

保持当前：

```text
config=v1.41-history-control
runtime enabled=false
history_character BPS=0
```

持续收集真实 runtime-scope control observations。

进入下一阶段前：

- control terminal observations >=100；
- observation write failures =0；
- deployment/schema/RAG 健康；
- baseline commit/config/environment 已固定。

### Phase 1：Shadow preflight

- 运行 production preflight；
- 审查 control baseline 和环境变量 diff；
- 确认其他 Agent BPS=0；
- 确认 active guard 关闭；
- 人工审批后才修改 Render/Blueprint 配置。

### Phase 2：History-only Shadow

配置 `v1.42-history-shadow`，100% 覆盖 `history_character` 的 observable wrapper，但不改变业务回答源。

停止条件：

- duplicate executed；
- invalid transition；
- high-risk violation；
- terminal inconsistency；
- provenance 不完整；
- 异常失败率/p95/event coverage 越线；
- observation 写入失败；
- 业务回答 parity 回归。

### Phase 3：Evidence

Shadow terminal runs >=100 后：

1. 运行 complete offline profile；
2. 运行 real LLM profile；
3. 运行 production RAG profile；
4. 从生产 control observations 构建 baseline；
5. 构建并持久化 hash-bound evidence；
6. strict Runtime readiness 必须 PASS；
7. per-agent rollout gate 必须 PASS。

### Phase 4：48h observation

- 保持 Shadow；
- 不进入 active；
- 持续检查 hard blockers、p95、failure rate 和 evidence freshness；
- 输出 v1.42 production shadow report。

## 12. 完成定义

### 12.1 Development Complete

必须同时满足：

1. rollout status API、phase machine 与 next-action 合同完成；
2. 统计按 agent/commit/config/environment/mode/scope 严格隔离；
3. Shadow 配置预检与 active 保护 fail-closed；
4. AgentOps rollout 面板完成；
5. production preflight workflow 完成，无生产写权限；
6. API/UI/workflow/config/parity smoke 全部通过；
7. full release gate、frontend build/E2E、Docker build 和 PostgreSQL 专项 CI 通过；
8. 文档不把 deterministic PASS 描述为生产 rollout PASS。

### 12.2 Operational Complete

必须同时满足：

1. production control observations >=100；
2. production shadow terminal runs >=100；
3. provenance coverage =100%；
4. terminal consistency =100%；
5. duplicate side effects executed =0；
6. invalid transitions =0；
7. high-risk violations =0；
8. observation write failures =0；
9. unexpected failure rate <=2%；
10. event coverage >=95%；
11. p95 regression <=5%；
12. offline/real LLM/production RAG profiles 全部 PASS；
13. rollout gate 和 strict Runtime readiness PASS；
14. 证据绑定正确的 production commit/config/environment；
15. 48 小时无 P0/P1 安全、一致性或用户可见回归。

样本不足时 Operational 状态保持 `NOT_RUN/unknown`，不得改小阈值或用非 production scope 数据替代。

## 13. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 真实流量不足 | 保持 collecting/unknown，不伪造样本；继续运营而不扩大技术范围 |
| Render 配置漂移 | preflight 校验线上 commit/config/environment，配置 diff 经人工审批 |
| Shadow 误触发其他 Agent | per-agent BPS 矩阵 + 非目标 BPS=0 强校验 |
| 误进 active | `ACTIVE_ENABLED=false` 与 Runtime 决策层 fail-closed |
| UI 误导 | phase/status 分离，unknown 不显示为绿色，样本不足显示进度 |
| 敏感数据进入证据 | API/artifact 只输出聚合指标和 code，加入负向脱敏测试 |
| 双执行导致成本/延迟翻倍 | 继续使用单一 graph 执行源，Shadow 只包装观测合同 |
| 阈值在多处漂移 | status/UI/workflow 复用 rollout gate 结果，不复制指标公式 |

## 14. 后续迭代

v1.42 Operational Complete 后再开始：

1. **v1.43 `history_character` active canary**：allowlist -> 1% -> 10%，每阶段独立 evidence 和审批；
2. **v1.44 真实教学效果证据**：教师盲审、初中生可理解性、24h retention；
3. 只根据真实 production failure/latency/safety 数据决定是否将 Runtime 扩展到 AutoTutor。

## 15. 实施记录（2026-08-30）

代码实现已完成：

- 新增聚合 rollout status phase machine、control progress 与管理员只读 API；
- AgentOps summary 与 Eval 页面接入 rollout 阶段、进度、阻塞项和 next action；
- 新增 control/shadow 配置预检，非目标 Agent、持久化、baseline、active guard 均 fail-closed；
- 新增只读 **Runtime Rollout Preflight** 工作流及脱敏 promotion-plan artifact；
- Render 默认仍保持 Runtime disabled/control，未由代码变更越权切换生产 Shadow；
- 新增 API、权限、scope 隔离、状态机、配置矩阵和 workflow contract smoke。

本地验证结果：

- 项目虚拟环境 full release gate：`92/93` suites、`405/406` cases 通过；唯一 skipped 为需要外部条件的既有 `history_character_smoke`；
- Frontend lint、Vitest（22 tests）、production build 通过；
- Playwright Eval rollout 面板目标流程通过；
- workflow YAML 解析与 runtime rollout 专项 smoke 通过。

Docker build 与一次性 PostgreSQL 演练依赖 CI/专用数据库环境，仍由现有发布流水线执行。因此这里记录的是实现与本地门禁结果，不把它表述为生产 rollout PASS。production control/shadow 样本、三类真实 evidence、strict gate 与 48 小时观察均尚未运行，Operational 状态保持 `NOT_RUN/unknown`。
