# EduAgent AutoTutor Production Verification Bootstrap & Execution Closure v1.49.6 Spec

**状态：** Approved for implementation
**日期：** 2026-09-02
**前置版本：** v1.49.5 AutoTutor Production Attestation & Rollback Closure
**后续候选：** v1.50 AutoTutor Single Executor Consolidation（仅在本 Spec 的 Production Verified 门禁全部满足后立项）

## 1. 背景与项目实际状态

截至 `4beb26d8f7bdd4b5b167a13cdc13bdead8d00fd1`，AutoTutor 已完成从
LangGraph Shadow、独立 transition、Active Canary admission 到 schema v4 candidate/final
生产证据链的开发工作：

- Legacy 与 Graph 使用同一份确定性 observation bundle 和 transition kernel；
- Graph 只负责 transition orchestration，不越过 AutoTutor CAS 与领域事务提交边界；
- 新会话按可信 cohort、稳定 bucket、admission、mode 和 BPS 选择执行器；
- Graph 异常或 comparator mismatch 可在提交前回退 Legacy；
- schema v4 candidate 与 final 已绑定 cohort fingerprint、runtime state、exact snapshot 和 rehearsal；
- rollback finalization 要求 post-window Legacy 至少 20 条且 Graph assigned/selected 均为 0；
- 默认生产配置仍为 `legacy + BPS 0`，普通 push 不会自动放量。

当前真实外部状态为：

1. `4beb26d` 已由 Render 部署，生产 `/api/ready?require_runtime=true` 返回相同完整 commit；
2. 生产 PostgreSQL migration `016` ready，rollout observation writer health 为 `ok`；
3. 该提交的 GitHub `EduAgent CI` 已成功；
4. `AutoTutor Production Verification` workflow 已注册但从未运行；
5. GitHub 仓库尚不存在 `production-verification` Environment；
6. Repository Actions secrets 当前为空，workflow 所需的
   `AUTOTUTOR_PRODUCTION_API_TOKEN` 尚未形成可验证配置；
7. 尚无真实 control ≥100、committed Graph ≥100、schema v4 candidate、post-rollback
   exact snapshot 或 schema v4 final GO evidence；
8. 全局 Runtime readiness 仍受 LLM capability manifest 和旧 Runtime rollout evidence
   影响，不能代替 AutoTutor scoped production verification。

因此，v1.49.5 已达到 **Development Complete**，但没有达到 **Production Verified**。
当前不能创建或实施 v1.50，也不能删除 Legacy、关闭所有 comparator 或提高生产流量。

## 2. 迭代决定

v1.49.6 不新增教学功能，不改变 transition 语义，也不执行 Single Executor Consolidation。
本迭代只解决一个问题：

> 将已经实现的 AutoTutor 生产验证能力，从“代码存在但外部前置条件缺失”升级为
> “可安全启动、可人工审批、可绑定 CI 与部署 provenance、可完整执行并可审计复核”的
> 真实生产闭环。

该闭环必须明确区分：

- **代码交付：** workflow guard、CI provenance、部署收敛、错误分类、receipt、AgentOps 与测试；
- **仓库配置：** GitHub Environment、required reviewers、deployment branch policy、Environment secret；
- **生产操作：** control 收集、人工 1% Canary、演练、BPS 0 回滚和 final evidence；
- **后续决策：** 只有 final GO 被重新加载验证后，才允许讨论 v1.50。

## 3. 目标

### 3.1 P0 目标

1. 验证目标 commit 的 `EduAgent CI` 已完成且结论为 success；
2. 缺失生产 Environment、审批保护或 API token 时 fail-closed；
3. workflow 只验证已经部署的 immutable commit，不接受短 SHA 或漂移部署；
4. 对 Render 冷启动与 auto-deploy 收敛使用有界等待，不把暂时未收敛误判为永久失败；
5. 输出 PII-free workflow receipt，绑定 run、commit、config、action、window 与 evidence hash；
6. 完成 preflight、control、canary candidate、rollback final 四阶段真实操作；
7. 操作完成后生产必须恢复 `legacy + BPS 0`；
8. final schema v4 GO 必须持久化、重新 GET 并验证 SHA256；
9. 把 v1.50 entry decision 变成显式 `GO | NO_GO`，默认 `NO_GO`。

### 3.2 P1 目标

- AgentOps 展示 CI provenance、部署收敛、Environment readiness、receipt 和 evidence stage；
- CLI 对配置缺失、认证失败、部署漂移、样本不足和数据安全 blocker 给出稳定错误码；
- workflow artifact 至少保留 90 天，失败时仍上传脱敏结果；
- README/runbook 给出不依赖隐式知识的人工执行顺序。

## 4. 非目标

本迭代明确不做：

- 自动创建 GitHub Environment、reviewer 或 secret；
- 把 token、Render 管理密钥或 GitHub PAT 写入仓库、日志或 artifact；
- 自动修改 Render `EXECUTOR_MODE`、`BPS`、kill switch 或 cohort；
- 自动生成生产学生请求或将 demo/pilot/operator 账号加入 verified cohort；
- 将生产 BPS 提升到 100 以上；
- 删除 Legacy executor 或 Legacy transition wrapper；
- 关闭 Graph active transition 的 Legacy comparator；
- 引入 LangGraph checkpointer、interrupt 或 migration 017；
- 修改 AutoTutor 教学策略、题目生成、mastery、weakpoint 或 effect 语义；
- 用全局 `/api/ready` 的其他 Agent blocker 替代 AutoTutor scoped verification；
- 自动开始 v1.50。

## 5. 信任边界与职责

| 边界 | 权威来源 | 允许行为 | 禁止行为 |
|---|---|---|---|
| GitHub CI | GitHub Actions API | 只读确认目标 commit 的 CI 结论 | 重新解释失败为通过 |
| Environment | GitHub Repository Settings | reviewer 审批、分支限制、Environment secret | workflow 自动创建或弱化保护 |
| 部署 provenance | 生产 API 服务端 | 返回完整 deployed commit/config/environment | 客户端自报部署状态 |
| Canary aggregate | PostgreSQL fixed-window 服务端聚合 | 计算 control/Graph/fallback/parity/latency | 客户端上传 aggregate |
| Evidence | release evidence store | 校验并持久化 candidate/final | 覆盖或删除已有 evidence |
| Render 配置 | 人工受控操作 | 审批后改 mode/BPS，完成后恢复 | workflow 持有 Render 写权限 |
| Workflow artifact | GitHub Actions | 保存脱敏 snapshot/receipt | 保存 token、学生内容或标识符 |

## 6. 前置配置合同

### 6.1 GitHub Environment

首次运行生产验证前，仓库管理员必须人工创建：

```text
production-verification
```

Environment 必须满足：

- 至少 1 名 required reviewer；
- deployment branch policy 只允许默认分支或受保护分支；
- 不允许通过普通 push 绕过审批进入生产验证 job；
- Environment 名称与 workflow 中的 `environment` 完全一致；
- 若 GitHub 套餐不支持 reviewer protection，必须记录显式 blocker，不能声称已审批。

不得通过“先运行 workflow 让 GitHub 自动创建同名无保护 Environment”的方式完成配置。

### 6.2 Environment secret

将公开 API 地址配置为 `production-verification` Environment variable：

```text
AUTOTUTOR_PRODUCTION_API_BASE
```

将以下 secret 配置在 `production-verification` Environment，而不是 repository scope：

```text
AUTOTUTOR_PRODUCTION_API_TOKEN
```

合同要求：

- token 对应一个最小权限 production admin 身份；
- API base 必须是 HTTPS 地址，缺失时返回 `production_api_base_missing`；
- 仅允许读取 verification/snapshot/evidence，并按既有 API 持久化验证 evidence；
- workflow 只检查 token 是否非空，不输出长度、前缀、hash 或请求 header；
- API 返回 401/403 时映射为 `production_api_auth_failed`；
- secret 缺失时映射为 `production_api_token_missing`，在任何 curl 前退出；
- token 轮换后旧 token 必须失效。

### 6.3 配置完成证明

仓库设置不进入 Git，因此必须形成一份不含 secret 的 operator attestation：

```json
{
  "schema_version": 1,
  "attestation_type": "github_environment_bootstrap",
  "repository": "zjgpolaris/edu-agent-platform",
  "environment": "production-verification",
  "required_reviewer_count": 1,
  "branch_policy": "protected_or_default",
  "api_token_configured": true,
  "verified_at": "ISO-8601 UTC",
  "verified_by": "github-actor"
}
```

该 attestation 只记录布尔状态和公开元数据，不记录 reviewer email、token 或权限响应正文。

## 7. CI provenance gate

### 7.1 输入

所有 action 必须要求：

```text
expected_commit = 40 位小写 Git SHA
expected_config_version = 非空、长度 <= 120
```

短 SHA、branch 名、tag 或非十六进制输入立即拒绝。

### 7.2 判定

workflow 使用 GitHub Actions API 只读查询目标 commit 对应的 `EduAgent CI` push run：

- 不存在：`ci_run_missing`；
- queued/in_progress：`ci_run_not_complete`；
- cancelled/skipped/failure：`ci_run_not_successful`；
- success：`ci_provenance_verified`；
- 多个 run：只接受最新 completed push run，且必须 success；
- pull_request run、其他 workflow 或其他 commit 不能证明目标 commit。

workflow 权限增加且只增加：

```yaml
permissions:
  contents: read
  actions: read
```

不得增加 `deployments: write`、`contents: write`、`secrets: write` 或云平台写权限。

### 7.3 Checkout

只有 CI gate 通过后，才能 checkout `expected_commit`。后续脚本必须来自目标 immutable revision，
不能使用 workflow 默认分支上更新后的脚本验证旧 commit。

## 8. 部署收敛合同

Render `autoDeploy=true`，push 后代码部署和 GitHub CI 可能并行完成。验证 CLI 必须区分：

- API 冷启动；
- API 暂时不可达；
- 部署尚未收敛；
- 部署已收敛但 commit/config 不匹配；
- 生产验证自身 blocker。

建议默认策略：

```text
最大等待：5 分钟
单次请求超时：30 秒
退避：5s, 10s, 20s, 30s，之后固定 30s
成功条件：连续 2 次返回相同 deployed commit/config/environment
```

结果代码：

| 条件 | 结果 |
|---|---|
| 暂时 5xx/timeout 后恢复 | warning，不单独阻断 |
| 5 分钟后仍不可达 | `production_api_unavailable` |
| commit 在等待期内收敛 | pass |
| 5 分钟后 commit 不一致 | `deployment_not_converged` |
| config 不一致 | `config_version_mismatch` |
| environment 非 production | `environment_not_production` |

等待逻辑只能 GET，不触发 Render deploy hook。

## 9. Production Verification 状态机

```text
bootstrap_missing
  -> bootstrap_ready
  -> ci_pending | ci_blocked | ci_verified
  -> deployment_converging | deployment_blocked | preflight_ready
  -> control_collecting
  -> ready_for_manual_one_percent
  -> canary_collecting
  -> canary_ready_for_snapshot
  -> candidate_persisted
  -> rollback_pending
  -> rollback_collecting | rollback_blocked
  -> rollback_ready_for_finalize
  -> rollback_verified
  -> v150_entry_go
```

任何阶段发现以下事件时必须转为 `NO_GO`：

- commit/config/environment/cohort fingerprint 漂移；
- observation writer failure；
- unauthorized Graph traffic；
- duplicate transition/effect；
- comparator unknown/mismatch；
- fallback 超过阈值；
- latency 或 safety gate 不通过；
- rollback window 中出现 Graph assignment/selection；
- evidence hash、stage 或 provenance 不一致；
- artifact privacy scan 失败。

## 10. 四阶段执行合同

### 10.1 Preflight

依次验证：

1. Environment 审批已完成；
2. API token 存在；
3. 目标 CI success；
4. 生产 commit/config/environment 收敛；
5. migration ≥016；
6. AutoTutor observation writer healthy；
7. verified runtime cohort ready；
8. comparator/fallback enabled；
9. kill switch off；
10. 当前为 `legacy + BPS 0`；
11. 不存在未解释 Graph traffic。

Preflight 只表示可以开始收集 control，不允许自动放量。

### 10.2 Control snapshot

- 使用 exact UTC start/end；
- verified runtime control transitions ≥100；
- assigned/selected Graph 为 0；
- observation health 为 ok；
- snapshot hash 校验通过；
- 达标后状态为 `ready_for_manual_one_percent`。

### 10.3 Canary candidate

人工在 Render 中将 mode 设置为 `active_canary`、BPS 设置为最多 100 后：

- 等待配置稳定；
- exact window 内 committed Graph transitions ≥100；
- comparator match 必须为 100%，unknown 为 0；
- unauthorized、duplicate、writer failure 为 0；
- fallback 和 latency 满足 v1.49.4/v1.49.5 门槛；
- restart、writer-failure、kill-switch rehearsal 均为 pass；
- 构建并持久化 schema v4 `candidate / CANDIDATE_GO`；
- 重新 GET 并验证 candidate SHA256。

Candidate 不是 Production Verified。candidate 成功后的唯一下一步是人工恢复
`legacy + BPS 0` 并收集 rollback window。

### 10.4 Rollback final

人工恢复 `legacy + BPS 0` 后：

- exact post-rollback window 内新 Legacy transitions ≥20；
- assigned Graph = 0；
- selected Graph = 0；
- runtime state 为 legacy/BPS 0/kill off；
- cohort fingerprint 与 candidate 完全一致；
- rollback rehearsal 为 pass；
- final 引用已持久化 candidate SHA 和 exact rollback snapshot SHA；
- 持久化 schema v4 `final / GO`；
- 重新 GET final 并校验 stage、decision、candidate hash、rollback hash 和 final hash。

只有此阶段完成，状态才为 `rollback_verified`。

## 11. Workflow receipt

每次 workflow 无论成功或失败都生成：

```json
{
  "schema_version": 1,
  "receipt_type": "autotutor_production_verification",
  "repository": "zjgpolaris/edu-agent-platform",
  "workflow_run_id": "public-run-id",
  "workflow_run_attempt": 1,
  "workflow_actor": "github-login",
  "action": "preflight|control_snapshot|canary_snapshot|rollback_verify",
  "expected_commit": "40-char-sha",
  "deployed_commit": "40-char-sha-or-null",
  "config_version": "v1.49.6-production-execution",
  "environment": "production",
  "ci": {
    "workflow": "EduAgent CI",
    "status": "verified|blocked|unknown",
    "run_id": "public-run-id-or-null"
  },
  "window": {
    "start": "ISO-8601 UTC or null",
    "end": "ISO-8601 UTC or null"
  },
  "result": {
    "status": "READY|NOT_READY|BLOCKED|VERIFIED|UNKNOWN",
    "decision": "GO|NO_GO",
    "phase": "stable-phase",
    "blockers": []
  },
  "snapshot_sha256": "sha256:... or null",
  "evidence_stage": "candidate|final|null",
  "evidence_sha256": "sha256:... or null",
  "generated_at": "ISO-8601 UTC"
}
```

要求：

- canonical JSON 后计算 receipt SHA256；
- artifact retention 至少 90 天；
- 写入 `$GITHUB_STEP_SUMMARY` 时只输出 phase、decision、blocker、计数和 hash；
- 失败步骤之后仍运行 receipt 与 privacy scan；
- receipt 不是 release evidence，不能替代 schema v4 final；
- workflow URL 可由 repository + run id 恢复，不在服务端保存凭证。

## 12. CLI 与错误合同

`scripts/verify_autotutor_canary_deployment.py` 增加或明确：

```text
--wait-for-deployment
--deployment-timeout-seconds 300
--require-ci-provenance
--ci-receipt-path <path>
--output-receipt <path>
```

CLI 退出码建议：

| 退出码 | 含义 |
|---:|---|
| 0 | 请求阶段达到 READY/VERIFIED |
| 2 | 参数或本地合同错误 |
| 3 | 认证/Environment 前置条件错误 |
| 4 | CI provenance 不通过 |
| 5 | 部署不可达或未收敛 |
| 6 | 生产指标 NOT_READY/BLOCKED |
| 7 | snapshot/evidence/receipt 完整性错误 |
| 8 | privacy scan 失败 |

日志禁止输出完整 response headers、Authorization、请求正文中的敏感字段或 shell trace。

## 13. API 合同

优先复用现有 API，不新增写入能力：

```text
GET  /api/admin/agent-runtime/autotutor-canary/verification
GET  /api/admin/agent-runtime/autotutor-canary/snapshot
GET  /api/admin/agent-runtime/autotutor-canary/evidence
POST /api/admin/agent-runtime/autotutor-canary/evidence
```

仅在现有响应中补充不会泄露数据的字段：

- `deployment_converged`；
- `ci_provenance` 只由 workflow receipt 表达，服务端不得信任客户端 CI 声明作为生产事实；
- `evidence_stage`；
- `candidate_sha256`；
- `final_sha256`；
- `v150_entry_ready`；
- `v150_entry_blockers`。

`v150_entry_ready=true` 必须由已重新加载的 schema v4 final GO 推导，不能由 query 参数设置。

## 14. AgentOps 展示

AutoTutor verification 卡片增加：

- deployed/expected commit 是否一致；
- CI provenance：unknown/pending/verified/blocked；
- Environment bootstrap：unknown/configured/blocked；
- API credential 只显示 configured/missing，不显示任何 token 信息；
- control、Graph、rollback 样本进度；
- candidate/final stage 与 hash 前 12 位；
- rollback Graph assigned/selected；
- v1.50 entry：`NO_GO | GO`；
- 下一人工动作。

UI 不提供修改 BPS、mode、kill switch、cohort 或 secret 的按钮。

## 15. 隐私与安全

receipt、snapshot、evidence、workflow log 和 summary 必须递归拒绝：

```text
token authorization password secret bucket_salt cookie
email student_id actor_id account_id session_id trace_id
effect_id transition_id question answer prompt response content
```

允许：

- public Git commit、workflow/run id；
- config version；
- SHA256；
- 枚举 phase/status/decision/blocker；
- 聚合计数与延迟分位数；
- Environment 名称与布尔配置状态；
- GitHub login 形式的 workflow actor，不记录 email。

任何 privacy 命中都必须让 workflow 失败，且不上传违规 artifact。

## 16. 建议代码变更范围

| 文件 | 变更 |
|---|---|
| `.github/workflows/autotutor-production-verification.yml` | CI gate、token guard、receipt、90 天 artifact、最小权限 |
| `scripts/verify_autotutor_canary_deployment.py` | 部署收敛、有界重试、稳定错误码、receipt 输出 |
| `scripts/build_autotutor_canary_evidence.py` | 接收已验证 workflow provenance，但不信任客户端 aggregate |
| `backend/agent_runtime/autotutor_canary_verification.py` | v1.50 entry projection 与稳定 blocker |
| `backend/api/routers/agent_runtime.py` | 暴露新增 PII-free summary |
| `backend/agent_runtime/rollout_status.py` | AgentOps 聚合状态 |
| `frontend/app/eval/page.tsx` | 展示 CI/bootstrap/entry 状态 |
| `eval/autotutor_production_workflow_contract_smoke.py` | workflow 权限、CI、receipt 合同 |
| `eval/autotutor_production_remote_cli_smoke.py` | 收敛、认证、退出码与隐私 |
| `eval/autotutor_production_attestation_smoke.py` | final 与 v1.50 entry 推导 |
| `eval/run_core_evals.py` | 注册新增 suite |
| `scripts/release_gate.py` | 加入 deterministic gate |
| `README.md` | bootstrap 与四阶段操作顺序 |

如实现中不需要修改某个文件，应保持最小 diff，不为满足表格而机械改动。

## 17. 测试计划

### 17.1 CI provenance

- 40 位 SHA + 最新 push CI success：通过；
- 无 run：阻断；
- queued/in_progress：NOT_READY；
- failure/cancelled/skipped：阻断；
- 只有 PR run：阻断；
- 其他 commit success：阻断；
- GitHub API timeout：UNKNOWN，fail-closed。

### 17.2 Bootstrap 与认证

- token 为空时 curl 不得执行；
- 401/403 使用稳定 blocker；
- log、summary、artifact 不含 token；
- workflow environment 名称固定；
- permissions 只包含 `contents: read` 和 `actions: read`。

### 17.3 部署收敛

- 冷启动后恢复；
- commit 从旧值收敛到目标值；
- 超时仍为旧 commit；
- 连续响应 commit 抖动；
- config/environment 不匹配；
- 5xx、timeout 与非法 JSON。

测试使用本地 fake transport，不依赖真实 Render。

### 17.4 Receipt

- success/failure 均生成 receipt；
- canonical hash 稳定；
- 任意字段 tamper 可检测；
- candidate/final hash 正确传递；
- forbidden key 嵌套时拒绝；
- artifact retention contract 为 90 天或更长。

### 17.5 回归

以下现有能力必须全部通过：

- observation provider single acquisition；
- Graph/Legacy full outcome parity；
- active routing 与 trusted cohort；
- admission cache/revocation；
- recovery 与 sticky executor；
- CAS/idempotency/transaction rollback；
- writer failure fail-closed；
- candidate/final evidence tamper；
- zero-traffic rollback rejection；
- frontend lint/unit/build；
- fast release gate。

## 18. 实施顺序

1. 定义 CI receipt、workflow receipt 和稳定错误码；
2. 实现 CI provenance gate 与 workflow 最小权限；
3. 实现 token 缺失 guard 和部署收敛等待；
4. 增加 receipt canonical hash、privacy scan 和 artifact；
5. 增加 verification/AgentOps 的 v1.50 entry projection；
6. 完成 deterministic tests 与 release gate；
7. 更新 README/runbook；
8. 提交、CI、部署；
9. 人工配置 GitHub Environment 和 Environment secret；
10. 按四阶段执行真实生产验证；
11. 最终复核并输出 v1.50 `GO | NO_GO`。

代码开发与生产操作必须分开提交证据。完成第 8 步不等于 Production Verified。

## 19. 验收标准

### 19.1 Development Complete

- Python compile 通过；
- v1.49.6 targeted suites 全部通过；
- fast release gate 全部通过；
- frontend lint/unit/build 通过；
- workflow YAML 与最小权限合同通过；
- CI/deployment/receipt negative cases 通过；
- privacy recursive scan 通过；
- `git diff --check` 通过；
- 默认 `legacy + BPS 0` 未改变；
- 没有新增生产写权限。

### 19.2 Deployment Ready

- clean commit 已 push；
- 目标 commit 的 `EduAgent CI` success；
- Render 部署完整 commit 与目标一致；
- migration 016 ready；
- AutoTutor observation writer healthy；
- workflow 使用目标 commit 中的脚本；
- `production-verification` Environment 已人工创建并受保护；
- Environment secret 已配置；
- preflight 经 reviewer 审批后执行。

### 19.3 Production Verified

- preflight receipt pass；
- exact control snapshot：Legacy ≥100、Graph =0；
- 1% Canary 有明确人工批准；
- exact Canary snapshot：committed Graph ≥100；
- comparator/safety/latency/provenance 全部达标；
- restart/writer-failure/kill-switch rehearsal pass；
- schema v4 candidate 已持久化并重新加载；
- 生产已恢复 `legacy + BPS 0`；
- exact rollback snapshot：新 Legacy ≥20、Graph assigned/selected =0；
- rollback rehearsal pass；
- schema v4 final GO 已持久化并重新加载；
- final/candidate/snapshot/receipt hash 全部一致；
- 所有 artifact PII-free；
- `v150_entry_ready=true` 且 blockers 为空。

## 20. 回滚与中止策略

### 20.1 在 Canary 前失败

- 保持 `legacy + BPS 0`；
- 修复 Environment、token、CI 或部署 blocker；
- 不生成 candidate；
- 重新运行 preflight/control，不复用不完整 snapshot。

### 20.2 Canary 中失败

人工立即：

1. 设置 Graph kill switch，或恢复 `EXECUTOR_MODE=legacy`；
2. 设置 `BPS=0`；
3. 不重放已提交 transition；
4. 开启新的 exact rollback window；
5. 调查 mismatch/fallback/writer/latency；
6. 不生成 final GO。

### 20.3 Candidate 后失败

- candidate 保留为不可变审计记录；
- final 不得生成；
- 修复后必须重新完成必要阶段；
- cohort fingerprint 变化时旧 candidate 失效，不能与新 rollback snapshot 拼接。

## 21. 风险与缓解

| 风险 | 缓解 |
|---|---|
| Environment 不存在时被自动创建且无审批 | 首次运行前人工 bootstrap，并形成 attestation |
| Secret 放在 repo scope 扩大暴露范围 | 使用 Environment-level secret |
| 部署成功但 CI 未通过 | CI provenance gate 先于远程验证 |
| CI 成功但 Render 尚未收敛 | 有界等待 + 连续一致确认 |
| 全局 readiness blocker 误阻断 AutoTutor | 使用 scoped verification，同时保留全局状态告警 |
| workflow receipt 被当作 final evidence | 合同明确 receipt 只做运行审计 |
| artifact 泄露学生或 token | recursive privacy scan，违规时不上传 |
| 人工演练自报失真 | Environment reviewer attestation + commit/config/window 绑定 |
| 零流量伪造 rollback | Legacy ≥20 且 Graph assigned/selected =0 |
| v1.50 被提前开发 | `v150_entry_ready` 只由 final GO 推导 |

## 22. v1.50 进入门槛

只有本 Spec 的 **Production Verified** 全部完成，才允许创建：

```text
EduAgent AutoTutor Single Executor Consolidation v1.50 Spec
```

届时 v1.50 才允许讨论：

- Graph 是否成为新会话默认 executor；
- comparator 从 100% 在线双算降为分阶段采样；
- Legacy 只保留 emergency fallback 还是进入删除计划；
- 旧 Legacy/Graph session 的恢复策略；
- telemetry schema 收敛；
- 更高流量阶段；
- 双执行 CPU/latency 成本优化。

即使 `v150_entry_ready=true`，v1.50 第一阶段仍必须保留即时回退 Legacy 的能力，
不得在同一个变更中同时“设 Graph 为默认、关闭 comparator、删除 Legacy”。

## 23. 最终验收问题

评审必须能用仓库设置、GitHub run、生产 API、fixed-window snapshot 和 immutable evidence
对以下问题全部回答“是”：

1. 目标 commit 是否有成功的 push CI，而不只是本地测试？
2. 生产部署 commit/config 是否与目标完全一致？
3. `production-verification` 是否真实存在并配置 reviewer 与分支限制？
4. API token 是否只存在于受保护 Environment 且没有进入日志/artifact？
5. workflow 是否只有 `contents: read` 与 `actions: read` GitHub 权限？
6. workflow 是否完全没有 Render 写权限？
7. 冷启动和部署收敛是否有界，持续失败是否 fail-closed？
8. control、Canary、rollback 是否全部使用服务端 exact-window aggregate？
9. 1% Canary 是否经过人工审批且从未超过 100 BPS？
10. committed Graph 是否至少 100 且 comparator/safety/latency 全部通过？
11. candidate 是否不能冒充 final GO？
12. rollback 是否有至少 20 条新 Legacy 流量而不是零流量？
13. rollback window 中 Graph assigned/selected 是否均为 0？
14. final 是否绑定 candidate 与 rollback snapshot hash？
15. final 是否持久化后重新 GET 并验证？
16. receipt、snapshot、evidence 和日志是否全部 PII-free？
17. 生产最终是否恢复 `legacy + BPS 0`？
18. `v150_entry_ready` 是否只由 schema v4 final GO 推导？

任一答案为“否”，v1.49.6 只能标记 Development Complete 或 Deployment Ready，不能标记
Production Verified，也不得创建 v1.50 Spec。
