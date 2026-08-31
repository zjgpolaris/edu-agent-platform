# EduAgent LLM Provider 生产证据闭环与能力门禁 v1.45 实施报告

**日期：** 2026-08-30

**基线：** `main@3c67314`

**状态：** Blocked / Not Ready · Milestone A/B/C code complete · Milestone D 缺少 staging 准入条件

## 已完成

- 新增 hash-bound `LLMCapabilityManifest`：绑定 commit、image digest、Runtime config、environment、endpoint fingerprint、SDK 版本、profile/model/max tokens/fallback、时间窗口与 manifest hash；
- live probe 扩展到全部 8 个运行 profile，目标 profile 探测时禁止 fallback；
- required 与 optional capability 分离，Tool Calling/Native Structured Output 默认关闭；
- Registry 暴露 configured/validated/enabled 三类能力，optional capability 只有显式 flag 与有效 manifest 同时满足才可启用；
- 新增管理员只读 `/api/admin/llm/capabilities`；
- 收窄 deep LLM health 语义为 `fast_connectivity_only`；
- Runtime release evidence 支持 schema v2，绑定 image digest、real business eval 与 capability manifest；
- schema v1 保持历史读取兼容，可通过 `EDU_AGENT_REQUIRE_LLM_EVIDENCE_V2=true` 对 v1.45 rollout fail-closed；
- real LLM profile 扩展为全 profile probe、语义路由、历史人物质量评测和真实历史人物主路径；
- Runtime rollout evidence workflow 增加 immutable image digest 输入、manifest 生成、schema v2 持久化；
- 新增 manifest、API、篡改、过期、provenance mismatch、optional capability 门禁与 evidence v2 deterministic smoke。

## 本地验证

已通过：

```text
llm_capability_manifest_smoke=PASS
llm_capability_api_smoke=PASS
llm_provider_contract_smoke=PASS
readiness_smoke=4/4
rollout_evidence_supply_chain_smoke=PASS
agent_runtime_rollout_gate_smoke=PASS
```

Release gate 与完整离线 core：

```text
fast release gate: 46/46 suites, 512/512 cases, PASS
offline core: 83/84 suites, 641/650 cases
only skipped: history_character_eval（需要真实 LLM/RAG，外部证据保持 NOT_RUN）
```

## 外部环境状态

以下按 v1.45 Spec 保持 NOT_RUN，不以本地测试替代：

1. 当前部署 commit/image/config 的百炼 all-profile live probe；
2. 真实 `history_character_eval/history_character_smoke`；
3. 材料视觉与真实流式业务证据；
4. production RAG profile；
5. schema v2 evidence 在 staging PostgreSQL 持久化；
6. staging >=100 terminal runs；
7. production 1% >=100 terminal runs；
8. production 10%/48h；
9. 部署 secret store 旧代理凭证清理；
10. 生产回滚演练。

Milestone D 未完成前，本版本不得标记 Complete。

## 2026-08-31 续作与环境盘点

代码验收继续补齐：

- 按 Spec 13.1 将 7 个能力合同测试拆分为独立 smoke：manifest、provenance、gate、admin API、release evidence v2、profile coverage、fallback；
- 7/7 能力合同 smoke 通过；
- 更新后的 fast release gate：51/51 suites、512/512 cases，PASS；
- 完整后端 smoke：95/96 suites、405/406 cases；唯一 skip 仍为需要真实 Provider/RAG 的 `history_character_smoke`；
- 前端 Next.js production build 通过；
- Runtime evidence workflow 已支持 `staging` 与 `production` 两个受保护 GitHub Environment，不再把 evidence 目标硬编码为 production。

对现有 Render 生产服务进行了无凭证只读盘点：

- `/api/health`：PASS；
- `/api/ready`：shallow readiness PASS，状态 degraded 仅来自 latest eval 与 rollout evidence 缺失；
- 当前线上 commit：`3c673147f22bdb63918814281c500e24f8408278`；
- 当前 Runtime config：`v1.41-history-control`，Runtime rollout disabled；
- PostgreSQL、Alembic `012`、pgvector 与 `rag_documents` 正常；history collection 文档数为 2850；
- LLM Provider 配置与凭证存在，但受保护的 deep health/all-profile probe 未在无管理员凭证条件下执行；
- 当前线上版本尚未暴露 v1.45 image digest/capability manifest/evidence v2 字段。

根据 Spec Definition of Ready，当前仍缺：staging backend、staging 百炼/API 与数据库 secrets、管理员 smoke 凭证、不可变 image digest、canary owner/测试账号和 secret-store 管理权限。生产服务启用了 main auto-deploy；在 staging 验收缺失时不得直接推送并以生产替代 staging。
