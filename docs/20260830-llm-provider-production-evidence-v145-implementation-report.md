# EduAgent LLM Provider 生产证据闭环与能力门禁 v1.45 实施报告

**日期：** 2026-08-30

**基线：** `main@3c67314`

**状态：** In Progress · Milestone A/B/C code complete · Milestone D external evidence NOT_RUN

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
