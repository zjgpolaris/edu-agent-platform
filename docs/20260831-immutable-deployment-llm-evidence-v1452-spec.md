# EduAgent 不可变部署与 LLM 生产证据闭环 v1.45.2 Spec

> **状态：已归档，不执行。** 当前产品定位为单环境 Agent Demo，采用 `main` 推送后由 Render 自动构建部署；本文保留为生产化方案参考，不再对应启用中的 GitHub Actions 工作流。

**创建时间：** 2026-08-31

**状态：** Development Complete · P0 · External Rollout NOT_RUN

**目标版本：** v1.45.2

**前置版本：** `main@c709e25`

**适用范围：** Backend 镜像供应链、Render staging/production 部署、LLM Capability Manifest 持久化、Release Evidence Schema v2、Runtime rollout、真实 Provider/RAG 评测、secret 清理与回滚

**关联文档：**

- `docs/20260830-llm-provider-production-evidence-v145-spec.md`
- `docs/20260830-llm-provider-production-evidence-v145-implementation-report.md`
- `docs/20260830-llm-provider-operations-v144-runbook.md`
- `docs/202608292100-agent-runtime-rollout-operations-v142-spec.md`
- `docs/202608301844-production-auth-trusted-rollout-v143-spec.md`
- [Render Default Environment Variables](https://render.com/docs/environment-variables)
- [Render Deploy a Prebuilt Docker Image](https://render.com/docs/deploying-an-image)
- [Render Deploys and Rollbacks](https://render.com/docs/deploys)
- [LangChain Structured Output](https://docs.langchain.com/oss/python/langchain/structured-output)

**实施记录：** 代码、迁移、工作流与 deterministic 门禁已完成，详见 `docs/20260831-immutable-deployment-llm-evidence-v1452-implementation-report.md`。独立 staging、真实 Provider/RAG、生产样本、secret store 清理与回滚演练仍为 `NOT_RUN`，因此本 Spec 不标记 Complete。

---

## 0. 执行摘要

v1.45 已完成 LLM capability manifest、运行时能力门禁、Release Evidence Schema v2、管理员能力 API 与 deterministic release gate，但生产部署仍不能形成完整证据闭环。

2026-08-31 当前生产只读快照：

| 检查 | 当前状态 |
| --- | --- |
| deployed commit | `c709e25708c08e1e991ba5145b48fa926117a180` |
| service health | PASS |
| shallow readiness | PASS / degraded |
| PostgreSQL / Alembic | PASS / `012` |
| pgvector / history RAG | PASS / 2850 documents |
| LLM provider config | PASS，百炼凭证已配置 |
| image digest | `null` |
| capability manifest | `missing` |
| latest eval | `missing` |
| release evidence | disabled / missing |
| Runtime config | `v1.41-history-control` |
| staging | 未配置或当前执行环境不可访问 |

当前主要问题不再是 LLM SDK 适配，而是部署与证据分离：

1. Render 当前从 Git 仓库构建 Dockerfile，并在 `main` push 后自动部署；运行时只稳定暴露 commit，不公开文档化的镜像 digest；
2. Capability manifest 在 GitHub Runner 的临时目录生成，生产 Runtime 只会从本地文件读取，运行中的容器无法自动获得该 manifest；
3. 当前仅有 production 服务，没有受控 staging 拓扑；
4. real LLM、材料视觉、真实 stream、长结构化输出和 production RAG 尚未在同一不可变制品上形成证据；
5. staging/production 样本、canary、secret 清理和回滚仍未执行。

因此，本版本不增加 Native Structured Output、Tool Calling、Agent 或 LangGraph 能力。本轮唯一目标是让以下证据链真实运行：

```text
clean commit
  -> CI build linux/amd64 image once
  -> push immutable GHCR digest
  -> deploy exact digest to staging
  -> persist and resolve exact capability manifest
  -> real LLM + business + RAG evidence
  -> staging shadow >=100 terminal runs
  -> promote same digest to production
  -> production 1% >=100 terminal runs
  -> production 10% / 48h
  -> rollback drill and final evidence report
```

---

## 1. 决策

### 1.1 采用预构建不可变镜像

Backend 发布改为：

- GitHub Actions 构建 `linux/amd64` Backend 镜像；
- 推送至 GHCR；
- 以 OCI digest 作为唯一可晋级制品标识；
- staging 与 production 部署完全相同的 digest；
- production 关闭 Git push 自动部署；
- 部署动作必须显式选择 digest，并由环境审批保护。

目标镜像引用形式：

```text
ghcr.io/zjgpolaris/edu-agent-platform/backend@sha256:<64-hex>
```

禁止使用以下标识证明生产制品不可变：

- `latest`；
- branch 名；
- 可移动语义版本 tag；
- 仅 commit、无镜像 digest；
- Render 内部未公开且无法由流水线验证的 build ID。

### 1.2 Capability Manifest 改为数据库事实源

生产 Runtime 不再只依赖本地 manifest 文件。新增 append-only manifest store：

- GitHub evidence workflow 生成并验证完整脱敏 manifest；
- workflow 将 manifest 持久化到目标环境数据库；
- Runtime 按当前 commit/image/config/environment/provider 精确查询；
- 本地文件只作为离线测试和显式 break-glass 输入，不是生产默认事实源；
- manifest 缺失、过期、hash 错误或 provenance 不匹配时 optional capability fail-closed。

### 1.3 Staging 与 production 严格分离

至少建立：

| 环境 | 服务 | 数据库 | GitHub Environment | 作用 |
| --- | --- | --- | --- | --- |
| staging | `edu-agent-backend-staging` | 独立 PostgreSQL/pgvector | `staging` | 部署验证、真实 Provider/RAG、受控回放、Shadow |
| production | `edu-agent-backend` | 当前生产 PostgreSQL/pgvector | `production` | 真实 verified cohort canary |

禁止 staging 使用 production 数据库写路径。允许使用相同的脱敏历史知识库版本，但必须单独建索引并记录 corpus/index version。

### 1.4 不提前进入 v1.46

在本 Spec Complete 前：

- `EDU_AGENT_LLM_ENABLED_CAPABILITIES` 保持空；
- 不把 `native_structured_output` 接入业务；
- 不把 `tool_calling` 接入业务；
- 不扩展 Agent Runtime 或 LangGraph；
- 不接入 LangSmith 替换现有观测或 evidence。

---

## 2. 目标与非目标

### 2.1 目标

1. 生成可复现、可验证、不可变的 Backend OCI digest；
2. 让 staging 与 production 按同一 digest 晋级；
3. 关闭 production Git push 自动部署，改为门禁后显式晋级；
4. 新增 Capability Manifest 数据库存储与运行时解析；
5. 让 `/api/ready` 和管理员能力 API 返回同一部署 provenance；
6. 在 staging 完成全 profile required capability 与真实业务评测；
7. 在同一 commit/image/config 下生成 Release Evidence Schema v2；
8. 完成 staging Shadow、production 1% 与 10% 灰度；
9. 删除旧代理 secret，并验证代码和部署环境均不再读取；
10. 完成基于上一 digest 的生产回滚演练；
11. 输出包含实际 hash、样本与 canary 结果的最终实施报告。

### 2.2 非目标

- 不启用 Native Structured Output；
- 不启用模型 Tool Calling；
- 不全面迁移 LangChain/LangGraph/LangSmith；
- 不增加新的在线 LLM Provider；
- 不改变 RAG 检索算法、知识库内容或 embedding 模型；
- 不扩展到 `learning_assistant`、`autotutor`、`essay_grader` 或 `debate` active rollout；
- 不用 demo/eval 数据伪造 production terminal runs；
- 不提供绕过审批的一键生产发布；
- 不在 manifest/evidence 中存储学生正文、图片、prompt 或模型完整输出。

---

## 3. Definition of Ready

开始外部实施前必须确认：

1. GitHub Actions 可写 GHCR package；
2. 已创建 `staging` 和 `production` GitHub Environment；
3. 两个 Environment 分别配置所需 secrets；
4. 可创建或迁移 Render image-backed service；
5. production 自动部署可关闭；
6. staging 使用独立 PostgreSQL/pgvector；
7. staging 与 production 均可部署 exact image digest；
8. 有 Render API token 或等价受控部署入口；
9. 有 staging 管理员和业务 smoke 账号；
10. production 有经过批准的 verified cohort 测试账号；
11. 有权限读取并清理 Render/GitHub secret store；
12. 明确 canary owner、发布审批人、停止条件与回滚责任人。

建议的 GitHub Environment secrets：

```text
BAILIAN_API_KEY
DATABASE_URL
DIRECT_URL
API_BASE
RUNTIME_ADMIN_USERNAME
RUNTIME_ADMIN_PASSWORD
SMOKE_USERNAME
SMOKE_PASSWORD
RENDER_API_TOKEN
RENDER_SERVICE_ID
```

所有 secret 必须由环境隔离，不允许 staging job 读取 production secret。

如果以上条件未满足，状态为 `Blocked / Not Ready`，不得用 production 直接替代 staging。

---

## 4. 不可变镜像供应链

### 4.1 Build once

新增独立 workflow，例如：

```text
.github/workflows/backend-image-release.yml
```

触发条件：

- 手动 `workflow_dispatch`；
- 可选：main release tag；
- 不在普通 pull request 中推送镜像。

前置门禁：

1. checkout 指定 full commit；
2. worktree clean；
3. 完整 release gate PASS；
4. PostgreSQL migration rehearsal PASS；
5. Backend Docker build PASS；
6. 镜像以 `linux/amd64` 构建；
7. 推送 GHCR；
8. 捕获 registry 返回的真实 digest；
9. 生成非敏感 build provenance artifact。

Build provenance 至少包含：

```json
{
  "schema_version": 1,
  "source_commit": "<40-char-sha>",
  "image_repository": "ghcr.io/zjgpolaris/edu-agent-platform/backend",
  "image_digest": "sha256:<64-hex>",
  "platform": "linux/amd64",
  "dockerfile_sha256": "sha256:...",
  "runtime_requirements_sha256": "sha256:...",
  "built_at": "2026-08-31T00:00:00Z",
  "workflow_run_id": "..."
}
```

不得包含 GitHub token、registry credential、build args 中的 secret 或完整环境变量。

### 4.2 Digest verification

发布流水线必须同时验证：

- GHCR 返回的 digest；
- Render 部署请求使用的 digest；
- Render deploy API 返回的实际 image reference；
- Runtime `/api/ready` 返回的 `image_digest`；
- Release Evidence Schema v2 中的 `image_digest`。

以上五处必须完全相同。

`EDU_AGENT_IMAGE_DIGEST` 由受控部署 workflow 写入目标服务环境，并与同一次部署请求绑定。不得由人工复制后直接视为可信；workflow 必须通过 Render API 与 readiness 二次校验。

### 4.3 Tag 策略

允许同时发布便于查看的不可变辅助 tag：

```text
sha-c709e25708c0
v1.45.2-rc.<run-number>
```

部署与晋级仍必须使用 digest，不使用 tag。

### 4.4 Production auto-deploy

迁移成功后：

- production `autoDeploy=false`；
- staging 也优先使用显式 digest 部署；
- push main 只触发 CI，不直接替换生产容器；
- production deployment 必须引用已通过 staging 的 digest；
- 禁止 production 重新 build 同一 commit。

---

## 5. Capability Manifest Store

### 5.1 数据表

新增 Alembic migration：

```text
013_llm_capability_manifest_store.py
```

新增表：

```text
llm_capability_manifests
```

建议字段：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `manifest_id` | text | PK，服务端生成 |
| `schema_version` | integer | 非空，当前为 1 |
| `provider` | text | 非空 |
| `environment` | text | 非空，staging/production |
| `deployed_commit` | text | 非空，full SHA |
| `image_digest` | text | 非空，`sha256:<64-hex>` |
| `runtime_config_version` | text | 非空 |
| `endpoint_fingerprint` | text | 非空 |
| `manifest_sha256` | text | 非空、唯一 |
| `generated_at` | timestamp/text | 非空 |
| `expires_at` | timestamp/text | 非空 |
| `payload_json` | jsonb/text | 非空、完整脱敏 manifest |
| `created_at` | timestamp/text | 非空 |

索引：

```text
UNIQUE(manifest_sha256)
INDEX(environment, deployed_commit, image_digest, runtime_config_version, created_at DESC)
INDEX(expires_at)
```

表为 append-only。应用运行路径不得 update manifest 内容。重复 hash 写入必须幂等返回已有记录。

### 5.2 写入验证

`save_capability_manifest()` 必须验证：

- schema version；
- canonical hash；
- generated/expires 时间；
- full commit；
- image digest 格式；
- environment/config/provider/endpoint；
- Registry 中全部 8 个 profile；
- exact model/max tokens/fallback；
- required status；
- 数据最小化禁止项。

写入前任何一项失败时拒绝持久化，不允许保存为 PASS 后再依赖读取端修正。

### 5.3 Runtime 解析顺序

Production 默认顺序：

```text
current deployment provenance
  -> exact DB manifest lookup
  -> validate hash/freshness/profile configuration
  -> expose configured/validated/enabled views
```

允许的显式测试顺序：

```text
function argument
  -> EDU_AGENT_LLM_CAPABILITY_MANIFEST_PATH（仅 test/break-glass）
  -> exact DB manifest lookup
```

production 若配置本地 manifest 路径，readiness 必须显示 `manifest_source=file_override` 警告。

### 5.4 Cache 与失败语义

- DB manifest cache TTL：建议 60 秒；
- cache key 包含完整 provenance；
- commit/image/config/environment/model 变化立即产生新 key；
- DB 查询失败返回 `manifest_store_unavailable`；
- DB 查询失败不阻塞现有 control chat/json_prompt 路径；
- DB 查询失败立即关闭 optional capability；
- 不使用过期缓存延长 manifest 生命周期；
- 管理员 API 不返回 payload 中的 trace 原始内容，只返回允许字段。

### 5.5 Retention

- 至少保留最近 90 天 manifest；
- 当前和最近一个可回滚 digest 的 manifest 不得自动清理；
- 清理任务只删除已过期且不再被 release evidence 引用的记录；
- 首期可以只实现查询与手动清理，不增加自动删除风险。

---

## 6. API 与 Readiness 合同

### 6.1 `/api/ready`

Deployment check 至少返回：

```json
{
  "ok": true,
  "deployed_commit": "...",
  "image_digest": "sha256:...",
  "runtime_config_version": "v1.45.2-history-staging-shadow",
  "environment": "staging"
}
```

Capability summary 至少返回：

```json
{
  "status": "pass",
  "source": "database",
  "manifest_sha256": "sha256:...",
  "generated_at": "...",
  "expires_at": "...",
  "deployment_provenance_match": true,
  "reasons": []
}
```

当 `EDU_AGENT_REQUIRE_LLM_EVIDENCE_V2=true`：

- image digest 缺失必须使 strict Runtime readiness 失败；
- manifest missing/invalid/stale 必须使 rollout readiness 失败；
- control 产品路径可以继续服务；
- optional capability 保持关闭。

### 6.2 管理员 Capability API

`GET /api/admin/llm/capabilities` 新增：

- `manifest_source`；
- `manifest_store_status`；
- `queried_provenance`；
- `profile_coverage`；
- `required_profile_count` / `passed_profile_count`；
- `last_refresh_at`；
- 稳定 reason code。

禁止返回：

- prompt/output；
- API key/Authorization；
- 图片或 base64；
- 学生/教师身份；
- raw provider error body；
- 数据库 URL；
- Render deploy hook/token。

### 6.3 Deep health

继续保持 `fast_connectivity_only` 语义。Deep health 不读取或覆盖 all-profile manifest，也不能把一次 fast 调用解释为全能力通过。

---

## 7. Staging 部署与证据

### 7.1 Staging 初始配置

建议：

```text
EDU_AGENT_ENVIRONMENT=staging
EDU_AGENT_DEPLOYED_COMMIT=<full-sha>
EDU_AGENT_IMAGE_DIGEST=sha256:<digest>
EDU_AGENT_RUNTIME_V2_CONFIG_VERSION=v1.45.2-history-staging-shadow
EDU_AGENT_RUNTIME_V2_ENABLED=true
EDU_AGENT_RUNTIME_V2_SHADOW_MODE=true
EDU_AGENT_RUNTIME_V2_ACTIVE_ENABLED=false
EDU_AGENT_RUNTIME_V2_PERCENT_BPS=10000
EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS=10000
EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS=0
EDU_AGENT_RUNTIME_V2_AUTOTUTOR_BPS=0
EDU_AGENT_RUNTIME_V2_ESSAY_GRADER_BPS=0
EDU_AGENT_RUNTIME_V2_DEBATE_BPS=0
EDU_AGENT_RUNTIME_V2_PERSIST_EVENTS=true
EDU_AGENT_REQUIRE_LLM_EVIDENCE_V2=true
EDU_AGENT_LLM_ENABLED_CAPABILITIES=
```

Shadow 不生成第二份学生答案，不重复执行 LLM/RAG/副作用，只记录 Runtime 生命周期、事件与完成判定。

### 7.2 Real-provider profile

同一 clean commit/image/config 下必须运行：

1. `llm_provider_live_probe`：全部 8 个 profile；
2. `learning_assistant_semantic_router_eval`；
3. `history_character_eval`；
4. `history_character_smoke`；
5. 材料图片 base64 真实理解；
6. 真实 streaming 首 token、完成与中断合同；
7. material/card_pool 长结构化输出；
8. 主模型首 token 前失败后的 fallback 区分；
9. production-shaped RAG health 与历史问答；
10. request ID、trace ID、latency、usage 元数据。

真实测试必须：

- 禁止目标 profile fallback 证明自身通过；
- 记录 dataset/corpus version；
- 不把 prompt/output 写入 manifest；
- 所有报告绑定 commit/image/config/environment；
- skip/not_run 视为失败。

### 7.3 Manifest 与 Evidence 顺序

正确顺序：

```text
deploy exact digest
  -> verify /api/ready commit/image/config
  -> run all-profile probe
  -> build and validate manifest
  -> persist manifest
  -> runtime resolves exact DB manifest
  -> run real business/RAG profiles
  -> collect staging observations
  -> build and persist Release Evidence v2
  -> strict readiness and rollout gate
```

不得先生成 evidence，再把 manifest 仅作为 CI artifact 留在 Runner。

### 7.4 Staging 100-run 合同

Staging 可以使用版本化、合规脱敏的 canary dataset，通过公开业务 API 发起请求，但必须满足：

- 至少 100 个不同 run ID；
- 每个请求使用唯一 idempotency key；
- 使用真实认证账号；
- 经过完整 API、Runtime、LLM/RAG 和数据库路径；
- 不直接写 `agent_runs`、events 或 rollout observation 表；
- 不使用 demo seed 伪造；
- 记录 dataset version 与 workflow run ID；
- terminal consistency、event coverage、provenance coverage 均为 100%；
- duplicate side effect、invalid transition、high-risk violation 均为 0；
- observation write failure 为 0。

Staging 数据不能进入 production baseline。

---

## 8. Release Evidence Schema v2 闭环

### 8.1 必需 profiles

```text
offline
real_llm_business_eval
production_rag
llm_capabilities
```

`llm_capabilities` 至少包含：

- manifest hash；
- source=`database`；
- required profiles；
- passed profile count；
- image digest；
- runtime config version；
- environment；
- generated/expires time。

### 8.2 Evidence 与 manifest 引用

Release evidence 只保存 manifest 摘要和 hash，完整 manifest 保存于 manifest store。写 evidence 时必须验证对应 manifest 记录真实存在且可按 hash读取。

数据库约束无法跨 JSON 自动保证时，应用层必须在同一事务边界内：

1. 查询 manifest hash；
2. 再次验证 provenance/freshness；
3. 写入 release evidence；
4. 返回 evidence hash。

### 8.3 Staging gate

Staging gate 只有在以下条件全部满足时 PASS：

- exact manifest PASS；
- offline PASS；
- real LLM business PASS；
- production-shaped RAG PASS；
- control baseline 合法；
- staging Shadow terminal runs >=100；
- provenance coverage=1.0；
- event coverage=1.0；
- terminal consistency=1.0；
- p95 regression 在批准阈值内；
- 安全计数为 0；
- observation store 健康。

---

## 9. Production 晋级

### 9.1 晋级前置条件

Production 只能接收已通过 staging gate 的同一 digest。晋级请求必须携带：

```text
source_commit
image_digest
staging_manifest_sha256
staging_evidence_sha256
staging_config_version
staging_gate_result
approver
```

production 允许因 environment/config 不同生成新的 manifest/evidence，但 image digest 与 commit 必须与 staging 相同。

### 9.2 Production Shadow

在 active 1% 前，先运行 production Shadow：

- `history_character` 100% Shadow；
- 其他 Agent 0 BPS；
- 不改变学生响应；
- 收集真实 verified cohort observation；
- 运行 production all-profile/real business/RAG evidence；
- gate PASS 后才可 active。

### 9.3 Active 1%

配置目标：

```text
runtime_mode=active
global_bps=100
history_character_bps=100
other_agent_bps=0
active_enabled=true
```

要求：

- 只允许 stable-hash 命中的 verified student cohort；
- 至少 100 个合法 terminal runs；
- 不混入 anonymous/demo/unverified/operator；
- 同一 actor/run 不能因重试跨 cohort；
- evidence 与 deployment provenance 完全匹配；
- blocking condition 立即停止扩量。

### 9.4 Active 10% / 48h

1% gate PASS 后才可调整为：

```text
global_bps=1000
history_character_bps=1000
```

连续观察至少 48 小时，期间：

- 不更换 digest/model/config；
- manifest 必须保持新鲜；
- 不得清零或重建 observation；
- 每次状态变化记录操作者、时间和原因；
- 每小时保留聚合快照或等价可审计记录。

### 9.5 Blocking conditions

任一条件成立立即停止扩量：

- manifest/evidence hash 或 provenance mismatch；
- required capability fail；
- real business/RAG profile fail；
- 认证、迁移、数据库 readiness fail；
- duplicate side effect >0；
- high-risk without confirmation >0；
- terminal consistency <1.0；
- provenance coverage <1.0；
- observation write failure >0；
- p95 延迟超过批准阈值；
- 错误率显著高于 control；
- P0/P1 用户影响事件；
- secret 或内容泄漏。

---

## 10. Secret 清理

### 10.1 清理对象

检查并删除旧代理或迁移前遗留项，包括但不限于：

- Zode/旧代理 API key；
- 旧 Node helper 相关 endpoint/token；
- 已废弃 Provider key；
- 重复或过期的 DashScope/Bailian alias secret；
- 无消费者的 deploy hook；
- staging 中误复制的 production secret；
- 本地或 CI artifact 中的明文凭证。

### 10.2 清理证明

最终报告只记录：

- secret 名称；
- 所属环境；
- `present/removed/rotated/not_applicable`；
- 清理时间；
- 操作者；
- 运行时无读取引用的代码扫描结果。

不得记录 secret 值、长度片段或 hash。

### 10.3 回归

删除后必须验证：

- Backend 启动；
- shallow/deep health；
- all-profile probe；
- real business/RAG；
- GitHub workflow；
- rollback image。

---

## 11. 回滚设计

### 11.1 回滚制品

回滚目标必须满足：

- GHCR 中仍存在；
- 使用 exact digest；
- 有通过的 manifest；
- 有对应 Release Evidence v2；
- 数据库 migration 向后兼容；
- 模型 snapshot 与 endpoint 仍可用。

### 11.2 回滚顺序

1. active BPS 调为 0；
2. 设置 Runtime kill switch；
3. 关闭 optional capability flags；
4. 部署上一已验证 digest；
5. 恢复该 digest 对应 config；
6. 验证 `/api/health`、strict `/api/ready`、LLM/RAG；
7. 验证无重复副作用；
8. 记录事件与恢复时间；
9. 在原因查清前不重新扩量。

### 11.3 回滚演练验收

- 使用 staging 完整演练；
- production 在批准窗口执行受控演练；
- 目标 digest 可成功拉取；
- readiness 恢复；
- evidence 与目标 digest 匹配；
- 数据库无需破坏性 downgrade；
- 记录 RTO 和人工步骤；
- 不恢复旧 Provider/代理实现。

---

## 12. 代码与配置改动清单

预计新增：

```text
backend/alembic/versions/013_llm_capability_manifest_store.py
backend/llm/capability_store.py
eval/llm_capability_store_smoke.py
eval/llm_capability_runtime_resolution_smoke.py
eval/immutable_image_provenance_smoke.py
eval/staging_canary_contract_smoke.py
eval/production_promotion_contract_smoke.py
scripts/persist_llm_capability_manifest.py
scripts/verify_image_promotion.py
.github/workflows/backend-image-release.yml
.github/workflows/deploy-environment.yml
```

预计修改：

```text
backend/db/schema.py
backend/llm/capability_manifest.py
backend/llm/registry.py
backend/api/routers/debug.py
backend/deployment.py
backend/agent_runtime/evidence_store.py
backend/agent_runtime/rollout_gate.py
scripts/build_rollout_evidence.py
scripts/verify_deployed_commit.py
scripts/release_gate.py
.github/workflows/runtime-rollout-evidence.yml
render.yaml 或 Render 外部受控配置
SCHEMA.md
docs/20260830-llm-provider-operations-v144-runbook.md
```

具体文件名可在实现时微调，但职责不得重新混入业务 Agent。

---

## 13. 实施里程碑

### Milestone A：不可变镜像

- GHCR build/push workflow；
- digest artifact；
- deploy exact digest；
- readiness digest verification；
- production auto-deploy 关闭。

### Milestone B：Manifest Store

- migration 013；
- append-only store；
- write/read validator；
- exact provenance resolver；
- Runtime cache/fail-closed；
- API/readiness source 字段。

### Milestone C：Staging 闭环

- 独立服务/数据库/secrets；
- all-profile probe；
- real business/vision/stream/long-output/RAG；
- manifest + Evidence v2 入库；
- staging >=100 terminal runs；
- staging gate PASS。

### Milestone D：Production Canary

- 同 digest 晋级；
- production Shadow；
- active 1% >=100 terminal runs；
- active 10% / 48h；
- blocking condition 监控。

### Milestone E：运维完成

- secret 清理；
- rollback drill；
- 最终报告；
- Spec 状态更新为 Complete。

Milestone C、D、E 未完成时，本 Spec 不得标记 Complete。

---

## 14. 测试计划

### 14.1 Deterministic tests

至少覆盖：

- manifest DB insert/load/idempotency；
- invalid hash/provenance/freshness 拒绝写入；
- 8-profile coverage；
- exact DB resolver；
- file override warning；
- DB unavailable optional capability fail-closed；
- cache key provenance 隔离；
- expired cache 不可继续启用 optional capability；
- evidence 引用不存在的 manifest 时拒绝；
- image digest 格式与 readiness mismatch；
- staging/production Environment 隔离；
- production deploy 不能使用未通过 staging 的 digest；
- production auto-deploy 配置拒绝；
- sample scope/cohort/idempotency；
- rollback target 缺少 manifest/evidence 时拒绝。

### 14.2 Integration tests

- migration 012 -> 013；
- fresh database -> head；
- PostgreSQL jsonb/text 兼容；
- 并发写入同 hash 幂等；
- manifest + evidence 事务一致性；
- GitHub workflow contract；
- GHCR digest capture；
- Render deployment response 验证；
- staging readiness；
- 管理员 API 认证与内容最小化。

### 14.3 Real-provider and deployment tests

- 全部 8 profile required checks；
- vision base64；
- stream complete/interrupted；
- material/card_pool 长输出；
- primary/fallback 区分；
- history character RAG；
- production-shaped RAG；
- 同 digest staging -> production；
- 1% 与 10% canary；
- rollback exact digest。

### 14.4 Release gate

必须拒绝：

- mutable tag；
- digest 缺失或格式错误；
- commit/digest/config/environment mismatch；
- manifest store 不可用；
- manifest missing/stale/invalid；
- required profile skip/not_run；
- real business/vision/stream/RAG 缺失；
- schema v1 evidence；
- staging gate 非 PASS；
- production 样本不足；
- production auto-deploy 未关闭；
- rollback target 无可信证据。

---

## 15. 验收标准

### 15.1 代码验收

1. Backend 镜像只构建一次并产生真实 registry digest；
2. Manifest 可持久化并由 Runtime 精确解析；
3. Manifest/evidence 与 digest 强绑定；
4. Runtime 不再依赖 GitHub Runner 临时文件；
5. optional capability 缺证据时 fail-closed；
6. staging/production secrets 与数据库隔离；
7. deterministic、migration、core、frontend 与 workflow tests 通过；
8. 无 secret 或学生内容泄漏。

### 15.2 Staging 验收

1. exact digest 部署成功；
2. strict readiness PASS；
3. capability manifest PASS；
4. 8 profiles required checks PASS；
5. real business/vision/stream/long-output/RAG PASS；
6. Evidence Schema v2 入库；
7. >=100 terminal runs；
8. rollout gate PASS；
9. rollback staging 演练成功。

### 15.3 Production 验收

1. 使用 staging 已通过的同一 digest；
2. production manifest/evidence 与当前部署匹配；
3. Shadow gate PASS；
4. 1% >=100 terminal runs 且 gate PASS；
5. 10% 连续 48 小时无 blocking condition；
6. secret 清理完成；
7. production rollback 演练成功；
8. 最终报告包含真实 commit/image/config/manifest/evidence/canary 数据。

### 15.4 禁止的完成声明

以下均不得标记 Complete：

- 只有 commit，没有 image digest；
- 只有 CI artifact，没有 Runtime 可读取 manifest；
- 只部署 production，没有 staging；
- 重新构建“相同 commit”代替同 digest 晋级；
- real-provider test skip/not_run；
- 只通过 shallow/deep health；
- staging 或 production 样本不足；
- 48h 未完成；
- secret 清理或回滚未执行；
- `Code complete · external validation pending`。

---

## 16. 风险与控制

| 风险 | 控制 |
| --- | --- |
| GHCR/Render 权限复杂 | GitHub Environment 审批、最小权限 token、先 staging |
| image digest 与环境变量人工错配 | workflow 同时更新、部署并回读 Render API + readiness |
| manifest DB 不可用影响产品 | control 路径继续，optional capability fail-closed |
| staging 污染 production | 独立数据库、secret、账号与 Environment |
| 100 个 staging 请求变成伪造样本 | 必须走公开 API/真实 Runtime，不得 DB 直写，记录 dataset version |
| production 流量不足 | 保持 1%，不降低样本门槛；等待真实 verified cohort |
| mutable tag 漂移 | 部署只接受 digest |
| rollback 镜像被清理 | GHCR retention 保护当前与上一可信 digest |
| migration 无法回退 | 013 仅增表，应用兼容 012/013 读路径，禁止破坏性 downgrade |
| secret 清理误删 | 先做代码消费者扫描、逐项清理、每项回归 |
| 再次转向框架扩建 | Native Structured Output/Tool Calling/LangGraph 明确列为非目标 |

---

## 17. 运营时间线与责任记录

Spec 不预设自然日工期，但要求按以下顺序记录事件：

```text
T0 image built
T1 staging deployed
T2 staging manifest persisted
T3 staging evidence persisted
T4 staging 100-run gate passed
T5 production same digest deployed
T6 production shadow passed
T7 production 1% started
T8 production 1% 100-run gate passed
T9 production 10% started
T10 production 10% 48h completed
T11 rollback drill completed
T12 secret cleanup verified
```

每个事件记录：

- UTC/Asia-Shanghai 时间；
- operator/approver；
- commit/image/config；
- manifest/evidence hash；
- before/after rollout BPS；
- gate 结果；
- rollback reason（若有）。

---

## 18. v1.46 边界

只有本 Spec Complete 后，才生成并实施 v1.46 Native Structured Output 纵向切片。

建议首个切片为学生周报 `_llm_narrative`：

- 非流式；
- Pydantic schema 简单；
- 无工具调用；
- 无关键外部副作用；
- 有规则 fallback；
- 已有 smoke；
- 可采用 `control -> shadow -> native_active` 对比。

v1.46 仍不要求 `create_agent` 或 LangGraph；优先使用当前 `ManagedChatModel.with_structured_output()` 与 v1.45 能力门禁。百炼 OpenAI-compatible endpoint 的支持必须以 live manifest 为准，不能只依赖 SDK 自动推断。

---

## 19. 最终完成定义

v1.45.2 Complete 意味着：

> EduAgent 能够从一个 clean commit 构建唯一不可变 Backend 镜像，将完全相同的 digest 从 staging 晋级到 production；运行时能够从数据库解析与当前 commit/image/config/environment/model 完全匹配的 capability manifest，并以真实 Provider、RAG、staging 样本、production canary、secret 清理和回滚证据证明本次发布可用。

任何一个外部证据仍为 `NOT_RUN` 时，状态保持 `In Progress/Blocked`。
