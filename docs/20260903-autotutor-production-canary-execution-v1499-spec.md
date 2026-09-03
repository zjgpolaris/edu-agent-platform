# EduAgent AutoTutor Production Canary Execution & Live Evidence v1.49.9 Spec

**状态：** Implemented · Production execution pending
**日期：** 2026-09-03
**代码基线：** `main@a4c5faa`
**前置版本：** v1.49.8 AutoTutor Verification Attestation Binding
**后续候选：** v1.50 AutoTutor Single Executor Consolidation（仅在本 Spec 的 final evidence 为 GO 后允许立项）

## 0. 文档目的与证据边界

本 Spec 基于当前仓库实际代码、配置、测试和证据文件生成，不把既有规划文档中的目标视为已经实现。

当前已经具备：

- AutoTutor Legacy 与 LangGraph Active 两种 transition executor；
- 基于 verified cohort、稳定 bucket、BPS、admission 和 kill switch 的 fail-closed 路由；
- observation bundle、Graph/Legacy comparator、提交前 fallback 和领域事务边界；
- 生产 verification API、GitHub Environment workflow、candidate/final evidence 和 rollback verification；
- schema revision 016、observation writer health、部署 commit/config provenance；
- restart、writer failure、kill switch 和 rollback 的 evidence contract；
- 离线 transition parity、并发、幂等、恢复、安全和发布门禁评测。

当前尚未证明：

1. 当前 HEAD 的 clean active evidence；
2. 当前版本真实 LLM 调用质量；
3. 当前版本浏览器 E2E 全量通过；
4. 生产 control transition 不少于 100；
5. 生产 committed Graph transition 不少于 100；
6. schema v4 candidate evidence 为 `CANDIDATE_GO`；
7. BPS 恢复 0 后不少于 20 条 Legacy rollback control；
8. schema v4 final evidence 为 `GO`；
9. v1.50 entry decision 为 `GO`。

现存 `eval/reports/autotutor_active_latest.*` 绑定旧提交且带 dirty 标记，决策为
`NO_GO`。它只能作为历史开发证据，不能作为本次生产放量依据。

本 Spec 中所有“通过”“完成”和“GO”都必须由当前 immutable commit 的机器可验证证据支持。
受控验证流量只能证明工程正确性和发布安全性，不能被描述为真实学生学习效果或自然生产流量。

## 1. 迭代决定

v1.49.9 不新增教育业务功能，不改变教学状态机语义，也不删除 Legacy executor。
本迭代只完成一件事：

> 将 AutoTutor LangGraph Active 从“代码和离线合同已经完成、生产仍为 Legacy/BPS 0”推进到
> “当前提交通过真实模型与浏览器验证，完成受控 1% 生产 Canary、故障演练、精确窗口快照、
> BPS 0 回滚和 final GO evidence”的可审计闭环。

由于生产门禁要求至少 100 条 committed Graph transition，而最大生产放量为 100 BPS（1%），
完全依赖自然流量预计需要约 10,000 条 eligible transition。当前项目不能假设短期存在该流量，
因此本迭代允许新增一个最小权限、可追溯、显式标记的受控验证流量工具。

不得通过降低生产最小样本、临时提高 BPS、生产强制 Graph、伪造 observation 或把离线数据写入
生产 evidence 的方式完成门禁。

## 2. 成功目标

### 2.1 P0 目标

1. 为当前 immutable commit 生成 clean、可复现的 active transition evidence；
2. 真实 LLM profile 至少观察到一次模型调用，并保留 provider/model/dataset provenance；
3. 现有 13 条 Playwright E2E 在 CI 环境真实执行并全部通过；
4. 实现受控 Canary traffic runner，且只能由受保护的 production-verification 环境运行；
5. 收集不少于 100 条相同 commit/config/cohort fingerprint 的 production Legacy control；
6. 经人工审批将生产配置切换为 `active_canary + 100 BPS`；
7. 收集不少于 100 条 committed Graph transition，覆盖全部要求的 transition kind；
8. comparator、fallback、权限、重复副作用和延迟指标满足现有生产门禁；
9. 完成 restart、observation writer failure、kill switch 三项生产演练；
10. 生成并持久化 schema v4 `CANDIDATE_GO` evidence；
11. 人工恢复 `legacy + BPS 0`，在精确回滚窗口收集不少于 20 条 Legacy control；
12. 生成、持久化并重新读取校验 schema v4 final `GO` evidence；
13. 生产最终保持 `legacy + BPS 0`，v1.50 entry decision 变为 `GO`。

### 2.2 P1 目标

- verification traffic 与自然用户流量在数据层可区分；
- AgentOps 展示当前 phase、样本进度、受控流量数量和 evidence SHA；
- 所有自动化输出不包含账号、密码、token、bucket salt、学生输入或原始模型回答；
- 失败时生成稳定 blocker code，并保留可复查 receipt；
- 形成一条可重复执行但不能绕过人工审批的 release runbook。

## 3. 非目标

本迭代明确不做：

- 删除 Legacy executor、Legacy transition wrapper 或 comparator；
- 将生产 BPS 提升到 100 以上；
- 将 Graph 作为生产默认 executor；
- 使用 `internal_force_graph` 绕过生产 admission；
- 修改 mastery、weakpoint、教学计划、内容门禁、题目选择或退出票语义；
- 新增开放式 Agent 规划、多 Agent、Agent-as-tool 或动态 fan-out；
- 把 verification traffic 计入学生活跃、学习效果、留存或业务转化；
- 自动创建或自动提升真实学生账号为 verified cohort；
- 自动修改 Render 环境变量或持有 Render 写权限；
- 把 GitHub、Render、学生账号或 LLM 密钥写入命令参数、日志、artifact 或数据库；
- 为了通过门禁降低 100 Graph / 100 control / 20 rollback control 的生产阈值；
- 启动 v1.50 Single Executor Consolidation。

## 4. 用户与操作角色

### 4.1 发布操作员

作为发布操作员，我需要在每个阶段看到精确的 commit、config、window、样本数、blocker 和下一动作，
避免把旧 evidence、错误部署或未完成回滚误判为 GO。

### 4.2 审批人

作为 production-verification Environment 审批人，我需要确认放量、演练和回滚动作来自已通过 CI 的
immutable commit，并且 workflow 没有云平台写权限。

### 4.3 项目维护者

作为项目维护者，我需要通过受控流量获得足够的 transition 样本，但不能泄露密钥、污染业务指标、
绕过 verified cohort 或扩大生产流量。

### 4.4 学生

作为学生，我不应感知 verification 元数据，也不应看到 executor、bucket、comparator、trace、
admission reason 或内部 evidence 信息。Canary 失败时必须在提交前回退 Legacy，不重复写学习副作用。

## 5. 总体流程

```text
冻结 immutable commit
  -> CI / release gate / browser E2E / real-LLM evidence
  -> clean active transition evidence
  -> production preflight
  -> exact Legacy control window（>=100）
  -> 人工审批 active_canary + 100 BPS
  -> exact Canary window
       -> 受控 verified traffic
       -> committed Graph >=100
       -> comparator/fallback/latency/safety gate
       -> restart/writer-failure/kill-switch drills
  -> schema v4 candidate CANDIDATE_GO
  -> 人工恢复 legacy + BPS 0
  -> exact rollback window（Legacy >=20, Graph assigned/selected=0）
  -> schema v4 final GO
  -> GET 回读并校验 evidence SHA
  -> v1.50 entry GO
```

任何阶段失败时，默认动作都是停止新验证流量并保持或恢复 `legacy + BPS 0`。

## 6. 版本与证据冻结

### 6.1 Immutable revision

本轮所有证据必须绑定同一个完整 40 位 Git SHA：

- GitHub CI `head_sha`；
- Render deployed commit；
- AutoTutor executor config version；
- active evidence；
- real-LLM report；
- production snapshots；
- candidate/final evidence；
- workflow receipt。

若实现代码产生新提交，所有之前基于旧 SHA 的 release evidence 自动失效，必须重新开始 preflight。

### 6.2 Clean active evidence

必须从 clean workspace 运行 active evidence builder，至少证明：

- full trajectory parity：108/108；
- exact parity rate：1.0；
- Legacy wrapper tripwire：passed；
- executor external calls：0；
- executor side effects：0；
- duplicate effect count：0；
- dirty：false；
- evidence commit 等于 immutable revision；
- decision：GO。

生成后的 JSON 与 Markdown 必须进入 CI artifact；是否提交到仓库由现有 evidence policy 决定，
不能通过手工编辑报告消除 dirty blocker。

## 7. 真实 LLM 验证合同

### 7.1 运行要求

使用现有 `Agent Evidence Profiles` workflow 的 `real_llm` profile：

- `BAILIAN_API_KEY` 只存在于受保护 secret；
- `EDU_AGENT_REAL_LLM=1`；
- `--require-real-llm`；
- `--require-clean-revision`；
- 报告中的 LLM observed calls 必须大于 0；
- model/provider/profile 和 dataset hash 必须存在；
- authentication、rate limit、timeout 和 empty response 必须分类记录；
- 原始学生输入和完整模型输出不得写入公开 artifact。

### 7.2 通过条件

- profile status 为 pass；
- blocking skipped suites 为 0；
- AutoTutor teaching、assessment、grounding 和 safety 相关 required suites 全部通过；
- 运行 commit 等于 immutable revision；
- 报告不是 `offline` 或 `LLM execution: not_observed`；
- 重跑产生的质量指标不低于当前 release gate 阈值。

真实 LLM 结果只能证明当前 provider/model/profile 的运行表现，不可推广为所有模型准确率。

## 8. 浏览器 E2E 合同

### 8.1 环境

CI 必须：

- 使用 Python 3.12；
- 安装项目 runtime/eval dependencies；
- 使用 Node 24；
- 执行 `npx playwright install --with-deps chromium`；
- 启动真实 FastAPI 和 Next.js 服务；
- 使用独立临时数据库；
- 开启 auth、Runtime V2 和 AutoTutor content gate；
- 禁用外部 LLM，仅验证确定性产品合同。

### 8.2 必须覆盖的产品行为

现有 13 条 E2E 必须全部执行，不允许只有 collection success：

- AutoTutor 答错、反思、重规划和退出票；
- session reload 恢复与重新演示；
- 内容不足安全阻断；
- 学生复习、错题、作业和智能练习；
- 随问多步计划；
- 同一 Runtime Run 内高风险确认；
- 学情薄弱点到随问的上下文交接；
- 教师作业和 evidence；
- Admin Eval/AgentOps 页面。

验收记录必须显示 `13 passed`；浏览器未安装、服务未启动或用例未运行均为 infrastructure failure，
不能记为业务通过。

## 9. 受控 Canary Traffic Runner

### 9.1 新增入口

新增：

```text
scripts/run_autotutor_canary_verification_traffic.py
```

建议 CLI：

```text
--api-base HTTPS_URL
--expected-commit FULL_SHA
--expected-config-version VERSION
--phase control|canary|rollback
--target-transitions N
--maximum-sessions N
--timeout-seconds N
--receipt-output PATH
--dry-run
```

敏感信息只允许通过环境变量读取：

```text
AUTOTUTOR_VERIFICATION_STUDENT_CREDENTIALS_JSON
AUTOTUTOR_GRAPH_BUCKET_SALT
AUTOTUTOR_PRODUCTION_API_TOKEN
AUTOTUTOR_PRODUCTION_BOOTSTRAP_SHA256
```

不得把 credential、token 或 salt 放入 CLI 参数。

### 9.2 执行权限

Runner 必须同时满足：

1. 运行于 GitHub `production-verification` Environment；
2. 目标 API 使用 HTTPS；
3. preflight 返回 production 且 commit/config 完全匹配；
4. CI provenance 已 verified；
5. production verification machine credential 有效；
6. 账号在显式 allowlist 中；
7. 账号为 active + verified + student；
8. phase 与服务端当前 verification phase 一致；
9. canary phase 只允许 active BPS 为 1..100；
10. control/rollback phase 要求 executor mode 为 legacy 且 BPS 为 0。

任一条件不满足时不得发送学生 transition 请求。

### 9.3 Bucket 选择

Runner 可在受保护环境内使用与服务端一致的 SHA-256 sticky bucket 算法，从专用验证账号集合中选择
Graph bucket 账号，但必须满足：

- salt 不写日志、不写 receipt、不上传 artifact；
- 只输出 cohort fingerprint；
- 不输出账号 ID、用户名、密码或精确 bucket；
- 服务端 observation 的 executor assignment 才是最终权威；
- 没有可选 Graph 账号时 fail-closed 为 `verification_graph_subject_unavailable`；
- 不得调用生产 `internal_force_graph`。

同一 selected account 可以创建多个独立 AutoTutor session，但每条 transition 必须有唯一幂等键。

### 9.4 Transition 场景

Runner 必须使用固定、可审计且不会修改教学语义的场景集：

| 场景 | 必需 transition | 目的 |
|---|---|---|
| 正确路径 | start, lesson_answer, exit_ticket_answer | 基本完成路径 |
| 反思路径 | start, lesson_answer(wrong), lesson_answer(correct) | reflect/replan/reteach |
| 挣扎路径 | 连续错误后继续 | mark_struggling |
| 恢复路径 | start/answer 后 recovery_resume | session recovery |
| 内容阻断 | unsupported objective | fail-safe，不计 Graph committed 成功样本 |

用于累计 committed Graph 样本的 transition 必须来自现有公开 AutoTutor API 和真实业务事务。
不得直接插入 observation、session、learning event 或 evidence 表。

### 9.5 流量与成本保护

- 默认串行或最多并发 2；
- 全局 QPS 不超过 1；
- 每次运行设置最大 session、transition、wall time 和预估 LLM 成本；
- 达到目标样本立即停止；
- 连续 3 次 5xx、fallback rate 达 1%、comparator mismatch、unauthorized traffic、duplicate effect、
  observation write failure 或 kill switch 时立即停止；
- 收到 429 时指数退避，不绕过限流；
- workflow cancel 后不启动新 session；
- 所有会话结束后输出仅含聚合值的 receipt。

### 9.6 流量来源标记

新增 migration `017_autotutor_verification_traffic.py`，为 `agent_rollout_observations` 增加：

```text
traffic_source TEXT NOT NULL DEFAULT 'organic'
verification_run_id TEXT NULL
```

合同：

- `traffic_source` 只允许 `organic | release_verification`；
- `verification_run_id` 为不可逆随机 ID，不包含 GitHub run、账号或 secret；
- 普通请求永远写 `organic`；
- 只有通过 machine attestation 和专用账号双重验证的请求才能写 `release_verification`；
- production canary aggregate 同时报告 organic、release_verification 和 total；
- release gate 可使用 total 验证工程安全，但报告必须显式披露两类样本；
- 学习效果、活跃、留存和教师业务报表必须排除 `release_verification`；
- rollback 窗口同样保留来源分布；
- migration 必须支持 PostgreSQL/SQLite upgrade、downgrade 和 legacy row default。

客户端请求可使用：

```text
X-AutoTutor-Verification-Run: opaque-run-id
X-AutoTutor-Verification-Attestation: signed-token
```

服务端必须验证 header 与 actor、phase、commit、config 和过期时间绑定。无效 header 返回 403，
不得静默降级为受控验证流量；普通用户不发送这些 header。

## 10. 生产窗口与指标合同

### 10.1 Control window

放量前使用精确 UTC `[start, end)` 窗口收集：

- assigned control >= 100；
- assigned/selected/committed Graph = 0；
- environment = production；
- commit/config 固定；
- observation writer health = ok；
- control P95 可计算。

Control 未满足时状态保持 `control_collecting`，不得开启 Canary。

### 10.2 Canary window

人工将配置改为：

```text
EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE=active_canary
EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS=100
EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED=true
EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED=true
EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH=false
```

Canary 聚合通过条件：

- committed Graph >= 100；
- required transition kind coverage 完整；
- comparator exact match = 100%；
- fallback rate < 1%；
- unauthorized Graph traffic = 0；
- duplicate effect count = 0；
- duplicate transition observation count = 0；
- observation write failure = 0；
- observation/outcome schema 与当前合同匹配；
- transition/admission provenance 完整；
- active P95 <= control P95 * 1.20；
- active P95 - control P95 <= 50ms。

任一 hard blocker 出现时必须停止 runner，并人工恢复 Legacy/BPS 0。

### 10.3 Drill window

三项演练必须由 Environment-approved operator 执行并生成 attestation：

1. **restart：** Canary 中重启服务，已有 session 可恢复且无重复 effect；
2. **writer failure：** observation writer 故障时 admission/fallback fail-closed，不提交未经观察的 Graph effect；
3. **kill switch：** 开启后新 transition 全部选择 Legacy，关闭后不自动扩大 BPS。

attestation 只包含 pass/fail、commit、config、window 和 operator workflow metadata，不包含学生数据。

### 10.4 Rollback window

Candidate 持久化后必须人工恢复：

```text
EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE=legacy
EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS=0
```

使用新的精确 UTC 窗口收集：

- assigned control >= 20；
- assigned Graph = 0；
- selected Graph = 0；
- committed Graph = 0；
- commit/config/cohort fingerprint 与 candidate 一致；
- observation writer health = ok。

只有非空 rollback control 才能证明真实回滚；空窗口不能生成 final evidence。

## 11. Evidence 与 Receipt

### 11.1 Candidate

Candidate 必须为 schema v4，并包含：

- `evidence_stage=candidate`；
- `decision=CANDIDATE_GO`；
- full deployed commit；
- config version；
- exact canary window；
- cohort/runtime-state fingerprint；
- aggregate 与 traffic source distribution；
- snapshot SHA；
- restart/writer-failure/kill-switch 均为 pass；
- blockers 为空。

### 11.2 Final

Final 必须：

- 校验 candidate evidence SHA；
- 绑定 rollback exact snapshot；
- `mode=legacy` 且 `active_bps=0`；
- rollback Graph assigned/selected/committed 均为 0；
- rollback control >=20；
- drills.rollback=pass；
- `evidence_stage=final`；
- `decision=GO`；
- blockers 为空。

持久化后 workflow 必须重新 GET evidence，并逐项验证 stage、decision 和 SHA。只生成本地文件不算完成。

### 11.3 Runner receipt

Runner receipt 至少包含：

```json
{
  "schema_version": 1,
  "receipt_type": "autotutor_controlled_verification_traffic",
  "phase": "canary",
  "expected_commit": "40-char-sha",
  "config_version": "v1.49.9-production-canary",
  "verification_run_id_hash": "sha256:...",
  "window": {"start": "...", "end": "..."},
  "requested_transitions": 100,
  "completed_transitions": 100,
  "session_count": 34,
  "traffic_source": "release_verification",
  "result": "pass",
  "blockers": [],
  "generated_at": "..."
}
```

receipt 不得包含 actor ID、用户名、密码、JWT、salt、原始请求、原始回答、题目答案或 trace 内容。

## 12. API 与 UI 变化

### 12.1 API

现有学生公开响应不新增 executor/debug 字段。

Admin verification/snapshot API 增加以下聚合字段：

```json
{
  "traffic_sources": {
    "organic": {"control": 0, "graph": 0},
    "release_verification": {"control": 100, "graph": 100},
    "total": {"control": 100, "graph": 100}
  }
}
```

只有 require_admin + machine verification credential 可以读取该字段。不得返回逐账号记录。

### 12.2 AgentOps

高级诊断区展示：

- current phase/status/decision；
- expected/deployed commit；
- config version；
- control/Graph/rollback 样本进度；
- organic 与 release verification 的聚合分布；
- candidate/final evidence stage 与 SHA 前 12 位；
- blocker 与 next action；
- v1.50 entry decision。

学生和教师界面不展示任何上述信息。

## 13. 安全与隐私要求

1. Verification student credentials 只存在于 GitHub Environment secret；
2. 专用账号不得拥有 teacher/admin 权限；
3. Machine token 不能登录学生端，student token 不能读取 admin verification API；
4. Verification attestation 必须绑定 actor、run、phase、commit、config、expiry 和 nonce；
5. attestation TTL 不超过 15 分钟，nonce 只能使用一次；
6. 所有 verification 写操作进入 audit log；
7. 不记录 Prompt、完整回答、密码、JWT 或 bucket salt；
8. 对公开 artifact 的错误信息执行安全截断；
9. GitHub workflow 只保留 `contents: read`、`actions: read` 和 Environment 审批；
10. workflow 不获取 Render 写权限，mode/BPS 仍由人工修改；
11. production endpoint 不接受 localhost、HTTP 或非 allowlisted host；
12. verification traffic 必须受成本、QPS、wall-time 和最大 session 限制；
13. 任意疑似真实账号出现在 credential allowlist 时立即 NO_GO；
14. controlled traffic 的存在必须在最终 evidence 和项目说明中明确披露。

## 14. 故障与恢复

| 故障 | 系统行为 | Blocker/结果 |
|---|---|---|
| CI 非 success | 不 checkout、不请求生产 | `ci_run_not_successful` |
| commit 未收敛 | 有界等待，超时停止 | `deployment_not_converged` |
| config 漂移 | 不发送 transition | `config_version_mismatch` |
| credential 缺失 | workflow fail-closed | `verification_credentials_missing` |
| 无 Graph bucket 账号 | 不提高 BPS、不强制 Graph | `verification_graph_subject_unavailable` |
| observation writer unhealthy | admission denied，停止流量 | `observation_write_unhealthy` |
| comparator mismatch | 提交前 fallback，停止 Canary | `comparator_not_exact` |
| fallback >=1% | 停止 Canary，恢复 Legacy | `fallback_rate_above_one_percent` |
| unauthorized Graph | 立即停止并安全调查 | `unauthorized_graph_traffic` |
| duplicate effect/observation | 立即停止，不生成 candidate | 对应 duplicate blocker |
| active latency regression | 停止 Canary | `active_latency_regression` |
| API 429 | 退避，预算内重试 | 非 blocker，超预算失败 |
| API 5xx 连续三次 | 停止 runner | `verification_api_unstable` |
| workflow 被取消 | 不启动新 session | receipt=`cancelled` |
| candidate 已持久化但回滚不足 | 保持 Legacy/BPS 0，继续收集 | `rollback_collecting` |
| rollback 窗口出现 Graph | 不生成 final | `rollback_graph_traffic_detected` |
| evidence GET SHA 不一致 | 发布失败 | `evidence_sha_mismatch` |

## 15. 实施文件范围

预计修改或新增：

```text
scripts/run_autotutor_canary_verification_traffic.py
scripts/build_autotutor_canary_evidence.py
scripts/verify_autotutor_canary_deployment.py
.github/workflows/autotutor-production-verification.yml
backend/alembic/versions/017_autotutor_verification_traffic.py
backend/db/schema.py
backend/agents/autotutor_execution.py
backend/agent_runtime/rollout_observations.py
backend/agent_runtime/autotutor_canary_verification.py
backend/security/autotutor_verification_auth.py
backend/api/routers/learning.py
backend/api/routers/agent_runtime.py
frontend/app/eval/page.tsx
eval/autotutor_verification_traffic_smoke.py
eval/autotutor_verification_traffic_security_smoke.py
eval/autotutor_canary_source_aggregation_smoke.py
eval/autotutor_production_workflow_contract_smoke.py
eval/postgres_schema_smoke.py
eval/run_core_evals.py
```

若实现不需要某个文件，不应为了匹配清单制造无意义改动。若需要扩大权限或新增生产写 API，必须先修订
本 Spec，不得在实现中隐式扩展范围。

## 16. 测试计划

### 16.1 单元与合同测试

- attestation 签名、TTL、nonce replay、actor/phase/commit/config binding；
- credential allowlist 和角色限制；
- bucket 计算与服务端一致；
- dry-run 不发送请求；
- max sessions/transitions/wall-time/cost 生效；
- 429 退避与连续 5xx 停止；
- receipt 不含敏感字段；
- ordinary request 只能标记 organic；
- forged verification header 返回 403；
- source aggregation total 等于各来源之和；
- student/teacher metrics 排除 release_verification；
- candidate/final evidence 绑定 source distribution。

### 16.2 Migration

- SQLite 016 -> 017 upgrade；
- PostgreSQL 016 -> 017 upgrade；
- legacy rows default 为 organic；
- downgrade 后恢复 016 schema；
- 并发启动 migration lock；
- schema readiness required revision 更新为 017；
- migration 失败时 API 拒绝启动。

### 16.3 Runtime 回归

- 108/108 full outcome parity；
- start/answer/exit/recovery 路由；
- transaction fault injection；
- transition idempotency；
- side-effect exactly-once；
- admission fail-closed；
- fallback 和 comparator；
- production internal force forbidden；
- existing session downgrade；
- public response contract 不变。

### 16.4 全量门禁

```bash
npm run lint --prefix frontend
npm run test:unit --prefix frontend
npm run build --prefix frontend
PYTHONPATH=backend python3 eval/run_core_evals.py --smoke
npm run test:e2e --prefix frontend
npm run release:gate
```

生产证据另外要求：

```text
real_llm profile PASS
clean active evidence GO
production preflight GO
control snapshot GO
canary candidate CANDIDATE_GO
rollback final GO
persisted evidence GET verification PASS
```

## 17. 分阶段交付

### Phase A：本地实现与安全合同

- 实现 traffic source migration；
- 实现 verification attestation；
- 实现 runner dry-run、预算、receipt 和安全停止；
- 完成专项 deterministic tests。

退出条件：专项测试、migration 和 security tests 全绿。

### Phase B：CI 与证据刷新

- 将 runner 接入 production-verification workflow；
- 当前 commit 的 lint/unit/build/smoke/E2E/release gate 全绿；
- real-LLM profile PASS；
- clean active evidence GO。

退出条件：形成 immutable candidate commit，后续不再改代码。

### Phase C：Control

- 部署 candidate commit；
- 验证 schema 017、commit/config、writer health；
- 保持 Legacy/BPS 0；
- 收集 exact control >=100。

退出条件：`ready_for_manual_one_percent`。

### Phase D：1% Canary

- Environment 人工审批；
- 人工设置 active_canary + 100 BPS；
- 运行受控流量；
- 达到 committed Graph >=100；
- 三项 drill 通过；
- 生成并持久化 candidate evidence。

退出条件：`candidate_persisted` 且 decision 为 GO。

### Phase E：Rollback 与 Final

- 人工恢复 Legacy/BPS 0；
- 开启新的 exact rollback window；
- 收集 control >=20 且 Graph=0；
- 生成 final evidence；
- 持久化并 GET 校验 SHA；
- 确认生产仍为 Legacy/BPS 0。

退出条件：`rollback_verified`、final `GO`、v1.50 entry `GO`。

## 18. Definition of Done

只有以下全部满足，本迭代才可标记完成：

- [ ] 当前 immutable commit 的 CI push run 为 success；
- [ ] workspace clean，active evidence decision 为 GO；
- [ ] active full trajectory parity 为 108/108；
- [ ] real-LLM profile PASS 且 observed calls > 0；
- [ ] Playwright 13/13 passed；
- [ ] migration 017 在 SQLite/PostgreSQL upgrade/downgrade 通过；
- [ ] verification runner 通过安全、预算、receipt 和故障测试；
- [ ] verification traffic 不进入业务学习指标；
- [ ] control transition >=100；
- [ ] 人工审批记录存在；
- [ ] 生产 Canary 不超过 100 BPS；
- [ ] committed Graph transition >=100；
- [ ] required transition kinds 覆盖完整；
- [ ] comparator exact match=100%；
- [ ] fallback rate <1%；
- [ ] unauthorized Graph=0；
- [ ] duplicate effect=0；
- [ ] duplicate observation=0；
- [ ] observation write failure=0；
- [ ] active P95 满足相对和绝对阈值；
- [ ] restart/writer-failure/kill-switch drills 全部 pass；
- [ ] schema v4 candidate 为 CANDIDATE_GO；
- [ ] 生产恢复 Legacy/BPS 0；
- [ ] rollback control >=20 且 Graph assigned/selected/committed=0；
- [ ] schema v4 final evidence 为 GO；
- [ ] 持久化 evidence 回读 SHA 一致；
- [ ] 最终 production verification phase 为 rollback_verified；
- [ ] `v150_entry_decision=GO`；
- [ ] 文档明确披露受控流量比例，不声称为自然用户效果。

任何一项缺失时，状态只能是 `Development Complete`、`NOT_READY` 或 `NO_GO`，不得标记
`Production Verified`。

## 19. 发布后决策

本 Spec 完成后，生产仍保持 Legacy/BPS 0。final GO 只证明 Graph Active 已完成一次受控生产放量和
可验证回滚，不自动授权长期放量。

满足以下条件后，才允许单独评审 v1.50 Single Executor Consolidation：

1. final evidence 为 schema v4 GO；
2. evidence SHA 可从生产重新读取验证；
3. rollback_verified；
4. v150_entry_decision=GO；
5. 没有未关闭的安全、重复副作用或数据污染 blocker；
6. 团队明确决定是继续小比例长期 Canary，还是开始单执行器收敛。

v1.50 必须另立 Spec，不得把本轮受控验证自动解释为删除 Legacy 的授权。
