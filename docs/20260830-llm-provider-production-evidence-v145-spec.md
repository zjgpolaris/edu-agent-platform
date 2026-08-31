# EduAgent LLM Provider 生产证据闭环与能力门禁 v1.45 Spec

**创建时间：** 2026-08-30

**状态：** In Progress · Milestone A/B/C complete · Milestone D blocked on staging access

**目标版本：** v1.45.0（能力证据合同）+ v1.45.1（真实业务评测与发布证据）+ v1.45.2（staging / production canary 闭环）

**优先级：** P0 生产迁移闭环；原生 Tool Calling / Native Structured Output 仅形成能力证据，不在本版本进入生产业务路径

**适用范围：** `backend/llm/`、LLM 健康检查、真实 Provider 评测、Runtime release evidence、staging/production rollout；不改变 Runtime v2、Tool Registry、RAG、Evidence Verifier 和产品 API 的职责边界

**前置基线：** `main@3c67314`（v1.44 LLM Provider LangChain 迁移代码完成）

**关联文档：**

- `docs/20260830-llm-provider-langchain-migration-v144-spec.md`
- `docs/20260830-llm-provider-migration-v144-implementation-report.md`
- `docs/20260830-llm-provider-operations-v144-runbook.md`
- `docs/202608280000-agent-runtime-langgraph-boundary-adr.md`
- `docs/202608281900-agent-runtime-production-evidence-v140-spec.md`
- `docs/202608292100-agent-runtime-rollout-operations-v142-spec.md`

---

## 0. 决策摘要

v1.45 不扩展 Agent 架构，不进行 LangSmith 替换，也不重写 AutoTutor/Learning Assistant。本轮关闭 v1.44 尚未完成的真实 Provider、真实业务链路、部署 provenance 和 canary 证据缺口，使“模型能力探测”成为可验证、可过期、可进入发布门禁的生产证据。

当前 v1.44 已完成：

- 使用 `langchain-openai` 直连百炼 OpenAI-compatible API；
- 建立 Provider/Profile Registry 与 Managed model；
- 删除旧 Node LLM helper、Zode 代理和隐式跨 Provider fallback；
- 保持旧业务 invoke/stream/fallback/trace 合同；
- 增加离线 Provider smoke 与显式 opt-in 的 live capability probe；
- 固定并验证 LangChain/LangGraph/OpenAI SDK 运行版本。

但当前仍不能宣称生产迁移完成：

1. capability probe 产生的 JSON 未绑定部署 commit、镜像、Runtime config 和环境；
2. probe 结果未进入 Runtime release evidence，也不决定有效能力；
3. 默认 probe 未覆盖 `fallback`、`material`、`card_pool` 全部运行 profile；
4. `real_llm` evidence 只证明存在真实调用，不能证明所有实际业务 profile 和调用合同；
5. `history_character_eval`、材料视觉、真实流式和 production RAG 尚未形成同一 clean commit 的闭环证据；
6. `/api/debug/llm/health?deep=true` 只证明 fast profile 的单次连通性，不能代表全 profile 能力；
7. staging/production canary、部署 secret 清理和生产镜像验证仍为 NOT_RUN。

本轮目标证据链：

```text
clean commit + immutable image + runtime config
  → all-profile synthetic capability probe
  → real business-path eval
  → production RAG profile
  → hash-bound LLM Capability Manifest
  → Runtime release evidence schema v2
  → staging shadow / active observations
  → per-agent rollout gate
  → production canary / rollback decision
```

本轮完成标准必须包含真实环境证据，不接受再次以“Code complete · external validation pending”作为 Complete。

---

## 1. 当前事实与核心缺口

### 1.1 Capability probe 已有能力

`backend/llm/capability_probe.py` 当前能够测试：

- 普通 invoke；
- stream；
- prompt-based JSON；
- native structured output；
- tool calling；
- vision base64（仅视觉 profile）。

当前 `result=pass` 只要求 profile 声明的基础能力通过。Tool Calling 和 Native Structured Output 即使失败，也不会使基础 profile 失败。这个语义适合兼容迁移，但当前报告没有明确区分“基础发布通过”和“增强能力可启用”。

### 1.2 Registry 与 probe 没有闭环

`backend/llm/registry.py` 中的 capabilities 由代码静态声明：

- 文本 profile：`chat/stream/json_prompt`；
- 多模态 profile：`chat/vision/json_prompt`；
- `tools/native_structured_output` 默认不声明。

`ManagedChatModel.bind_tools()` 和 `with_structured_output()` 会按静态 capabilities fail-closed，但 Registry 不读取 live probe 结果。当前 probe 只能用于人工查看，不能成为可审计的部署能力来源。

### 1.3 Real LLM evidence 粒度不足

现有 `scripts/build_rollout_evidence.py` 将 real LLM profile 判定为：

- 报告整体通过；
- clean commit 与 deployed commit 一致；
- evidence profile 为 `real_llm`；
- 存在至少一个 run-scoped LLM call。

该合同不能证明：

- `fast/quality/reasoning/fallback` 是否都可用；
- multimodal 和 multimodal_quality 的 vision 是否可用；
- material/card_pool 的不同 max token 合同是否可用；
- stream 是否在实际业务链路中工作；
- 某个 fallback 是否因主模型持续失败而掩盖配置问题。

### 1.4 健康检查语义过宽

当前 deep LLM health 只调用 `llm_fast` 一次。它可以证明服务端到 Provider 的基础连通性，但不能证明：

- quality/reasoning/multimodal 模型存在；
- vision、tool calling 或 native structured output 可用；
- 全部 profile 的 fallback 与 token 参数合法；
- 真实 Agent 输出质量达标。

v1.45 必须在 API 响应和 Runbook 中收窄这一语义。

### 1.5 外部环境长期未闭环

Runtime v1.39-v1.44 已建立大量 deterministic contract、evidence 和 rollout 代码，但多个实施报告仍把真实 LLM、production RAG、PostgreSQL、staging traffic 和 production canary 标记为 NOT_RUN。

v1.45 的主要风险不是代码难度，而是继续在缺少外部权限时扩建验证框架。为避免该问题，本 Spec 将外部环境列入 Definition of Ready，并将真实 canary 列入 Definition of Done。

---

## 2. 目标与非目标

### 2.1 工程目标

1. 建立版本化、hash-bound、可过期的 `LLMCapabilityManifest`；
2. 覆盖所有实际运行 profile，不只覆盖默认五个 profile；
3. 明确区分 required capabilities 与 optional capabilities；
4. 将 capability manifest 绑定到 commit、image digest、Runtime config、环境、Provider、模型和依赖版本；
5. 将 capability manifest 纳入 Runtime release evidence schema v2；
6. 让当前部署能够只读展示“配置能力、已验证能力、已启用能力”的差异；
7. 让模型/Provider/endpoint/SDK/config 变化自动使旧能力证据失效；
8. 让 real LLM profile 证明真实业务链路，而不只是证明发生过一次 LLM 调用；
9. 完成 staging shadow、production canary 和回滚演练；
10. 保持观测失败不影响业务，但证据缺失必须阻止 rollout 扩量。

### 2.2 产品与运营目标

1. v1.44 迁移后的历史人物、教材问答、材料理解、批改、游戏生成和流式链路在真实 Provider 上行为等价；
2. 模型变更可以按 profile 判断是否允许发布；
3. 运营能够从管理员接口确认当前模型能力证据是否新鲜、是否匹配部署；
4. 生产问题可以关联到 exact model、provider request ID、trace ID、commit、config 和 image；
5. 基础能力可正常发布时，不因 optional capability 失败而错误阻断；
6. optional capability 未经单独灰度不得进入生产路径。

### 2.3 非目标

- 不迁移或替换 Langfuse；
- 不全面引入 LangSmith；
- 不引入 LangSmith Deployment/Agent Server；
- 不重写 AutoTutor 或 Learning Assistant 为 LangGraph；
- 不扩大开放式 Agent、ReAct、dynamic re-plan、read fan-out 或 Agent 委派；
- 不增加第二个在线 LLM Provider；
- 不开放任意工具执行；
- 不在生产业务中启用原生 Tool Calling；
- 不在生产业务中启用 Native Structured Output；
- 不用 synthetic probe 替代真实业务质量评测；
- 不用 fallback 输出证明主模型能力通过；
- 不把学生正文、图片 base64 或敏感 Artifact 写入 capability manifest/release evidence。

---

## 3. Definition of Ready

v1.45 开始实施前必须确认：

1. 可用的 staging 百炼 API key，且允许调用本 Spec 中全部模型；
2. 可部署 staging backend 的权限；
3. 可获取或注入 `deployed_commit`、`image_digest`、`runtime_config_version` 和 environment；
4. 可构建并推送生产等价 Docker image；
5. staging PostgreSQL/pgvector 已迁移到当前 Alembic head；
6. production RAG embedding/index/health 可用；
7. 可读取并清理部署 secret store 中旧代理凭证；
8. 有权限执行 staging shadow 与 production canary；
9. 有真实或合规脱敏的 eval dataset，且 dataset version 可记录；
10. 明确 canary owner、停止条件和回滚责任人。

若以上条件缺失，本迭代状态保持 `Blocked/Not Ready`，不以增加更多本地 smoke 代替外部闭环。

---

## 4. LLM Capability Manifest 合同

### 4.1 Manifest 示例

```json
{
  "schema_version": 1,
  "provider": "bailian",
  "transport": "langchain_openai",
  "deployed_commit": "3c67314...",
  "image_digest": "sha256:...",
  "runtime_config_version": "v1.45-provider-staging",
  "environment": "staging",
  "endpoint_fingerprint": "sha256:...",
  "dependencies": {
    "python": "3.13.x",
    "langchain_core": "1.6.1",
    "langchain_openai": "1.6.0",
    "langgraph": "1.2.11",
    "openai": "3.6.0"
  },
  "profiles": {
    "quality": {
      "profile_name": "llm_quality",
      "model": "qwen3.7-plus",
      "max_tokens": 2048,
      "fallback_profiles": ["fast", "fallback"],
      "required_checks": {
        "invoke": {"status": "pass", "latency_ms": 1200},
        "stream": {"status": "pass", "latency_ms": 1500},
        "json_prompt": {"status": "pass", "latency_ms": 1100}
      },
      "optional_checks": {
        "tool_calling": {"status": "pass", "latency_ms": 1300},
        "native_structured_output": {"status": "fail", "error_type": "LLMProviderError"}
      },
      "required_status": "pass",
      "validated_capabilities": ["chat", "stream", "json_prompt", "tool_calling"],
      "trace_ids": ["..."]
    }
  },
  "generated_at": "2026-08-30T00:00:00Z",
  "expires_at": "2026-09-06T00:00:00Z",
  "manifest_sha256": "sha256:..."
}
```

### 4.2 Provenance 要求

Manifest 必须绑定：

- 完整 deployed commit；
- 不可变 image digest；
- Runtime config version；
- environment；
- Provider 与 transport；
- endpoint fingerprint（不得保存 API key、query 或 Authorization）；
- 每个 profile 的 exact model、max tokens、fallback profile；
- LangChain/OpenAI/Python 版本；
- 生成时间、过期时间、trace ID；
- manifest 自身 hash。

任一绑定字段变化，旧 manifest 不得继续证明新部署。

### 4.3 新鲜度

- 默认有效期：7 天；
- production 可配置更短有效期；
- 模型 alias、snapshot、SDK、endpoint、image 或 config 变化时立即失效；
- `expires_at` 之后管理员接口返回 `stale`；
- stale/invalid manifest 不阻止已运行 control 路径，但阻止新 rollout 扩量和 optional capability 启用。

### 4.4 数据最小化

Manifest 不得包含：

- API key、Authorization header；
- 原始 endpoint query；
- 测试 prompt 和完整模型输出；
- 学生、教师或真实用户输入；
- 图片 base64；
- raw provider error body；
- confirmation token；
- Artifact 内容。

允许包含：

- 错误类型与稳定 error code；
- 延迟、成功状态、输出 schema 是否有效；
- provider request ID；
- trace ID；
- 输出字符数/usage 等非内容指标。

---

## 5. Profile 与能力矩阵

### 5.1 Required capabilities

| Profile | 实际用途 | Required checks |
| --- | --- | --- |
| `fast` | 路由、抽取、总结、轻量生成 | invoke、stream、json_prompt |
| `quality` | RAG 回答、批改、复杂生成 | invoke、stream、json_prompt |
| `fallback` | 文本模型降级 | invoke、stream、json_prompt |
| `reasoning` | 复杂推理 | invoke、stream、json_prompt |
| `multimodal` | 普通图片理解/OCR | invoke、vision_base64、json_prompt |
| `multimodal_quality` | 高质量图片理解 | invoke、vision_base64、json_prompt |
| `material` | 材料处理、长上下文结构化抽取 | invoke、json_prompt、configured_max_tokens |
| `card_pool` | 多人卡池长结构化输出 | invoke、json_prompt、configured_max_tokens |

`material/card_pool` 即使复用 fast 模型，也有不同 max token 和业务合同，必须直接探测或在 manifest 中记录经过验证的严格等价关系，不能只按模型名推导通过。

### 5.2 Optional capabilities

所有适用文本 profile 可探测：

- `tool_calling`；
- `native_structured_output`；
- usage metadata；
- provider request ID；
- reasoning metadata（仅 reasoning profile，若 Provider 返回）。

Optional capability 失败不会阻断 v1.44 兼容路径，但必须保持对应 feature flag 关闭。

### 5.3 Fallback 判定

Probe 默认禁止 fallback，用于证明目标 profile 自身可用。另设独立 fallback contract probe，证明：

- 主模型在首 token 前失败时可切换；
- 已输出 token 后不会拼接另一个模型；
- fallback attempt 可在 trace 中区分；
- authentication/configuration error 不被无意义重试；
- fallback 不能让主 profile 的 capability status 变为 pass。

---

## 6. 运行时能力门禁

### 6.1 三类能力视图

Registry/管理员接口必须区分：

1. `configured_capabilities`：代码和配置声明的能力；
2. `validated_capabilities`：当前匹配 manifest 已证明的能力；
3. `enabled_capabilities`：显式 feature flag 允许且 validated 的能力。

关系必须满足：

```text
enabled_capabilities
  ⊆ validated_capabilities
  ⊆ configured_capabilities ∪ probed_optional_capabilities
```

### 6.2 启用规则

本版本只实现门禁，不在生产业务启用 optional capability。未来启用时必须同时满足：

- feature flag 显式开启；
- manifest 存在且未过期；
- commit/image/config/environment/model 完全匹配；
- 对应 capability status 为 pass；
- Agent 在 allowlist；
- Tool Calling 继续经过 Runtime v2 与 Tool Registry；
- 不允许模型直接执行任意 Python 函数或绕过确认/审计。

### 6.3 Fail-closed

以下情况 optional capability 必须不可用：

- manifest 缺失、hash 无效或过期；
- manifest 与部署 provenance 不一致；
- profile/model/max tokens 不一致；
- capability 未探测、失败或 unknown；
- feature flag 未开启；
- Agent 不在 allowlist；
- Tool Registry/Runtime policy 未准备好。

基础兼容调用是否允许继续，由对应 profile required capability 和 rollout mode 决定，不因 optional capability 不可用而错误中断。

---

## 7. 真实业务评测 Profile

### 7.1 必跑套件

`real_llm` evidence 至少覆盖：

1. `learning_assistant_semantic_router_eval`；
2. `history_character_eval`；
3. `history_character_smoke` 或等价真实 RAG + LLM 主路径；
4. 教材问答真实生成；
5. 材料图片理解真实链路；
6. 一个真实流式业务链路（历史人物、历史地图或教材摘要）；
7. 一个长结构化输出业务链路（card pool、作文批改或材料抽取）；
8. Provider live capability probe。

若某套件依赖的业务未部署，可在 Spec 实施阶段将其标为不适用，但必须有明确替代套件；release-required run 不允许 blocking skip。

### 7.2 每条真实链路的 provenance

每条套件至少记录：

- eval run ID；
- dataset name/version/hash；
- deployed commit；
- image digest；
- Runtime config version；
- Agent/业务能力；
- profile 与 exact model；
- Provider/transport；
- run-scoped真实调用数；
- fallback 次数；
- provider request ID/trace ID；
- 首 token 延迟、总延迟；
- 输出合同/引用/grounding 是否通过；
- infra failure 与 quality failure 分类。

### 7.3 通过条件

- 所有必跑套件实际运行；
- 0 blocking skip；
- 0 未分类 failure；
- required profile 均观察到真实 Provider 调用；
- 输出 schema、引用和安全合同不回退；
- fallback 可观察且不用于掩盖主 profile capability failure；
- 报告来自同一 clean deployed commit/config/image；
- 报告在规定新鲜度窗口内。

---

## 8. Release Evidence Schema v2

### 8.1 目标结构

```json
{
  "schema_version": 2,
  "agent_type": "history_character",
  "config_version": "v1.45-provider-staging",
  "runtime_mode": "shadow",
  "deployed_commit": "...",
  "image_digest": "sha256:...",
  "environment": "staging",
  "profiles": {
    "offline": {"status": "pass"},
    "real_llm_business_eval": {"status": "pass"},
    "production_rag": {"status": "pass"},
    "llm_capabilities": {
      "status": "pass",
      "manifest_sha256": "sha256:...",
      "required_profiles": ["quality"],
      "required_capabilities": ["invoke", "stream", "json_prompt"]
    }
  },
  "control_baseline": {},
  "evidence_sha256": "sha256:..."
}
```

### 8.2 Schema 兼容策略

- v1 evidence 继续允许只读和历史展示；
- v1.45 新部署不得使用 v1 evidence 产生新的 rollout PASS；
- schema v2 入库前校验 manifest hash、provenance、freshness 和 required profile；
- 数据库唯一性继续使用 evidence hash 幂等；
- 不修改历史 evidence payload；
- 若需数据库字段扩展，优先把 image digest/manifest digest 作为可索引列，其余保留在 payload JSON。

### 8.3 Real LLM profile 新判定

不再只以“至少一个真实 LLM call”判定通过。v2 必须验证：

- `real_llm_business_eval` 全部必跑套件通过；
- capability manifest 匹配当前部署；
- 当前 Agent 使用的每个 required profile 都已验证；
- 真实调用模型集合与 manifest 一致；
- provider/model provenance 完整；
- blocking skip、unknown model、fallback-only success 均失败。

---

## 9. 健康检查与管理员接口

### 9.1 `/api/debug/llm/health`

浅检查只返回：

- Provider/transport；
- credentials configured；
- 配置 profile/model/fallback；
- deployed commit/config/image presence；
- manifest presence/freshness 摘要。

不得发起真实模型请求。

### 9.2 `/api/debug/llm/health?deep=true`

deep health 继续只进行低成本 fast connectivity 检查，并明确返回：

```json
{
  "scope": "fast_connectivity_only",
  "proves": ["credentials", "endpoint_connectivity", "fast_invoke"],
  "does_not_prove": ["all_profiles", "vision", "tool_calling", "native_structured_output", "business_quality"]
}
```

它不能作为 capability manifest 或 real LLM release evidence 的替代品。

### 9.3 管理员能力接口

新增：

```text
GET /api/admin/llm/capabilities
```

返回：

- manifest status/freshness/hash；
- deployment provenance match；
- 每个 profile 的 configured/validated/enabled capabilities；
- required/optional check 状态；
- release blocking reasons；
- trace ID/request ID 的安全引用；
- 不返回 prompt、output、学生内容、图片或 secret。

访问控制复用现有可信管理员认证，不新增客户端自报角色。

---

## 10. Staging 与 Production Rollout

### 10.1 Staging 顺序

1. 从 clean commit 构建不可变 image；
2. 部署并记录 commit/image/config/environment；
3. 完成 Alembic/PostgreSQL schema readiness；
4. 运行 all-profile capability probe；
5. 运行 offline core；
6. 运行 real LLM business profile；
7. 运行 production RAG profile；
8. 生成、校验并持久化 schema v2 release evidence；
9. 历史人物进入 100% observable/shadow；
10. 采集至少 100 个 terminal runs；
11. rollout gate 达到 pass 后才允许 active canary。

### 10.2 Production canary

第一阶段：

```dotenv
EDU_AGENT_RUNTIME_V2_SHADOW_MODE=false
EDU_AGENT_RUNTIME_V2_PERCENT_BPS=100
EDU_AGENT_RUNTIME_V2_HISTORY_CHARACTER_BPS=100
EDU_AGENT_RUNTIME_V2_CONFIG_VERSION=v1.45-provider-canary-1pct
```

要求：

- optional capability flags 全部关闭；
- 只扩量已拥有 schema v2 evidence 的 Agent/profile；
- 至少 100 个合法 terminal runs；
- gate pass 后扩大到 10%；
- 10% 连续观察至少 48 小时；
- 最后才考虑全量。

### 10.3 Blocking conditions

任一条件满足即停止扩量：

- capability manifest 缺失、过期、hash 无效或 provenance mismatch；
- required profile/capability 非 pass；
- vision 失败但材料图片入口仍被视为 ready；
- real business eval 有 blocking skip；
- unexpected failure rate >2%；
- event coverage <95%；
- terminal consistency <100%；
- p95 相对 control 回退 >10%；
- fallback rate 超过基线阈值或主模型持续不可用；
- duplicate side effect executed >0；
- invalid transition >0；
- high-risk without confirmation >0；
- trace/LLM provenance 缺失导致问题不可定位。

---

## 11. 回滚方案

按以下顺序执行：

1. 保持所有 optional capability 关闭；
2. 将 Agent rollout 比例降为 0，回到 control；
3. 使用 Runtime kill switch 关闭受影响 Agent active path；
4. 回滚到最近一个 schema v2 evidence 与 capability manifest 均通过的 image；
5. 必要时在同一百炼 Provider 内切换到已验证的固定模型 snapshot；
6. 极端情况下设置 `EDU_AGENT_LLM_DISABLED=true`，使用已有产品 degraded/fallback；
7. 记录 rollback reason、commit/config/image/model、影响窗口和恢复验证。

不得恢复：

- 旧 Zode/Node helper；
- 未验证模型 alias；
- 隐式跨 Provider fallback；
- 无 manifest 的 Tool Calling/Native Structured Output；
- 绕过 Runtime/Tool Registry 的直接工具执行。

---

## 12. 实施里程碑

### Milestone A：能力证据合同

- 定义 `LLMCapabilityManifest` schema 与 validator；
- all-profile probe；
- required/optional 分类；
- provenance、freshness 与 manifest hash；
- 错误类型、trace ID、request ID 和内容最小化；
- 离线 contract smoke。

### Milestone B：运行时门禁与可观测

- Registry 暴露 configured/validated/enabled 能力视图；
- optional capability fail-closed；
- 管理员 capability API；
- deep health 语义收窄；
- manifest mismatch/stale/invalid smoke。

### Milestone C：评测与 Release Evidence v2

- real LLM business profile 扩展；
- capability manifest 纳入 release evidence；
- schema v1 只读兼容、v2 发布强制；
- image digest/model set/profile coverage 校验；
- evidence store/rollout gate/readiness smoke。

### Milestone D：真实环境闭环

- staging all-profile probe；
- offline/real LLM/production RAG 同 commit 证据；
- schema v2 evidence 持久化；
- staging >=100 terminal runs；
- production 1% canary >=100 terminal runs；
- 10%/48h 观察；
- secret 清理与回滚演练。

Milestone D 未完成时，本 Spec 不得标记 Complete。

---

## 13. 测试计划

### 13.1 Deterministic contract tests

至少新增：

- `llm_capability_manifest_smoke.py`；
- `llm_capability_manifest_provenance_smoke.py`；
- `llm_capability_gate_smoke.py`；
- `llm_capability_api_smoke.py`；
- `llm_release_evidence_v2_smoke.py`；
- `llm_profile_coverage_smoke.py`；
- `llm_fallback_capability_smoke.py`。

必须覆盖：

- hash tampering；
- stale/future timestamp；
- commit/image/config/environment mismatch；
- model/max tokens/fallback mismatch；
- required fail 与 optional fail 的不同语义；
- fallback-only success 不算主 profile pass；
- manifest 缺失时 optional capability fail-closed；
- v1 evidence 不能为 v1.45 rollout 产生 PASS；
- 管理员 API 不泄露 prompt/output/secret；
- deep health 不被解释成全能力通过。

### 13.2 Real-provider tests

- 全 profile required capability；
- applicable optional capability；
- 历史人物真实 RAG + LLM；
- 材料视觉；
- 真实 stream；
- 长结构化输出；
- 主模型失败与 fallback 行为；
- request ID/trace ID/latency/usage 观测。

### 13.3 Release gate

`make verify-release` 或 production release workflow 必须拒绝：

- manifest 缺失或失效；
- required profile 未覆盖；
- real business suite skip/not run；
- report/manifest/evidence commit 不一致；
- image/config/model mismatch；
- schema v1 evidence；
- staging/canary 样本不足；
- rollout gate unknown/fail。

---

## 14. 验收标准

### 14.1 代码验收

1. Manifest schema/validator/hash/freshness 合同完成；
2. 所有运行 profile 被直接探测或有可验证等价证明；
3. required/optional capability 语义正确；
4. optional capability 默认关闭且 fail-closed；
5. 管理员 capability API 受可信认证保护；
6. release evidence schema v2 能持久化并参与 rollout gate；
7. v1 evidence 只读兼容但不能证明 v1.45 rollout；
8. deterministic smoke、现有 core eval 和前端测试通过；
9. 无学生正文、图片 base64、secret 或 raw error body 泄露。

### 14.2 外部环境验收

1. 当前 clean deployed commit/image/config 的 all-profile probe 通过；
2. required real LLM business suites 全部运行且通过；
3. production RAG profile 通过；
4. schema v2 evidence 入库成功；
5. staging >=100 terminal runs 且 gate pass；
6. production 1% canary >=100 terminal runs 且 gate pass；
7. production 10% 连续 48 小时无 blocking condition；
8. 旧代理 secret 已删除并验证不会被运行时读取；
9. 回滚演练成功；
10. 最终实施报告包含实际 evidence hash、manifest hash、commit/config/image 和 canary 结果。

### 14.3 禁止的完成声明

以下状态不得标记为 Complete：

- `Code complete · Real-provider validation pending`；
- `Implementation complete · production NOT_RUN`；
- 只通过 synthetic probe；
- 只观察到一次 fast/quality LLM 调用；
- `history_character_eval` 或材料视觉仍为 skip；
- staging/production canary 未运行；
- evidence 与部署 provenance 不一致。

---

## 15. 风险与控制

| 风险 | 控制 |
| --- | --- |
| Probe 成本过高 | synthetic probe 每次部署运行；SLO 使用 canary 样本，不靠高频 probe |
| Provider 短时波动导致阻塞 | 区分 infra/quality failure，允许受控重试，但不让 fallback 证明主模型通过 |
| Manifest 被手工篡改 | canonical JSON + sha256 + 服务端 validator + evidence 再绑定 |
| 模型 alias 漂移 | 生产使用固定 snapshot；alias 变化视同模型变更 |
| 能力报告与部署错配 | 强制 commit/image/config/environment/model 比对 |
| 管理员接口泄露内容 | 只返回状态、hash、ID、指标和稳定错误码 |
| Optional capability 被误启用 | feature flag + manifest + allowlist 三重门禁 |
| 又一次停留在本地代码完成 | Definition of Ready 前置权限；Milestone D/Canary 写入 DoD |
| LangChain SDK 升级改变行为 | 依赖版本进入 manifest，升级后旧证据失效并重跑 |

---

## 16. 后续迭代建议

只有 v1.45 真实环境闭环后，才进入后续能力迭代：

1. **v1.46 Native Structured Output 纵向切片**：选择无外部副作用、非流式、可 shadow 对比的结构化任务；
2. **v1.47 低风险只读 Tool Calling**：模型只产生 Tool Call，执行必须经过 Runtime v2/Tool Registry；
3. **v1.48 LangGraph 持久化纵向切片**：只为确实需要跨请求 interrupt/resume 的 Agent 接入 PostgreSQL checkpointer；
4. **后续观测平台试点**：以 OTel/平台无关接口对比 Langfuse 与 LangSmith，不替换业务 Runtime evidence。

在 v1.45 前，不把框架覆盖率、Graph 数量或 LangSmith 接入视为当前主要完成度。

---

## 17. 最终完成定义

v1.45 完成意味着：

> 对当前部署的每个实际 LLM profile，项目能够证明“配置了什么、真实验证了什么、允许启用了什么”；这些证据与 commit、镜像、配置、环境和模型严格绑定，并已通过真实业务评测、staging 与 production canary。

如果只能证明代码合同正确，而不能提供真实 Provider、production RAG 和 canary 证据，本版本保持 `In Progress/Blocked`，不进入 Complete。
