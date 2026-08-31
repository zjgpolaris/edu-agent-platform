# EduAgent 不可变部署与 LLM 证据闭环 v1.45.2 实施报告

> **状态：发布链路已退役。** 项目现按 Agent Demo 运行，不再启用 GHCR immutable image、独立 staging、Render digest deploy 或 production canary 工作流；底层运行时观测与能力清单代码仍保留。

**日期：** 2026-08-31
**状态：** Development Complete · External Rollout NOT_RUN

## 已实现

- Alembic 013 与 append-only `llm_capability_manifests`，支持 hash 幂等写入、内容最小化检查、exact provenance 查询；
- Runtime 默认按 environment/commit/image/config/endpoint 从数据库解析，60 秒 provenance-keyed cache；测试/break-glass 文件覆盖会在 production 返回 warning；数据库不可用时 optional capability fail-closed；
- Evidence Schema v2 入库前在同一数据库事务中校验引用 manifest 存在且 provenance 一致；
- `/api/ready` strict Runtime 模式要求 capability manifest PASS，管理员 API 与 readiness 共用同一解析结果；
- GHCR `linux/amd64` build-once workflow，输出 registry digest、source commit、Dockerfile/requirements hash 和 SBOM/provenance；
- staging/production 受保护环境的 digest 部署工作流，production 需要 staging 或 48 小时 production evidence；
- evidence 流程改为 capability probe → manifest 入库 → 真实业务/RAG → Evidence v2；
- 生产 Blueprint 关闭 auto-deploy，并要求 image digest 与 Evidence v2；
- 删除运行时代码对旧 `DASHSCOPE_API_KEY` alias 的读取，只保留 `BAILIAN_API_KEY`；
- 新增 Manifest Store、Runtime resolution、immutable provenance、staging canary、production promotion 五组 deterministic smoke。

## 本地验证

- fast release gate：`56/56 suites`、`512/512 cases`，PASS；
- full backend smoke gate：`105/106 suites`、`405/406 cases`，gate PASS；唯一 skip 为需要真实 Provider/RAG 的 `history_character_smoke`，保持外部 `NOT_RUN`；
- frontend Next.js production build：PASS（50/50 routes generated）；
- 三个 GitHub workflow YAML parse：PASS；
- Alembic fresh SQLite rehearsal：`013 (head)`；真实 PostgreSQL 012→013 rehearsal 配置在 image release/CI job，当前本地未伪造其结果。

## 外部状态

以下必须使用真实基础设施执行，本地代码和测试不能替代，当前均为 `NOT_RUN`：

- 创建独立 Render staging image-backed service、独立 PostgreSQL/pgvector 与隔离 secrets；
- GHCR 真实 push、Render exact digest 部署和 strict readiness；
- 全 8 profile live probe、真实业务/视觉/流式/长输出与 production-shaped RAG；
- staging ≥100 terminal runs 与 gate PASS；
- 同 digest production 1% ≥100、10%/48h；
- Render/GitHub secret store 中旧 alias/代理 secret 的实际删除或轮换；
- 上一可信 digest 的 staging/production 回滚演练和 RTO；
- 最终生产 hash、样本、错误率、延迟与 canary 报告。

因此 Spec Milestone A/B 的代码路径完成，C/D/E 的外部执行仍未完成；不得将本报告标记为 Production Complete。
