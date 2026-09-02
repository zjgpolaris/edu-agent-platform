# EduAgent AutoTutor Production Attestation & Rollback Closure v1.49.5 Spec

**状态：** Approved for implementation
**日期：** 2026-09-02
**前置版本：** v1.49.4 AutoTutor Canary Production Verification
**后续候选：** v1.50 AutoTutor Single Executor Consolidation

## 1. 背景与实际状态

`d011527` 已通过 CI 并部署到 Render，生产数据库与 migration 016 ready，AutoTutor
Production Verification workflow 已注册。v1.49.4 已完成开发与部署基线，但尚无人工 workflow
运行、Canary exact snapshot、持久化 GO evidence 或真实 rollback observation。

现有实现仍有三个完整性缺口：

1. 已有 GO evidence 且配置恢复 BPS 0 时即可显示 `rollback_verified`，可能出现零流量假证明；
2. 一个 fingerprint 同时绑定 cohort salt 与可变的 mode/BPS，无法正确表达 Canary 到 rollback 的状态变化；
3. Canary evidence 与 rollback proof 没有明确的 candidate/final 两阶段关系。

因此 v1.50 仍被阻止。本迭代只完善生产证据与回滚证明，不扩大流量、不删除 Legacy，
也不改变 AutoTutor 教学、事务或 effect idempotency 逻辑。

## 2. 目标

- 将稳定 cohort 身份与可变 runtime state 拆成两个脱敏 fingerprint；
- Canary 阶段只允许生成 `candidate` evidence；
- BPS 0 后必须在 fixed UTC window 内观察到新的 Legacy 流量和零 Graph assignment；
- 只有 candidate、rollback snapshot 与全部 rehearsal 同时有效，才生成 `final GO` evidence；
- workflow 串行执行，不能并发验证同一生产环境；
- API、CLI、artifact 使用 PII-free projection，并拒绝 trace/session/effect/raw content 字段；
- 兼容读取 schema v3，但 schema v3 不再单独证明 rollback complete。

## 3. 非目标

- 自动修改 Render mode/BPS/kill switch；
- 自动创建 verified cohort 或生成生产学生流量；
- 提升到 1% 以上；
- 删除 Legacy、降低 comparator 覆盖或实施 v1.50；
- 新增 migration 017。evidence 继续使用 JSON payload 存入现有表。

## 4. 指纹合同

### 4.1 Cohort fingerprint

绑定稳定分桶身份：

```text
config_version
bucket_salt
bucket_algorithm_version
```

只输出 SHA256，不输出 salt。Canary candidate 与 rollback snapshot 必须完全一致。

### 4.2 Runtime state fingerprint

绑定当前执行状态：

```text
mode
active_bps
kill_switch
comparator_enabled
fallback_enabled
config_version
```

Canary 与 rollback 的 runtime state fingerprint 应不同；rollback 必须为 legacy/BPS 0/kill off。
保留旧 `config_fingerprint` 作为 runtime state fingerprint 的兼容别名。

## 5. Phase 状态机

```text
control_collecting
ready_for_manual_one_percent
canary_collecting
canary_ready_for_snapshot
candidate_persisted
legacy_evidence_requires_upgrade
rollback_pending
rollback_collecting
rollback_blocked
rollback_ready_for_finalize
rollback_verified
```

- schema v3 GO evidence 只能进入 `rollback_pending`，不得直接 VERIFIED；
- candidate evidence + BPS 0 + 非 exact window：`rollback_pending`；
- post-rollback Graph assigned/selected 非零：`rollback_blocked`；
- Graph 为零但新 Legacy transitions 少于生产下限 20：`rollback_collecting`；
- exact rollback snapshot 通过：`rollback_ready_for_finalize`；
- 持久化并重新加载 schema v4 final GO：`rollback_verified`。

高优先级部署、安全、写入健康 blocker 继续优先于上述阶段。

## 6. Exact rollback snapshot

Rollback snapshot 必须由服务端数据库 fixed window 聚合产生，包含：

- commit/config/environment/cohort fingerprint；
- window start/end；
- assigned control count；
- assigned Graph count；
- selected Graph count；
- minimum rollback control；
- observation write health；
- status/decision/blockers；
- snapshot SHA256。

生产通过条件：

```text
assigned_graph_count == 0
selected_graph_count == 0
assigned_control_count >= 20
observation_health == ok
mode == legacy
active_bps == 0
```

这避免“窗口内完全没有请求，因此 Graph 为零”的空证明。

## 7. Evidence schema v4

### 7.1 Candidate

Canary snapshot GO 后生成：

```json
{
  "schema_version": 4,
  "evidence_stage": "candidate",
  "decision": "CANDIDATE_GO",
  "canary_snapshot_sha256": "sha256:...",
  "cohort_fingerprint": "sha256:...",
  "runtime_state_fingerprint": "sha256:..."
}
```

Candidate 不是 Production Verified，只表示允许回滚和收集 post-window evidence。

### 7.2 Final

Final evidence 必须引用：

- candidate evidence SHA256；
- 原 Canary snapshot；
- exact rollback snapshot；
- restart/writer-failure/kill-switch/rollback 四项 rehearsal；
- 相同 commit/config/environment/cohort fingerprint；
- rollback runtime state 为 legacy/BPS 0。

只有 final evidence 可以使用 `decision=GO`。

## 8. Workflow

现有手工 workflow 增加：

- `concurrency.group=autotutor-production-verification`；
- `cancel-in-progress=false`；
- `canary_snapshot` 只生成并持久化 candidate；
- `rollback_verify` 获取已持久化 candidate，验证 exact rollback snapshot，生成并持久化 final；
- final 持久化后重新 GET evidence，校验 stage、decision 与 SHA；
- 所有失败仍上传 PII-free artifact；
- workflow 不持有 Render 写权限，不改变 BPS。

## 9. 隐私与安全

Artifact 投影禁止出现以下字段或其嵌套形式：

```text
token authorization password bucket_salt email
student_id actor_id account_id session_id trace_id effect_id transition_id
question answer raw_prompt raw_response content
```

聚合计数、哈希、枚举状态和延迟分位数允许输出。任何敏感字段命中均为 BLOCKED，
且 CLI 退出码非零。

## 10. API 与 CLI

- verification/snapshot API 增加 `minimum_rollback_control`，生产下限固定为 20；
- snapshot 响应增加 `snapshot_kind=canary|rollback`；
- evidence summary 增加 schema version、stage、candidate/final hash；
- evidence POST 拒绝当前部署 provenance 或 cohort fingerprint 不匹配；
- builder 支持 `--stage candidate|final`；
- final builder 必须读取 candidate evidence 与 rollback snapshot，不能接受客户端自报 aggregate。

## 11. 测试

新增或扩展 deterministic suites：

- fingerprint 稳定性、salt 脱敏与状态变化；
- rollback 无 exact window 不得 VERIFIED；
- 零流量不得验证通过；
- post-window Graph 流量必须 BLOCKED；
- 20 条 Legacy + 0 Graph 才能 ready；
- candidate 不能冒充 final GO；
- final evidence provenance、hash 和 snapshot tamper；
- schema v3 兼容读取但不得证明 rollback；
- workflow concurrency 与两阶段合同；
- session/trace/effect/raw content privacy negative cases；
- 原 AutoTutor transaction、admission、writer failure、parity suites 全部回归。

## 12. 验收标准

### Development Complete

- Python compile；
- v1.49.5 targeted suites；
- fast release gate；
- frontend lint/unit/build；
- workflow YAML contract；
- sensitive field scan；
- git diff check。

### Production Verified

- CI 与部署 commit 精确匹配；
- verified control ≥100；
- 人工 1% Canary；
- committed Graph ≥100 且全部安全/质量/延迟门槛通过；
- candidate evidence 已持久化；
- BPS 恢复 0；
- rollback fixed window 内 Legacy ≥20 且 Graph assigned/selected 均为 0；
- final schema v4 GO evidence 已持久化并重新加载；
- workflow 成功；
- 所有 artifact PII-free。

只有上述 Production Verified 全部完成，才能创建 v1.50 Spec。

## 13. 实施顺序

1. 拆分 fingerprint 并保持兼容；
2. 增加 rollback exact-window 状态机；
3. 实现 schema v4 candidate/final evidence validation；
4. 改造 builder 与 workflow 两阶段流程；
5. 收紧 API/CLI privacy projection；
6. 更新 AgentOps、README 与 release gate；
7. 完成全量验证，但不自动执行生产 Canary。
