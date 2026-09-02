# EduAgent AutoTutor Canary Deployment Verification v1.49.4 Spec

**状态：** Proposed
**日期：** 2026-09-02
**优先级：** P0 Scoped Production Preflight、Exact Snapshot 与 Rollback Verification；P1 Manual Evidence Workflow
**前置版本：** v1.49.3 AutoTutor Production Canary Admission & Evidence Closure
**后续候选：** v1.50 AutoTutor Single Executor Consolidation（仍需本 Spec Production Verified 后才能创建）

---

## 0. 决策摘要

v1.49.3 已完成 AutoTutor Graph Canary 的开发级安全闭环，并已进入远端默认分支与生产部署：

- `main`、`origin/main` 与 Render deployed commit 均为 `1e34b71bc8465354b1608291faaf0ec3efbd8eac`；
- GitHub Actions `EduAgent CI` 对该 commit 执行成功；
- 生产数据库为 PostgreSQL，Alembic revision 已到 `016`；
- `runtime_schema_readiness` 为 ready，缺失表和列均为空；
- 最近 15 分钟 observation writer health 为 `ok`，failure count 为 0；
- 生产浅层 readiness 通过，认证、数据库和 LLM 配置均可用；
- AutoTutor Active BPS 的代码默认仍为 0，Graph 未被设为默认 executor；
- 本地 fast release gate 为 73/73 suites、657/657 cases；
- AutoTutor full outcome parity 为 108/108，fault injection 为 8/8；
- 前端 lint、30/30 unit tests 和 production build 通过。

但当前仍只有 **Deployment Baseline Ready**，不是 **Production Verified**：

1. `render.yaml` 尚未显式声明 AutoTutor executor mode、BPS、config version、bucket salt、kill switch、comparator 和 fallback；
2. 生产安全目前部分依赖代码默认值，而不是可评审的声明式部署合同；
3. 现有 `/api/ready?require_runtime=true` 是通用 Runtime gate，会被 History Character 的 LLM capability manifest 和 rollout evidence 阻断，不能精确回答 AutoTutor BPS 0/1% 是否安全；
4. GitHub workflow 只有通用 release gate 与 production RAG evidence，没有 AutoTutor 专用远程 preflight；
5. `scripts/build_autotutor_canary_evidence.py` 默认直接访问数据库，不具备通过管理员 API 获取不可变生产窗口快照的路径；
6. rollout status 使用滚动时间窗口，不能直接作为评审后不变的 evidence input；
7. 没有统一脚本验证 deployed commit、schema 016、AutoTutor config、trusted cohort、BPS、admission、writer health 和 exact aggregate；
8. 没有 GitHub Environment 审批后的手工 workflow 来封存 preflight、control、canary、rollback 四阶段证据；
9. restart、writer failure、kill switch 的测试存在，但真实部署 rehearsal 尚未绑定 commit/config/window；
10. Render free service 存在冷启动：一次 `/api/ready` 45 秒无响应，实例唤醒后 `/api/health` 与 `/api/ready` 可恢复；现有生产检查缺少有界重试和冷启动分类；
11. production verified cohort、control transition 和 committed Graph transition 的真实数量尚未形成可审计快照；
12. 当前没有证据证明 production Active 从未超过 1%。

因此 v1.49.4 的决定是：

> 不修改教学算法，不删除 Legacy，不扩大流量，不进入 Single Executor Consolidation；先把部署配置、AutoTutor scoped readiness、远程 exact snapshot、手工审批 workflow、rehearsal 和 rollback verification 做成一条可重复、可审计、默认只读的生产验证链。

版本主题：**生产验证必须针对正在发布的 Agent、commit、config 和窗口，而不是依赖一个跨 Agent 的通用绿色或红色状态。**

---

## 1. 项目实际基线

### 1.1 已成立且必须保留的边界

- `autotutor_sessions` 继续是唯一业务状态真相；
- start idempotency 与 answer claim 必须先于 Admission 和 Provider；
- Admission 必须先于 Provider；
- stale、busy、replay、conflict 不执行 Admission/Provider/Graph；
- Graph 与 Legacy 只能计算 outcome，不能直接提交业务副作用；
- selected 与 comparator 共用同一个 immutable observation bundle；
- Graph failure 与 Comparator mismatch 只能在 commit 前 fallback；
- start/answer 业务效果仍由现有事务单次提交；
- existing Graph session admission revoked 后永久降级；
- kill switch 必须绕过 Admission cache；
- migration 016 的 telemetry 字段保持 nullable；
- production Active BPS 默认 0，v1.49.x 硬上限为 100 BPS；
- demo、eval、anonymous、operator、unverified 流量不得进入 production GO 分母；
- 不引入 PostgreSQL LangGraph checkpointer 或 `interrupt`；
- CI、preflight、snapshot 和 evidence 不得输出学生或会话内容。

### 1.2 2026-09-02 生产只读核验

| 检查项 | 实际结果 | 结论 |
|---|---|---|
| GitHub default branch | `1e34b71` | 已同步 |
| GitHub CI | success | Development gate 已进入远端 |
| Render deployed commit | 完整 SHA，等于 `1e34b71...` | commit provenance ready |
| Environment | production | ready |
| Database | PostgreSQL | ready |
| Alembic | `016` | AutoTutor telemetry schema ready |
| Observation health | ok / 0 failures | 当前 writer ready |
| Shallow readiness | pass | 服务基础依赖 ready |
| Strict generic Runtime readiness | fail | LLM capability manifest、History rollout evidence 缺失 |
| AutoTutor scoped readiness | 无独立合同 | NOT READY |
| AutoTutor Render config | Blueprint 未声明 | NOT READY |
| Exact production snapshot | 未封存 | NOT READY |
| Verified control/Graph samples | 未形成 evidence | NOT READY |
| Rehearsal evidence | 未绑定部署 | NOT READY |

### 1.3 为什么不能复用通用 Runtime strict readiness

当前 strict Runtime readiness 同时要求：

- Runtime deployment provenance；
- Runtime schema；
- LLM capability manifest；
- 通用 rollout evidence；
- observation writer health。

这些检查适合 History Character Runtime v2 rollout，但 AutoTutor Graph executor 有不同治理平面：

- AutoTutor 使用 `EDU_AGENT_AUTOTUTOR_*` 配置；
- AutoTutor 在 BPS 0 时仍应允许部署、收集 Legacy control；
- AutoTutor 的 comparator、fallback、Admission 和 transition aggregate 有独立合同；
- AutoTutor evidence schema 为 schema v3 / `active_canary`；
- 通用 History evidence 缺失不应误报为 AutoTutor schema 或 Admission 故障；
- AutoTutor 的 GO 也不能因为通用 shallow readiness 绿色而被推断成立。

结论：保留通用 readiness，不改变其既有语义；新增 AutoTutor scoped preflight，不通过放宽通用 gate 获得绿色。

---

## 2. 目标与非目标

### 2.1 P0：声明式 BPS 0 部署合同

- 在 `render.yaml` 显式声明 AutoTutor executor 的全部安全默认值；
- mode 默认 `legacy`；
- Active BPS 默认 `0`；
- config version 固定为 `v1.49.4-production-verification`；
- bucket salt 必须显式配置，版本内不可漂移；
- kill switch 默认 `false`，但必须可由 Render Dashboard 立即设为 `true`；
- comparator 与 fallback 默认开启；
- Blueprint 变更不得自动开启 Active；
- 启动日志和 readiness 只输出非敏感配置摘要，不输出 salt 原文。

### 2.2 P0：AutoTutor Scoped Production Preflight

建立唯一 AutoTutor 部署状态合同，回答：

- 当前服务是否为预期 commit；
- schema 是否至少为 016；
- executor mode、BPS、config 是否符合当前阶段；
- production BPS 是否在 0..100；
- comparator、fallback、kill switch 是否安全；
- observation writer 是否健康；
- verified cohort 是否存在；
- exact control/Graph 样本进度是多少；
- 当前 phase、blockers、next action 是什么；
- 是否允许进入 1% 收集窗口；
- 是否必须回滚到 BPS 0/Legacy。

### 2.3 P0：不可变 Production Snapshot

- 提供管理员只读 exact snapshot API；
- 请求显式携带 window start/end、commit、config、environment；
- 服务端从生产数据库计算 aggregate，不接受客户端自报指标；
- 返回 schema/admission/config/cohort/aggregate 摘要；
- snapshot 生成 hash，并能作为 evidence builder 的唯一聚合输入；
- 同一请求参数和同一数据集得到稳定 payload hash；
- snapshot 不返回 observation row、trace ID、effect key、actor ID 或 session ID；
- query/schema/provenance 异常返回 `UNKNOWN` 和 `decision=NO_GO`。

### 2.4 P1：手工审批 Production Verification Workflow

- 新增 `workflow_dispatch`，不由普通 push 自动开启 Canary；
- 使用 GitHub Environment approval 保护 production verification；
- workflow 默认只读，不调用 Render 配置写 API；
- 支持 `preflight`、`control_snapshot`、`canary_snapshot`、`rollback_verify` 四种动作；
- expected commit 必须等于 workflow checkout SHA 和 deployed commit；
- 管理员 token 只通过 GitHub secret 注入，不写 artifact/log；
- artifact 只包含 PII-free status、snapshot、evidence 和 Markdown summary；
- workflow 失败时保留诊断 artifact，但不得把失败伪装为 NOT_RUN；
- evidence GO 仅在 production exact snapshot 和全部 rehearsal 都通过时生成。

### 2.5 P1：有界冷启动与网络错误语义

- `/api/health` 用于唤醒，不作为 rollout GO；
- 远程检查允许 2–3 次有界重试，总预算不超过 120 秒；
- 区分 `cold_start_timeout`、`network_unavailable`、`http_error`、`invalid_payload` 和 `provenance_mismatch`；
- 第一次超时、后续成功应记录 warning，不自动判 NO_GO；
- 所有重试仍失败返回 `UNKNOWN/NO_GO`；
- 不使用无限循环，不让 workflow 永久占用 runner。

### 2.6 非目标

- 不把 Graph 设为默认 executor；
- 不在代码、CI 或 workflow 中自动把 BPS 从 0 改为 100；
- 不集成 Render 写权限或自动修改生产环境变量；
- 不允许超过 1%；
- 不删除 Legacy、Comparator 或 fallback；
- 不降低 Admission 条件；
- 不修改教学内容、题目、mastery 或复习算法；
- 不新增学生数据到 telemetry/evidence；
- 不让 public readiness 暴露管理员聚合细节；
- 不把 demo 账号改成 verified；
- 不把 operator actor 计入真实学生 Canary；
- 不以本地/CI synthetic rows 作为 production sample；
- 不在本迭代执行 v1.50 consolidation。

---

## 3. 阶段模型

### 3.1 唯一允许的生产阶段

```text
deployed_bps_zero
        │
        ▼
control_collecting
        │ control >= 100
        ▼
ready_for_manual_one_percent
        │ 人工审批 + Render 手工 BPS=100
        ▼
canary_collecting
        │ committed Graph >= 100
        ▼
canary_ready_for_snapshot
        │ exact snapshot + rehearsals
        ▼
production_verified
        │ 评审后恢复 BPS=0，或单独授权保持 1%
        ▼
rollback_verified / review_complete
```

任一阶段均可进入：

```text
deployment_blocked
canary_blocked
rollback_required
verification_unknown
```

### 3.2 next action 枚举

只允许以下机器可读值：

```text
fix_deployment_contract
wait_for_deployment
collect_control
approve_verified_cohort
review_one_percent_enablement
collect_canary
stop_canary
build_exact_snapshot
complete_rehearsals
persist_evidence
restore_bps_zero
verify_rollback
review_v150_entry
```

前端和 workflow 不自行推导 next action。

### 3.3 status 与 decision

```text
status   = READY | NOT_READY | BLOCKED | UNKNOWN | VERIFIED
decision = GO | NO_GO
```

- `READY`：只表示可以请求下一人工步骤，不表示已自动执行；
- `NOT_READY`：样本不足或尚未执行必需步骤；
- `BLOCKED`：指标或安全条件失败；
- `UNKNOWN`：远程、schema、query 或 provenance 无法确认；
- `VERIFIED`：exact production evidence 已持久化且 rollback policy 已满足；
- 除 `READY` 和 `VERIFIED` 外，decision 必须为 `NO_GO`；
- `READY/GO` 也只授权人工评审，不授权 workflow 修改 BPS。

---

## 4. 声明式 AutoTutor 部署配置

### 4.1 `render.yaml` 必须新增

```yaml
EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE: legacy
EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS: "0"
EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION: v1.49.4-production-verification
EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT: <sync:false or reviewed immutable value>
EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH: "false"
EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED: "true"
EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED: "true"
```

约束：

- salt 不得在 API、日志和 artifact 输出原文；
- config version 必须输出；
- BPS、mode、kill switch、comparator、fallback 必须输出；
- production `active_canary` + BPS 0 为配置错误；
- production `legacy` + BPS 0 为部署基线；
- production `active_canary` + BPS 1..100 才是候选 Canary；
- production BPS >100 必须启动后 fail-closed 到 Legacy；
- Blueprint 合并本身不能改变 Dashboard 中的人工 Canary 审批状态而产生意外开流量。

### 4.2 配置指纹

新增 PII-free 配置指纹：

```text
sha256(mode + bps + config_version + salt + comparator + fallback)
```

只输出 hash，不输出 salt。用途：

- Admission snapshot cache key；
- exact deployment snapshot；
- evidence；
- restart 前后配置一致性检查；
- 防止同 config version 下 salt 静默变化。

kill switch 不进入稳定指纹，单独记录当前值和检查时间，保证其可立即切换。

---

## 5. AutoTutor Scoped Preflight 合同

### 5.1 服务层

建议新增：

```text
backend/agent_runtime/autotutor_canary_verification.py
```

统一函数：

```python
build_autotutor_canary_verification(
    *,
    expected_commit: str | None,
    expected_config_version: str | None,
    window_start: str | None,
    window_end: str | None,
    minimum_control: int = 100,
    minimum_graph: int = 100,
) -> dict
```

不得在 router、CLI、workflow 和 UI 中复制 phase/blocker 公式。

### 5.2 返回合同

```json
{
  "schema_version": 1,
  "agent_type": "auto_tutor",
  "generated_at": "UTC ISO-8601",
  "phase": "control_collecting",
  "status": "NOT_READY",
  "decision": "NO_GO",
  "next_action": "collect_control",
  "blockers": ["control_samples_insufficient"],
  "deployment": {
    "expected_commit": "40-char sha",
    "deployed_commit": "40-char sha",
    "environment": "production",
    "schema_revision": "016"
  },
  "configuration": {
    "mode": "legacy",
    "active_bps": 0,
    "config_version": "v1.49.4-production-verification",
    "config_fingerprint": "sha256:...",
    "kill_switch": false,
    "comparator_enabled": true,
    "fallback_enabled": true
  },
  "admission": {},
  "trusted_cohort": {
    "ready": false,
    "verified_actor_count": 0
  },
  "observation_health": {},
  "progress": {
    "control_transition_count": 0,
    "committed_graph_transition_count": 0,
    "minimum_control": 100,
    "minimum_graph": 100
  },
  "snapshot": null,
  "evidence": {
    "present": false,
    "decision": null,
    "sha256": null
  }
}
```

### 5.3 blocker 优先级

从高到低：

1. deployed commit mismatch；
2. non-production environment；
3. schema <016 / missing columns；
4. invalid mode/BPS/config；
5. comparator/fallback disabled；
6. writer degraded/unavailable；
7. unauthorized Graph；
8. duplicate committed effect；
9. comparator mismatch/unknown；
10. fallback rate ≥1%；
11. latency regression；
12. trusted cohort missing；
13. sample insufficient；
14. rehearsal/evidence missing。

高优先级 blocker 不得被低优先级 `NOT_READY` 覆盖。

---

## 6. API

### 6.1 Scoped verification

```text
GET /api/admin/agent-runtime/autotutor-canary/verification
```

Query：

```text
expected_commit
expected_config_version
window_start
window_end
minimum_control=100
minimum_graph=100
```

要求：

- admin only；
- production authentication required；
- 所有参数有长度、格式和上限校验；
- expected commit 在 production 必须是完整 SHA；
- exact snapshot 模式必须同时提供 start/end；
- start < end；
- 最大窗口 7 天；
- 返回 PII-free aggregate；
- 400 用于无效请求；
- 401/403 保持现有认证语义；
- query/database 异常返回稳定 `UNKNOWN/NO_GO` payload，不返回 SQL 文本。

### 6.2 Exact snapshot

```text
POST /api/admin/agent-runtime/autotutor-canary/snapshots
```

请求只包含：

```json
{
  "expected_commit": "...",
  "expected_config_version": "...",
  "window_start": "...",
  "window_end": "...",
  "minimum_control": 100,
  "minimum_graph": 100
}
```

响应新增：

```json
{
  "snapshot_sha256": "sha256:...",
  "snapshot": {
    "slice": {},
    "schema": {},
    "configuration": {},
    "cohort": {},
    "aggregate": {},
    "decision": "GO|NO_GO"
  }
}
```

POST 只生成/封存运维 snapshot，不修改 BPS、session、account 或教学数据。

### 6.3 Evidence 查询

复用或补充：

```text
GET /api/admin/agent-runtime/autotutor-canary/evidence
```

只返回最新匹配 commit/config/environment 的 schema v3 evidence 摘要。默认不返回完整 aggregate；下载完整 evidence 时使用显式 `include_payload=true`，仍需 admin。

---

## 7. 远程验证 CLI

### 7.1 新脚本

```text
scripts/verify_autotutor_canary_deployment.py
```

CLI：

```text
--api-base
--expected-commit
--expected-config-version
--phase preflight|control_snapshot|canary_snapshot|rollback_verify
--window-start
--window-end
--minimum-control
--minimum-graph
--output-json
--output-markdown
```

认证只读取：

```text
API_TOKEN
```

禁止把 token 放到 CLI 参数，避免进入 process list 和 Actions log。

### 7.2 网络策略

```text
1. GET /api/health，timeout 20s
2. 若超时，等待短退避后重试一次
3. GET scoped verification，timeout 30s
4. 仅 exact phase 请求 snapshot
5. 校验响应 content type、schema version 和 provenance
6. 写 PII-free artifact
```

总重试预算不超过 120 秒。

### 7.3 退出码

```text
0 = phase contract satisfied
2 = NOT_READY
3 = BLOCKED / NO_GO
4 = UNKNOWN / network / invalid payload
5 = provenance mismatch
```

GitHub workflow 可根据 phase 决定 `NOT_READY` 是否失败；production GO workflow 中所有非 0 均失败。

---

## 8. Evidence Supply Chain

### 8.1 Snapshot 与 Evidence 分工

- snapshot：服务端对固定窗口与固定部署的只读事实封存；
- rehearsal artifact：部署操作事实；
- evidence：snapshot + rehearsals + schema/config/deployment provenance 的最终 hash-sealed 决策。

不允许直接把滚动 rollout status 复制成 GO evidence。

### 8.2 Evidence builder 扩展

`scripts/build_autotutor_canary_evidence.py` 增加二选一输入：

```text
--database-source
--snapshot-path
```

约束：

- production workflow 优先使用 `--snapshot-path`；
- snapshot hash 必须先验证；
- evidence slice 必须与 snapshot slice 完全一致；
- expected commit/config/environment 必须由 workflow 显式传入；
- drill artifact 必须有 schema、commit、config、result、generated_at；
- 任一 drill 为 fail/not_run，evidence 不得 GO；
- evidence 生成后再次做敏感字段扫描；
- artifact retention 至少 30 天；
- 持久化数据库是最终步骤，失败不得影响学生业务请求。

### 8.3 Drill artifact

```json
{
  "schema_version": 1,
  "deployed_commit": "...",
  "config_version": "...",
  "environment": "production",
  "generated_at": "...",
  "results": {
    "restart": "pass|fail|not_run",
    "writer_failure": "pass|fail|not_run",
    "kill_switch": "pass|fail|not_run",
    "rollback": "pass|fail|not_run"
  },
  "notes": ["reason_code_only"]
}
```

不得包含操作者姓名、token、账号 ID、学生 ID、session ID 或原始响应。

---

## 9. Rehearsal 合同

### 9.1 Restart rehearsal

目标：证明重新部署/冷启动后：

- deployed commit 不变或等于预期新 commit；
- schema 仍为 016；
- config fingerprint 不变；
- BPS 未意外改变；
- session/CAS 数据未丢失；
- 已提交 transition 不重放；
- writer health 恢复为 ok。

Render free service 冷启动只作为 warning；超过总预算仍不可达则 UNKNOWN/NO_GO。

### 9.2 Writer-failure rehearsal

生产中禁止通过破坏真实学生写入进行演练。

允许方式：

- 在 staging 使用 fault injection 完整验证；或
- 在 production 使用专用 operator/test scope，明确 `rollout_eligible=0`，且不执行学生业务 effect；
- 验证 observation write failure audit 可见；
- 验证 scoped health 进入 degraded；
- 验证 Graph Admission fail-closed；
- 故障移除后等待隔离窗口恢复；
- rehearsal row 永远不进入 verified production aggregate。

只有能证明上述链路的 artifact 才为 pass。

### 9.3 Kill-switch rehearsal

只允许在 BPS 0 或批准的 1% 窗口执行：

1. 记录切换前 config/commit；
2. 设置 kill switch；
3. scoped verification 必须显示 BLOCKED；
4. 新 session Graph assignment 必须为 0；
5. existing Graph test session 在 Provider 前永久降级；
6. 恢复 kill switch 后不自动提升旧 session；
7. BPS 保持 0，除非仍在已批准窗口；
8. 输出 reason-code-only artifact。

### 9.4 Rollback verification

rollback 的完成条件不是“配置已点击”，而是：

- mode=legacy 或 BPS=0；
- Graph assignment 在回滚时间后为 0；
- writer health ok；
- schema ready；
- 已提交 effect duplicate=0；
- existing downgraded session 不回升；
- public AutoTutor 仍可走 Legacy；
- scoped verification phase 为 `rollback_verified`。

---

## 10. GitHub Actions

### 10.1 新 workflow

```text
.github/workflows/autotutor-production-verification.yml
```

仅允许：

```yaml
on:
  workflow_dispatch:
```

Inputs：

```text
action
expected_commit
expected_config_version
window_start
window_end
minimum_control
minimum_graph
release_required
```

Secrets：

```text
AUTOTUTOR_PRODUCTION_API_BASE
AUTOTUTOR_PRODUCTION_API_TOKEN
```

### 10.2 安全要求

- job 绑定 `production-verification` GitHub Environment；
- Environment 配置 required reviewer；
- checkout ref 必须解析到 expected commit；
- expected commit 必须是 origin/main 可达 commit；
- 禁止 workflow 修改 Render env；
- 禁止把 secret 写入 `$GITHUB_OUTPUT` 或 artifact；
- URL 日志不得包含 query token；
- artifact 名包含短 SHA 和 action，不包含 actor；
- permissions 默认 `contents: read`；
- 不授予 deployments、packages、id-token 或 repository write；
- release-required 时 NOT_READY 也应失败；
- always upload 失败诊断 artifact。

### 10.3 与现有 CI 的关系

- 普通 push CI：继续跑代码、migration、browser、Docker；
- production RAG workflow：保持独立；
- Agent Evidence Profiles：保持独立；
- AutoTutor Production Verification：只在人工 dispatch 运行；
- 不把外部生产状态加入 PR 必过检查，避免冷启动/网络波动阻塞开发 CI；
- v1.50 评审必须引用一次成功的 AutoTutor production verification run。

---

## 11. AgentOps UI

现有 AutoTutor Canary panel 增加：

- deployed commit 与 expected commit 是否一致；
- migration revision；
- executor mode/BPS/config fingerprint；
- control progress 与 Graph committed progress；
- phase/status/decision/next action；
- latest exact snapshot hash；
- latest evidence hash；
- restart/writer/kill-switch/rollback rehearsal 状态；
- rollback required 明显红色提示；
- cold-start warning 与最后成功检查时间。

前端约束：

- 不计算 GO；
- 不提供修改 BPS/kill switch 按钮；
- 不展示 bucket salt；
- 不展示 verified actor 标识，只展示数量；
- UNKNOWN 不得用绿色；
- stale snapshot 显示过期；
- exact snapshot 与 rolling status 明确标注，避免混淆。

---

## 12. 数据与隐私

所有新增 API、CLI、workflow artifact 和日志禁止包含：

```text
student_id
session_id
actor_id
username
display_name
raw answer
question/teaching/reflection text
profile/weakpoint/retrieval content
trace_id
transition_id
effect_key
state_json
API token
bucket salt
database URL
```

允许字段：

- count、rate、percentile；
- reason code；
- commit/config/environment；
- schema revision；
- config fingerprint；
- snapshot/evidence hash；
- phase/status/decision；
- UTC timestamps；
- rehearsal pass/fail/not_run。

敏感字段扫描必须覆盖嵌套 JSON key 和字符串值，不能只扫描顶层。

---

## 13. 失败语义

| 场景 | 状态 | decision | next action |
|---|---|---|---|
| 服务冷启动后成功 | READY/NOT_READY + warning | 依 phase | 继续当前阶段 |
| 服务总预算内不可达 | UNKNOWN | NO_GO | wait_for_deployment |
| commit mismatch | BLOCKED | NO_GO | fix_deployment_contract |
| schema <016 | BLOCKED | NO_GO | fix_deployment_contract |
| BPS >100 | BLOCKED | NO_GO | stop_canary |
| writer degraded | BLOCKED | NO_GO | stop_canary |
| verified cohort=0 | NOT_READY | NO_GO | approve_verified_cohort |
| control <100 | NOT_READY | NO_GO | collect_control |
| Graph committed <100 | NOT_READY | NO_GO | collect_canary |
| comparator unknown/mismatch | BLOCKED | NO_GO | stop_canary |
| fallback ≥1% | BLOCKED | NO_GO | stop_canary |
| exact snapshot 缺失 | NOT_READY | NO_GO | build_exact_snapshot |
| rehearsal 缺失 | NOT_READY | NO_GO | complete_rehearsals |
| evidence hash invalid | BLOCKED | NO_GO | persist_evidence |
| BPS 0 且回滚指标安全 | VERIFIED | GO | review_v150_entry |

任何异常不得导致生产请求绕过 Legacy fallback。

---

## 14. 实施范围

| 文件 | 变更 |
|---|---|
| `render.yaml` | 声明 AutoTutor BPS 0 安全配置 |
| `backend/agent_runtime/autotutor_canary_verification.py` | scoped phase/blocker/next-action 唯一合同 |
| `backend/agents/autotutor_execution.py` | 配置指纹与安全摘要 |
| `backend/agent_runtime/rollout_observations.py` | exact snapshot 输入与稳定聚合 |
| `backend/agent_runtime/evidence_store.py` | snapshot/evidence 绑定校验 |
| `backend/api/routers/agent_runtime.py` | verification/snapshot/evidence admin API |
| `scripts/verify_autotutor_canary_deployment.py` | 远程 preflight、重试、退出码、artifact |
| `scripts/build_autotutor_canary_evidence.py` | 支持 snapshot-path 与 drill artifact |
| `.github/workflows/autotutor-production-verification.yml` | 手工审批 production workflow |
| `backend/agent_ops.py` | verification/snapshot/rehearsal 摘要 |
| `frontend/app/eval/page.tsx` | AutoTutor verification panel |
| `.env.example` / `README.md` | v1.49.4 配置与 runbook |
| `eval/autotutor_production_verification_*` | scoped contract、API、CLI、workflow 测试 |
| `scripts/release_gate.py` | 新增 v1.49.4 deterministic gates |

不新增业务数据表。若 exact snapshot 需要持久化，优先复用 `agent_release_evidence`，以不同 runtime mode/type 或 payload subtype 区分；只有证明复用会破坏唯一约束或查询语义时才允许 migration 017，并需单独说明。

---

## 15. 测试计划

### 15.1 新增 deterministic suites

```text
eval/autotutor_production_verification_contract_smoke.py
eval/autotutor_production_verification_api_smoke.py
eval/autotutor_production_snapshot_smoke.py
eval/autotutor_production_remote_cli_smoke.py
eval/autotutor_production_cold_start_retry_smoke.py
eval/autotutor_production_workflow_contract_smoke.py
eval/autotutor_production_evidence_chain_smoke.py
eval/autotutor_production_rollback_verification_smoke.py
eval/autotutor_production_privacy_smoke.py
```

### 15.2 必须保留

- Admission fail-closed/cache；
- existing session permanent downgrade；
- exact canary aggregate；
- writer failure；
- comparator sensitivity；
- full outcome parity ≥108/108；
- active transaction single commit；
- finalize fault injection 8/8；
- transition idempotency；
- false mastery 与 adaptive difficulty；
- session recovery；
- migration upgrade/rehearsal/lock；
- production BPS cap；
- auth/cohort/scope isolation；
- AgentOps API/UI contract；
- frontend lint/unit/build。

### 15.3 负向测试

- wrong commit；
- short commit；
- wrong config；
- non-production environment；
- schema 015；
- BPS 101；
- comparator disabled；
- fallback disabled；
- kill switch enabled；
- writer degraded/unavailable；
- verified cohort missing；
- control/Graph insufficient；
- comparator unknown；
- fallback exactly 1%；
- duplicate effect；
- unauthorized Graph；
- invalid/missing window；
- stale/tampered snapshot；
- snapshot/evidence slice mismatch；
- drill not_run/fail；
- API 401/403；
- cold start first timeout then success；
- repeated timeout；
- malformed JSON/HTML response；
- artifact sensitive field injection；
- workflow missing Environment/secret；
- workflow attempts write permission or automatic BPS mutation。

---

## 16. Release Gate

### 16.1 Development Complete

```text
python compile
v1.49.4 targeted suites
existing AutoTutor safety suites
backend full smoke
fast release gate
workflow YAML contract
frontend lint
frontend unit tests
frontend production build
git diff --check
sensitive field scan
```

Development Complete 不等于 Production Verified。

### 16.2 Deployment Baseline Ready

- clean commit 已 push；
- GitHub CI 全绿；
- Docker build 通过；
- Render deployed commit 精确匹配；
- schema 016 ready；
- declarative AutoTutor config 存在；
- mode=legacy；
- BPS=0；
- observation health=ok；
- scoped preflight 可认证访问；
- cold-start retry 行为可解释；
- production workflow 可手工 dispatch。

### 16.3 Production Verified

- verified cohort 经单独审批存在；
- control transitions ≥100；
- 人工批准一次 100 BPS 窗口；
- committed Graph transitions ≥100；
- comparator parity=100%；
- comparator unknown=0；
- fallback rate <1%；
- observation failures=0；
- duplicate committed effect=0；
- unauthorized Graph=0；
- provenance coverage=100%；
- transition coverage 完整；
- active p95 relative regression ≤20%；
- active p95 absolute increase ≤50ms；
- exact snapshot hash 有效；
- restart/writer/kill-switch/rollback rehearsal pass；
- evidence commit/config/environment/window/cohort 完全匹配；
- evidence 已持久化并可重新加载；
- 评审结束后 BPS=0，除非另有明确授权；
- rollback verification pass；
- production 从未超过 1%。

---

## 17. 实施顺序

### Milestone A：Deployment Contract

- Render 显式 AutoTutor 配置；
- config fingerprint；
- production BPS 0 验证；
- 配置脱敏测试。

### Milestone B：Scoped Verification

- 唯一 phase/status/blocker/next-action 服务；
- admin verification API；
- 与 existing rollout status 语义对齐；
- strict generic Runtime gate 保持不变。

### Milestone C：Exact Snapshot

- fixed window aggregate；
- snapshot sealing/tamper check；
- admin snapshot API；
- PII scan。

### Milestone D：Remote CLI

- auth header；
- cold-start retry；
- stable exit codes；
- JSON/Markdown artifact；
- network/provenance negative tests。

### Milestone E：Evidence Workflow

- snapshot-path builder；
- drill artifact；
- manual GitHub workflow；
- Environment approval contract；
- always-upload diagnostics。

### Milestone F：AgentOps 与开发门禁

- verification panel；
- snapshot/evidence/rehearsal 状态；
- backend/full/fast/frontend gates；
- clean commit 与 push。

### Milestone G：Production Operations

- BPS 0 deploy；
- control collection；
- verified cohort approval；
- manual 1% enablement；
- exact snapshot；
- rehearsals；
- evidence persist；
- BPS 0 rollback；
- review v1.50 entry。

---

## 18. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 通用 Runtime gate 误阻断 AutoTutor | 新增 scoped gate，不放宽原 gate |
| scoped gate 绕过通用安全能力 | 明确复用 auth/schema/writer/deployment 基础检查 |
| workflow 被误当流量控制器 | 只读设计，不授予 Render 写权限 |
| Blueprint 意外开启 Canary | mode=legacy、BPS=0 固定默认，active 只允许人工 Dashboard 变更 |
| 冷启动造成假失败 | 有界 health warmup、重试与 warning；总失败仍 UNKNOWN |
| rolling status 被当 immutable evidence | exact window snapshot + hash sealing |
| 客户端伪造 aggregate | snapshot 指标只由服务端数据库计算 |
| workflow token 泄漏 | token 只来自 env header，不进参数/log/artifact |
| drill 污染真实数据 | operator/test scope，rollout_eligible=0，禁止学生 effect |
| verified cohort 被滥用 | demo/pilot 禁止加入，cohort 变更继续审计 |
| config version 不变但 salt 漂移 | config fingerprint 绑定 salt hash |
| rollback 只改配置未验证 | rollback verification 要求 post-window Graph assignment=0 |
| snapshot 保存增加 migration | 优先复用 evidence 表；必要时单独评审 migration 017 |
| v1.50 被提前启动 | Production Verified checklist 与 workflow run 作为硬门槛 |

---

## 19. v1.50 进入条件

只有以下证据同时存在，才能创建 v1.50 Spec：

1. v1.49.4 clean commit 已部署；
2. GitHub CI 成功；
3. AutoTutor production verification workflow 成功；
4. exact snapshot 为 GO；
5. immutable evidence 为 GO；
6. committed Graph transitions ≥100；
7. 所有 safety/latency/provenance 指标通过；
8. 全部 rehearsal pass；
9. BPS 已恢复 0 或有明确保持 1% 的审批；
10. rollback verification pass。

v1.50 才允许讨论：

- Graph 默认 executor；
- Comparator 从 100% 在线双算调整为采样；
- Legacy orchestration 删除计划；
- shadow/active telemetry schema 收敛；
- 更高流量阶段；
- 双执行成本优化。

即使进入 v1.50，也必须先保留即时 rollback 路径，并单独证明旧 session、effect idempotency 和教学结果不变。

---

## 20. 最终验收问题

评审必须能用代码、API、workflow artifact 和不可变 evidence 回答“是”：

1. Render 是否显式声明 AutoTutor mode/BPS/config/comparator/fallback/kill switch？
2. 普通 push 是否永远不会自动把 BPS 从 0 改到 1%？
3. scoped preflight 是否只判断 AutoTutor 相关门禁，同时保留通用 Runtime gate？
4. deployed commit/config/schema 是否与 workflow expected values 精确匹配？
5. cold start 是否有界重试，持续不可达是否 UNKNOWN/NO_GO？
6. exact snapshot 是否由服务端固定窗口聚合，而不是客户端自报？
7. snapshot 是否 hash-sealed 且 tamper 可检测？
8. snapshot/evidence 是否不包含学生、会话、trace、effect 或 secret？
9. workflow 是否 admin-authenticated、Environment-approved、只读且最小权限？
10. verified cohort 是否独立审批并排除 demo/pilot/operator？
11. control、assigned、selected、committed、fallback 是否有稳定分母？
12. comparator unknown 是否仍阻断 GO？
13. writer/restart/kill-switch/rollback rehearsal 是否绑定同一部署 provenance？
14. rollback 后 Graph assignment 是否确实归零，而不只是配置声称归零？
15. evidence 是否可重新加载并验证 hash？
16. production 是否从未超过 1%？
17. v1.50 是否仍被 Production Verified 硬门槛阻止？

任一答案为“否”，v1.49.4 不得标记 Production Verified，也不得创建 v1.50 Spec。
