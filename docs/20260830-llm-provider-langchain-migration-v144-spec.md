# EduAgent LLM 接入层去 Zode 与 LangChain 迁移 v1.44 Spec

**创建时间：** 2026-08-30

**状态：** Implemented · Real-provider validation pending（代码与离线回归完成；真实百炼能力、生产 canary 和部署 secret 清理由外部环境收口）

**目标版本：** v1.44.0（直连接入与兼容层）+ v1.44.1（能力验证与业务迁移）+ v1.44.2（删除 Zode 与生产收口）

**优先级：** P0 基础设施迁移；原生 Tool Calling / Structured Output 扩展为 P1，必须通过逐模型能力门禁后启用

**适用范围：** 后端所有文本、多模态、流式、结构化输出和评测 LLM 调用；不改变 Runtime v2、Tool Registry、RAG、Evidence Verifier 和产品 API 的职责边界

**前置基线：** `main@1c89bbd`，生成本文时工作区无未提交修改

**关联文档：**

- `docs/20260820-agent-runtime-v2-architecture-upgrade-v133-spec.md`
- `docs/202608280000-agent-runtime-langgraph-boundary-adr.md`
- `docs/202606082106-langfuse-tracing-dev.md`
- `docs/202606100200-langfuse-ragas-eval-dashboard-dev.md`
- `docs/202607141045-ai-agent-fullstack-coverage-report.md`

---

## 0. 决策摘要

当前 EduAgent 的生产证据与示例配置均以阿里云百炼为主，主要模型为：

| Profile | 当前模型 | 当前用途 | 迁移结论 |
| --- | --- | --- | --- |
| `fast` | `qwen3.6-35b-a3b` | 路由、抽取、总结、轻量生成 | 可迁移到百炼 OpenAI-compatible + `ChatOpenAI` |
| `quality` | `qwen3.7-plus` | RAG 回答、批改、复杂生成 | 可迁移；Tool Calling 需真实探测 |
| `fallback` | `qwen3.7-max-2026-06-08` | 文本模型降级 | 可迁移；保持显式 snapshot |
| `reasoning` | `qwen3.7-max-2026-06-08` | 推理任务 | 可迁移；thinking 参数和工具能力需单独探测 |
| `multimodal` | `qwen3.5-omni-flash` | OCR/图片理解 | 条件可迁移；必须验证图片消息和流式行为 |
| `multimodal_quality` | `qwen3.5-omni-plus` | 高质量图片理解 | 条件可迁移；必要时使用 `ChatTongyi` 专用 adapter |

本轮作出以下决策：

1. **删除 Zode 是确定目标。** 最终态不再调用 `zode.qa.qima-inc.com`，不再保留 `ZodeChatModel`、`zode_client.js`、Node 子进程或 Anthropic-compatible Zode fallback。
2. **百炼是 v1.44 唯一默认在线 Provider。** 使用 Python `langchain-openai` 的 `ChatOpenAI` 直连百炼 OpenAI-compatible endpoint；多模态如兼容探测失败，仅该 profile 切换为官方 `ChatTongyi` adapter。
3. **先迁移接入层，不借机重写全部 Agent。** 现有 `llm_fast / llm_quality / llm_reasoning / llm_multimodal` 名称和主要调用合同在兼容期保持稳定。
4. **不把 LangChain 变成新的治理平面。** LangChain 负责模型 client、消息、流式 chunk、tool binding 和结构化输出能力；Runtime v2 继续拥有权限、预算、幂等、完成判定、事件、灰度和审计。
5. **禁止隐式跨 Provider fallback。** v1.44 内只允许同一受控 Provider 内的显式 model fallback。未来新增其他 Provider 必须有独立 profile、真实凭证、能力报告和发布审批。
6. **原生 Tool Calling 与原生 Structured Output 不作为删除 Zode 的前置条件。** 第一阶段保留现有 prompt + `structured_output.py` 解析/修复链，先取得行为等价；高级能力按 profile 灰度。
7. **流式失败语义必须保持。** 首个 token 发出前可以切换 fallback；已经向用户发出 token 后不得拼接另一个模型的输出。
8. **Langfuse 继续作为线上 LLM/Agent 观测面。** 迁移后保留现有 trace ID、generation attempt、模型、fallback、耗时、输入输出脱敏和成本估算字段。

目标调用链：

```text
API / Agent / Runtime v2 / LangGraph
  → EduAgent LLM Profile Registry
  → ManagedChatModel（兼容、重试、fallback、trace、错误归一化）
  → ChatOpenAI（文本主路径）/ ChatTongyi（仅必要的多模态路径）
  → DashScope / Model Studio
```

最终必须删除的调用链：

```text
Python
  → subprocess.run / subprocess.Popen
  → node backend/zode_client.js
  → DashScope 或 zode.qa.qima-inc.com
```

---

## 1. 当前项目实际基线

### 1.1 当前传输层

`backend/llm_config.py` 定义普通 Python 类 `ZodeChatModel`，并非 LangChain `BaseChatModel`。它负责：

- 把字符串或 `list[dict]` 消息转换为自定义 payload；
- 用 `subprocess.run()` 完成非流式调用；
- 用 `subprocess.Popen()` 完成流式调用；
- 调用 `backend/zode_client.js` 发起 HTTPS 请求；
- 对同一 profile 进行 retry、model fallback 和可选跨 Provider fallback；
- 创建 Langfuse generation；
- 返回自定义 `LLMResponse(content: str)`；
- 流式接口直接产生 `Iterator[str]`。

`backend/zode_client.js` 内部存在两条路径：

1. `LLM_PROVIDER=bailian|dashscope`：直接请求 `${BAILIAN_BASE_URL}/chat/completions`；
2. 其他 Provider：按 Anthropic 协议请求 `ANTHROPIC_BASE_URL`，默认地址为 Zode 代理。

因此当前百炼流量虽然不经过 Zode 在线代理，仍依赖以 Zode 命名的 Node 桥接层。后端生产镜像安装 Node.js 的明确用途也是运行该脚本。

### 1.2 当前配置存在的风险

| 风险 | 当前事实 | 迁移要求 |
| --- | --- | --- |
| 默认 Provider 不一致 | `.env.example` 和真实 LLM CI 使用 `bailian`，代码缺省值却是 `anthropic` | 代码默认值改为 `bailian`，未知 Provider 启动失败 |
| 隐式 Zode fallback | 百炼凭证存在时仍可因 `ANTHROPIC_AUTH_TOKEN` 追加 Zode fallback | 删除跨 Provider fallback 和全部 Zode 环境变量 |
| 模型名与 Provider 混杂 | Anthropic-compatible 分支默认包含 Kimi、GLM、GPT 模型名 | 删除该异构代理模型链，不把它映射到 `ChatAnthropic` |
| 子进程错误不透明 | HTTP 状态、request ID、usage 被 Node stdout/stderr 压平 | 由 Python SDK 保留异常类别、usage 和 response metadata |
| 流式合同非标准 | 当前 `stream()` 产生字符串，LangChain 产生 `AIMessageChunk` | 兼容层保持旧合同，原生接口使用标准 chunk |
| Timeout 不统一 | 非流式固定 60 秒；流式只对进程 wait 设置 10 秒 | profile 显式声明连接/读取/总超时和 Runtime wall-time 上限 |
| 依赖未封口 | 有 `langchain-core`/`langgraph`，没有 `langchain-openai` | 加依赖并在兼容矩阵验证后写入 constraints |

### 1.3 当前模型实例

`backend/llm_config.py` 暴露：

- `llm_fast`：1024 max tokens；fallback 到 `MODEL_FALLBACK`；
- `llm_quality`：2048 max tokens；依次 fallback 到 fast、fallback；
- `llm_reasoning`：2048 max tokens；依次 fallback 到 quality、fast；
- `llm_multimodal`：4096 max tokens；无 fallback；
- `llm_multimodal_quality`：4096 max tokens；无 fallback；
- `llm_material`：材料处理专用 4096 max tokens；
- `llm_card_pool`：多人卡池专用 3072 max tokens。

后两个实例由业务模块直接实例化 `ZodeChatModel`，说明当前 profile 创建仍未完全收口到统一工厂。

### 1.4 当前调用面

代码盘点确认以下调用合同必须保持或显式迁移：

| 调用类型 | 代表模块 | 当前合同 | 迁移影响 |
| --- | --- | --- | --- |
| 普通文本 | 学习助手、教师、记忆、周报 | `.invoke(...).content` | LangChain `AIMessage.content` 基本兼容 |
| 自定义重试参数 | `materials/service.py` | `.invoke(messages, max_retries=1)` | 不能直接传给原生 `ChatOpenAI.invoke` |
| 字符串流 | 教材问答/摘要、历史人物、历史地图 | `for chunk in llm.stream(): chunk` 为字符串 | 原生 chunk 需读取 `.content` |
| 结构化输出 | 作业批改、卡牌、路由、AutoTutor | `invoke_structured()` + Pydantic + repair | 第一阶段保留 |
| 多模态 | 材料上传/OCR | OpenAI 风格 `image_url` content block | 必须真实探测 |
| 属性读取 | 学习助手、trace event | `.name/.model/.fallback_models` | 兼容层必须保留 |
| 测试替身 | 多个 eval/smoke | monkeypatch `.invoke` 或整体替换模型 | 测试注入接口必须保留 |

### 1.5 不在统一模型入口内的遗留调用

`scripts/generate_textbook_yaml.py` 直接以 `ANTHROPIC_BASE_URL` 和 Zode 默认地址发起请求。它必须纳入删除清单，不能因为不在在线后端中而保留 Zode。

以下说明性文档仍包含 Zode 架构描述，需要在迁移完成后标注历史状态或更新：

- `CLAUDE.md`
- `SCHEMA.md`
- `docs/202606100239-eduagent-dev-guide.md`
- `docs/202606180248-project-overview-dev.md`
- `docs/202606082106-langfuse-tracing-dev.md`

历史需求文档可以保留当时决策，但必须增加“已由 v1.44 替代”的说明，避免被误当作现行接入指南。

### 1.6 依赖基线

当前运行依赖已有：

- `langchain-core>=0.3.0`
- `langchain-anthropic>=0.3.0`
- `langgraph>=1.2.6,<1.3.0`
- `langfuse>=2.0.0`

但没有 `langchain-openai`。`constraints-runtime.txt` 当前锁定 `langgraph==1.2.11` 和 `langsmith==0.11.2`，未锁定 LangChain Provider package。实施前必须通过一次干净环境 resolver 和 smoke，不应仅向 requirements 添加无上界依赖。

---

## 2. 目标与非目标

### 2.1 工程目标

1. 后端所有在线 LLM 请求由 Python provider client 直接发起。
2. 删除 Zode 在线代理、Node helper、Python 子进程和镜像 Node.js 依赖。
3. 建立按用途而非按具体模型命名的 LLM Profile Registry。
4. 保持现有文本输出、流式顺序、fallback、Langfuse 和降级语义等价。
5. 给 LangGraph 提供原生 LangChain `BaseChatModel`，支持后续 `bind_tools()`、标准消息和 graph streaming。
6. 为每个模型形成可机器读取的能力报告，不凭模型系列名称假定能力。
7. 模型、Provider、endpoint、timeout、retry 和 fallback 均可审计、可灰度、可回滚。
8. 真实 LLM eval 能记录 provider、model snapshot、参数、commit、配置版本和 Langfuse trace ID。

### 2.2 产品目标

1. 学生端和教师端现有 API schema、SSE event 名称与最终内容字段不变化。
2. 迁移期间不降低历史问答、教材问答、批改、出题和材料理解的成功率。
3. 模型不可用时继续按既有业务策略返回 fallback/degraded，而不是暴露 SDK 错误。
4. 线上能够从 Langfuse 按 release/profile/model/agent 定位一次失败调用及其 fallback 链。

### 2.3 非目标

- 不在本 Spec 中把所有 Agent 改写成 LangGraph。
- 不替换 Runtime v2 的 Run/Event/Artifact、预算、权限、幂等和完成判定。
- 不允许 LangChain Agent 绕过 Tool Registry 直接执行工具。
- 不开放任意 ReAct、无限循环或模型生成任意工具名。
- 不把原生 structured output 当作唯一 JSON 保障。
- 不在生产请求中同时调用 Zode 和百炼做双写/双生成。
- 不自动启用新的模型 alias；生产与 eval 继续优先使用明确 snapshot。
- 不在缺少对应 Provider 真实凭证时保留“看起来可用”的 fallback 配置。

---

## 3. 设计原则

1. **Profile 先于模型名。** 业务依赖 `fast/quality/reasoning/multimodal` 能力，不直接决定 Provider endpoint。
2. **原生能力和兼容能力分层。** 旧业务通过兼容 facade；新 LangGraph 节点获取标准 `BaseChatModel`。
3. **单一配置源。** profile、模型、参数和 fallback 在一个 registry 定义，业务模块不得直接 new Provider client。
4. **失败默认封闭。** 凭证缺失、未知 Provider、模型不支持图片/工具或 schema 校验失败都必须显式失败或进入既有 degraded 路径。
5. **流式不混模。** 已 emit 后失败即终止当前生成，不再 fallback。
6. **重试和 fallback 可观测。** 每个 attempt 都是独立 generation，并共享一个业务 trace。
7. **观测不影响业务。** Langfuse 初始化、发送和 flush 失败不得使模型调用失败。
8. **敏感信息最小化。** API key、完整图片 data URL、学生私密文本和原始异常 body 不进入日志。
9. **能力由探测证明。** chat 成功不代表 tool calling、structured output、vision 和 streaming 均成功。
10. **删除是完成标准。** “新路径可用但旧 Zode 仍长期存在”不算迁移完成。

---

## 4. 目标架构

### 4.1 模块边界

建议新增内部 package：

```text
backend/llm/
  __init__.py
  contracts.py          # profile、能力、错误和 attempt 合同
  registry.py           # 配置解析、profile 定义、启动校验
  providers.py          # ChatOpenAI / ChatTongyi client factory
  managed_model.py      # retry、fallback、trace、兼容 invoke/stream
  capability_probe.py   # 显式真实模型能力探测

backend/llm_config.py   # 迁移期兼容 facade，只导出既有常量和实例
```

职责划分：

| 层 | 拥有的职责 | 不拥有的职责 |
| --- | --- | --- |
| Provider client | HTTP、SDK 消息、标准 stream、usage/response metadata | 产品 fallback、权限、业务完成判定 |
| Managed model | profile、retry、model fallback、trace、错误归一化 | Agent 规划、工具权限、RAG 证据 |
| Runtime v2 | 预算、run 状态、事件、幂等、rollout、completion | Provider HTTP 和模型协议 |
| LangGraph | 节点、分支、图 stream、checkpoint | 业务权限和 provider 配置 |
| Tool Registry | allowlist、schema、actor、确认、审计 | 模型选择和 graph 调度 |

### 4.2 Profile 合同

建议使用不可变配置对象：

```python
@dataclass(frozen=True)
class LLMProfile:
    name: str
    provider: Literal["bailian_openai", "bailian_tongyi"]
    model: str
    max_tokens: int
    timeout_seconds: float
    max_retries: int
    fallback_profiles: tuple[str, ...]
    capabilities: frozenset[str]
```

强制规则：

- fallback 引用 profile 名称，不在业务模块手写模型名；
- registry 启动时检测循环 fallback、重复 profile、空模型名和未知 Provider；
- 多模态 profile 不 fallback 到文本 profile；
- reasoning profile 是否允许 fallback 到非 reasoning 模型必须显式配置；
- `model`、`name`、`fallback_models` 在兼容 facade 上继续可读；
- profile 配置进入 Langfuse metadata 和 release evidence。

### 4.3 Provider Factory

文本主路径：

```python
ChatOpenAI(
    model=profile.model,
    api_key=BAILIAN_API_KEY,
    base_url=BAILIAN_BASE_URL,
    max_tokens=profile.max_tokens,
    timeout=profile.timeout_seconds,
    max_retries=0,
)
```

`max_retries=0` 的目的，是由 Managed model 统一控制 retry、fallback 和 attempt tracing，避免 SDK 内部不可见重试与外层重试叠加。若最终选择 SDK 内部重试，必须能够从 callback/response metadata 观察每次 attempt，否则不得启用。

Provider Factory 必须：

- 复用连接池/client，而不是每次 invoke 新建；
- 只从环境或 secret store 获取 key；
- 不记录 key 或完整 Authorization header；
- 保留 provider request ID、token usage、finish reason；
- 支持测试注入 fake client；
- 明确设置 timeout，不依赖 SDK 隐式默认值；
- 对百炼非标准参数只通过受控 `extra_body` allowlist 传入。

### 4.4 兼容 facade 与原生接口

迁移期保留：

```python
from llm_config import llm_fast, llm_quality
```

`ManagedChatModel` 对现有业务提供：

```python
invoke(messages, max_retries: int | None = None) -> AIMessage
stream_text(messages) -> Iterator[str]
as_langchain() -> BaseChatModel
```

兼容期可暂时保留 `stream()` 返回字符串，但新代码不得继续依赖该行为。业务迁移完成后：

- 原生 LangChain 代码使用 `as_langchain().invoke/stream/bind_tools`；
- SSE 业务统一调用 `stream_text()`；
- 不通过覆写标准 `BaseChatModel.stream()` 来返回字符串，避免破坏 LangChain 合同。

### 4.5 消息归一化

支持输入：

- 单个字符串；
- 现有 `list[{role, content}]`；
- LangChain `BaseMessage` 列表；
- OpenAI 风格多模态 content block。

规则：

- 文本消息转换为 `SystemMessage/HumanMessage/AIMessage`；
- 未知 role、空消息、非法 content block 在调用 Provider 前失败；
- tool message 仅允许在 capability probe 通过且调用来自 Tool Registry adapter 时使用；
- 图片 data URL 只传给声明 vision 能力的 profile；
- Langfuse sanitation 必须在消息归一化后仍能删除图片 base64。

### 4.6 Retry、fallback 和流式语义

非流式：

```text
profile model
  → 同模型最多 N 次受控 retry
  → 空输出视为失败，不重复同模型
  → 按配置切换同 Provider fallback profile
  → 全部失败后抛出归一化 LLMUnavailableError
```

流式：

```text
开始 attempt
  ├─ 首 token 前失败 → 允许 fallback
  ├─ 已 emit 后失败 → 记录 partial，立即失败，不 fallback
  └─ 正常结束 → 输出 usage/finish reason/完整拼接长度
```

不得在业务代码和 Managed model 同时进行同一层重试。Runtime 的任务级 retry 与模型 attempt retry 要使用不同 metadata：

- `run_attempt`
- `model_attempt`
- `model_retry`

### 4.7 错误合同

至少归一化为：

| 错误 | 可重试 | 可 fallback | 对外行为 |
| --- | --- | --- | --- |
| `LLMConfigurationError` | 否 | 否 | readiness 失败，启动/发布阻断 |
| `LLMAuthenticationError` | 否 | 否 | 不暴露 Provider body |
| `LLMRateLimitError` | 是 | 是 | 指数退避，受 wall-time 限制 |
| `LLMTimeoutError` | 是 | 是（首 token 前） | 进入既有 degraded/fallback |
| `LLMProviderError` | 视状态码 | 是（首 token 前） | 记录 request ID |
| `LLMEmptyResponseError` | 否 | 是 | 切换模型 |
| `LLMCapabilityError` | 否 | 否 | 禁止调用未验证能力 |
| `LLMStreamInterruptedError` | 否 | 否（已 emit） | SSE 明确失败/降级，不拼接模型 |

原始 SDK 异常不得穿透到前端 API。

---

## 5. 配置与密钥规范

### 5.1 v1.44 目标环境变量

保留并规范：

```bash
LLM_PROVIDER=bailian
BAILIAN_API_KEY=<secret>
BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

LLM_MODEL_FAST=qwen3.6-35b-a3b
LLM_MODEL_QUALITY=qwen3.7-plus
LLM_MODEL_FALLBACK=qwen3.7-max-2026-06-08
LLM_MODEL_REASONING=qwen3.7-max-2026-06-08
LLM_MODEL_MULTIMODAL=qwen3.5-omni-flash
LLM_MODEL_MULTIMODAL_QUALITY=qwen3.5-omni-plus

LLM_REQUEST_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2
EDU_AGENT_LLM_DISABLED=false
```

兼容别名 `DASHSCOPE_API_KEY` 可以保留一个版本，但部署规范只写 `BAILIAN_API_KEY`，避免双 key 来源不清。

### 5.2 必须删除的环境变量

v1.44.2 后删除：

```bash
ANTHROPIC_AUTH_TOKEN
ANTHROPIC_API_KEY        # 仅指当前 Zode 路径；未来真实 Anthropic Provider 需重新设计
ANTHROPIC_BASE_URL
ANTHROPIC_MODEL_FAST
ANTHROPIC_MODEL_QUALITY
ANTHROPIC_MODEL_FALLBACK
ANTHROPIC_MODEL_REASONING
```

生产 secret store、CI secret、部署平台变量和本地示例必须同步清理。代码不得因为存在旧变量而改变 fallback 链。

### 5.3 启动校验

生产启动或 readiness 必须校验：

- `LLM_PROVIDER` 仅允许已注册值；
- provider key 存在；
- endpoint 为 HTTPS，除明确 local-test 配置外不得使用 HTTP；
- endpoint host 在 allowlist；
- 所有启用 profile 均有模型；
- fallback graph 无环；
- profile 所需能力已在当前 release 的 capability report 中通过。

浅健康检查只验证配置；深健康检查真实调用 Provider，并返回：

```json
{
  "ok": true,
  "provider": "bailian",
  "transport": "langchain_openai",
  "profiles": {
    "fast": {"model": "qwen3.6-35b-a3b", "status": "ok"}
  }
}
```

不得返回 key、完整 endpoint query 或 Provider 原始错误 body。

---

## 6. 模型能力矩阵与验证门禁

### 6.1 必测能力

每个 profile 需要生成机器可读报告：

| 能力 | fast | quality | reasoning | multimodal |
| --- | --- | --- | --- | --- |
| 普通 invoke | 必须 | 必须 | 必须 | 必须 |
| system message | 必须 | 必须 | 必须 | 必须 |
| 中文输出 | 必须 | 必须 | 必须 | 必须 |
| stream | 必须 | 必须 | 按使用场景 | 按使用场景 |
| usage metadata | 尽量 | 尽量 | 尽量 | 尽量 |
| JSON prompt 输出 | 必须 | 必须 | 必须 | 按场景 |
| Pydantic parse | 必须 | 必须 | 必须 | 按场景 |
| native structured output | 探测 | 探测 | 探测 | 探测 |
| `bind_tools` | 探测 | 必须后才可进入 Agent | 必须后才可进入 Agent | 非首期 |
| tool result round-trip | 探测 | 必须后才可进入 Agent | 必须后才可进入 Agent | 非首期 |
| 图片 URL | 不适用 | 视模型 | 视模型 | 必须 |
| 图片 base64 | 不适用 | 视模型 | 视模型 | 必须 |
| timeout/retry | 必须 | 必须 | 必须 | 必须 |
| fallback before emit | 必须 | 必须 | 按使用场景 | 不允许跨文本 profile |
| failure after emit | 必须 | 必须 | 按使用场景 | 按使用场景 |
| Langfuse generation | 必须 | 必须 | 必须 | 必须 |

报告至少记录：

```json
{
  "commit": "1c89bbd",
  "provider": "bailian",
  "profile": "quality",
  "model": "qwen3.7-plus",
  "base_url_host": "dashscope.aliyuncs.com",
  "tested_at": "2026-08-30T00:00:00Z",
  "capabilities": {},
  "latency_ms": {},
  "trace_ids": [],
  "result": "pass"
}
```

报告不得包含 key、完整学生输入或图片 base64。

### 6.2 能力启用规则

- `chat + stream` 通过即可进入 v1.44.0 接入层 canary；
- `vision` 通过后才能迁移材料上传；
- `bind_tools + tool result round-trip` 均通过后，才能让某个 LangGraph 节点使用模型原生 tool calling；
- native structured output 未通过时，继续使用 `invoke_structured()`；
- thinking 模式和 non-thinking 模式视为两个不同 capability variant；
- model alias 发生变化后能力报告失效，必须重跑；固定 snapshot 仅在 Provider 宣布行为变化或 SDK 变化时重跑。

### 6.3 多模态决策门

多模态按以下顺序决策：

1. `ChatOpenAI` + 百炼 OpenAI-compatible 能正确完成 URL/base64 图片理解：继续统一使用 `ChatOpenAI`；
2. 文本正常但 Omni 消息或响应不兼容：仅多模态 profile 使用 `ChatTongyi`；
3. 两者都未通过：阻断 Zode 文件删除，不允许静默退化为 OCR 假成功；可以先保留确定性 OCR fallback，但产品必须标记 degraded。

---

## 7. Structured Output 与 Tool Calling 迁移

### 7.1 第一阶段：保持现有结构化输出

保留 `backend/structured_output.py`：

```text
LLM 文本输出
  → 提取 JSON
  → Pydantic 校验
  → 一次受限格式修复
  → 确定性 fallback / 失败
```

原因：当前多个业务合同依赖自定义 repair 和 fallback；百炼不同模型/模式的原生 structured output 能力不能统一假设。

迁移接入层时必须验证：

- `AIMessage.content` 为字符串时行为等价；
- content block 返回时能被显式归一化，不能直接 `str(list)` 后解析；
- repair 调用也经过同一 Managed model 和 trace；
- schema 验证失败仍 fail-closed。

### 7.2 第二阶段：选择性启用原生 Structured Output

只对 capability report 通过的 profile/模型开放：

```python
managed.as_langchain().with_structured_output(MySchema)
```

启用必须由 feature flag/profile capability 控制，并保留旧解析器作对照与紧急降级。只有真实 eval 证明原生路径在 schema 成功率、延迟和成本上不劣于旧路径，才允许成为默认。

### 7.3 Tool Calling 边界

模型原生工具调用只负责“提出结构化工具请求”，不能直接执行工具：

```text
LLM tool call
  → LangGraph node
  → Runtime v2 policy/budget
  → Tool Registry allowlist/schema/actor/confirmation
  → Tool result
  → LangGraph
```

禁止：

- 将任意 Python 函数直接传给 `bind_tools()`；
- 绕过 actor、data scope、风险等级、确认和审计；
- 模型自行构造数据库、shell、HTTP 或文件工具；
- 因迁移 Provider 而扩大 Agent 的工具权限。

---

## 8. Langfuse 与在线观测要求

### 8.1 Generation metadata

每个 Provider attempt 至少记录：

- `provider`
- `transport=langchain_openai|langchain_tongyi`
- `llm_name/profile`
- `configured_model`
- `attempt_model`
- `model_attempt`
- `model_retry`
- `fallback_profiles`
- `max_tokens`
- `stream`
- `operation`
- `latency_ms`
- `output_chars`
- `chunk_count`
- `emitted`
- `partial_output`
- `finish_reason`
- `provider_request_id`（可获得时）
- token usage 和 cost estimate（可获得时）
- `deployed_commit`
- `runtime_config_version`
- `trace_id/run_id/agent_name`（上下文存在时）

### 8.2 Trace 兼容

- 继续复用 `backend/tracing.py` 的 sanitation、no-op 降级和 context trace；
- 不同时启用两套自动 tracing，避免一个调用生成重复 generation；
- 若 LangChain callback 与手写 generation 并存，必须明确父子关系并做去重；
- v1.44.0 优先保留现有手写 attempt generation，待字段 parity 后再评估 LangChain callback；
- Langfuse 不可用不得影响业务，但 readiness/AgentOps 应显示 `observability_degraded`。

### 8.3 隐私要求

- 延续 `LANGFUSE_CAPTURE_INPUT/OUTPUT` 开关；
- 图片 base64 永不进入 trace；
- 生产可关闭正文 capture，仅保留长度、hash、schema、来源 ID 和业务 metadata；
- Provider 原始异常先经过 `safe_error_message()` 和敏感字段清理；
- capability probe 使用合成输入，不使用真实学生数据。

---

## 9. 文件级改动清单

### 9.1 新增

| 文件 | 目的 |
| --- | --- |
| `backend/llm/contracts.py` | profile、capability、错误合同 |
| `backend/llm/registry.py` | profile 配置、启动校验、统一实例缓存 |
| `backend/llm/providers.py` | `ChatOpenAI/ChatTongyi` 工厂 |
| `backend/llm/managed_model.py` | 兼容、retry、fallback、trace、文本流 |
| `backend/llm/capability_probe.py` | 真实模型能力探测入口 |
| `eval/llm_provider_contract_smoke.py` | 无真实凭证的合同 smoke |
| `eval/llm_provider_live_probe.py` | 显式 opt-in 的真实 Provider probe |

### 9.2 修改

| 文件/区域 | 必要修改 |
| --- | --- |
| `backend/llm_config.py` | 变为兼容 facade；默认 Provider 改为 Bailian；删除 subprocess 和 Zode 模型类 |
| `backend/requirements-runtime.txt` | 增加 `langchain-openai`；按 resolver 结果处理不再需要的 Anthropic 依赖 |
| `constraints-runtime.txt` | 锁定验证通过的 Provider package 及关键传递依赖 |
| `backend/tracing.py` | 接收 provider response metadata、usage、request ID；保持 no-op |
| `backend/api/routers/debug.py` | health 返回 transport/profile capability，不暴露 secret |
| `backend/textbook_learning/service.py` | 使用 `stream_text()` 或标准 chunk `.content` |
| `backend/agents/history_character.py` | 同上，并验证 LangGraph custom stream parity |
| `backend/agents/history_map_agent.py` | 同上 |
| `backend/materials/service.py` | 从 registry 获取 `material` profile；删除 `ZodeChatModel` 与调用级非标准 retry 耦合 |
| `backend/agents/multiplayer_card_generator.py` | 从 registry 获取 `card_pool` profile |
| `scripts/generate_textbook_yaml.py` | 改为百炼直连/复用受控 CLI client；删除 Zode 默认 URL |
| `.env.example` | 删除 Anthropic/Zode 示例，补充 timeout/transport 配置 |
| `.github/workflows/*.yml` | 增加 provider contract smoke；真实 probe 继续使用 `BAILIAN_API_KEY` |
| `backend/Dockerfile` | 最终删除 Node.js 安装和 Zode 注释 |
| `CLAUDE.md` / `SCHEMA.md` / 现行开发指南 | 更新当前架构描述 |

### 9.3 删除

v1.44.2 必须删除：

- `backend/zode_client.js`
- `ZodeChatModel`
- `LLMResponse`（所有调用已使用标准 `AIMessage` 后）
- 所有 Zode endpoint 和 Zode credential 配置
- 后端镜像的 Node.js runtime
- 生产代码内 Anthropic-compatible 异构代理 fallback

`anthropic` / `langchain-anthropic` 依赖是否删除，以代码搜索和 eval 需求为准：

- 在线 runtime 不再使用时，应从 `requirements-runtime.txt` 删除；
- `eval/ragas_eval.py` 若仍需真实 Anthropic judge，应迁移到明确独立的 eval extra，不得使生产 runtime 重新依赖 Zode；
- 没有真实 Anthropic endpoint/key 时，RAGAS judge 也应改用已验证的百炼模型或标记 skip。

---

## 10. 实施里程碑

### Milestone 0：冻结基线与建立证据

目标：证明迁移前实际行为，而不是只证明代码可导入。

工作项：

1. 记录当前 commit、镜像 digest、模型 profile、endpoint host 和配置版本。
2. 在不泄露 secret 的前提下运行 `/api/debug/llm/health?deep=true`。
3. 生成 invoke、stream、structured、multimodal、fallback 的迁移前样本。
4. 运行当前 core eval、相关 smoke 和至少一组真实 LLM eval。
5. 记录 p50/p95 延迟、首 token 延迟、成功率、空输出率、schema 成功率、fallback 率和估算成本。
6. 建立合成 capability probe 数据，不使用学生正文。

退出标准：基线报告可定位到 commit/config/model/trace；没有基线不得开始生产切换。

### Milestone 1：引入百炼 Python 直连和兼容层

目标：替换传输实现，不改变 Agent 行为。

工作项：

1. 增加并约束 `langchain-openai`。
2. 实现 registry、Provider Factory 和 Managed model。
3. `llm_config.py` 继续导出既有 profile 名称。
4. 保持 `.invoke().content`、属性读取、retry/fallback 和 Langfuse attempt 语义。
5. 为现有字符串 stream 提供 `stream_text()`。
6. 增加 `EDU_AGENT_LLM_TRANSPORT=legacy_zode|langchain_openai` 临时迁移开关，仅用于测试环境和短期 canary。
7. 生产新部署默认 `langchain_openai`；未知值 fail-fast。

退出标准：离线合同 smoke 全过；文本真实 probe 全过；Langfuse 能看到新 transport。

约束：临时 `legacy_zode` 开关必须在 v1.44.2 删除，不能成为永久 fallback。

### Milestone 2：迁移业务调用面

目标：所有在线业务使用统一 registry，不直接实例化旧模型类。

顺序：

1. `llm_fast` 普通 invoke 低风险链路；
2. `llm_quality` 结构化输出链路；
3. 教材摘要/问答、历史地图等流式链路；
4. 历史人物 LangGraph 流式链路；
5. `llm_material` 和 `llm_card_pool` 专用 profile；
6. 多模态材料处理；
7. 离线脚本和 eval judge。

每条链路必须比较：

- 输出 schema；
- SSE event 顺序；
- fallback/degraded 状态；
- trace/generation；
- timeout 和取消；
- 延迟和成本。

退出标准：生产代码不再 import/实例化 `ZodeChatModel`；所有流式链路不依赖“标准 `.stream()` 返回字符串”的非标准假设。

### Milestone 3：高级能力选择性启用

目标：让已验证 LangGraph 节点使用标准 LangChain 能力，但不扩大权限。

工作项：

1. 对 quality/reasoning profile 验证 `bind_tools()` 和 tool result round-trip。
2. 构建 Tool Registry → LangChain tool schema adapter。
3. 选择一个只读、低风险 Agent 做 canary，不直接迁移写工具。
4. 对结构化输出成功率高的 schema 做 shadow/offline 对比。
5. 保持 Runtime v2 的预算、确认、审计和完成门控。

退出标准：真实 LLM 和 canary 证据达标；失败可按 profile/能力 flag 关闭，不影响普通 invoke。

说明：Milestone 3 不阻塞 Zode 删除。如果高级能力未达标，继续沿用现有受控 Agent 和结构化解析。

### Milestone 4：删除 Zode 并生产收口

目标：仓库、镜像、配置和运行环境中不存在 Zode 依赖。

工作项：

1. 删除 `backend/zode_client.js`、`ZodeChatModel` 和临时 transport flag。
2. 删除后端 Dockerfile 的 Node.js 安装。
3. 删除 Zode/Anthropic proxy 环境变量和 secret。
4. 更新健康检查、CLAUDE/SCHEMA/开发指南。
5. 全仓搜索 `zode|Zode|zode.qa.qima-inc.com`，执行代码和现行配置结果必须为零。
6. 构建全新镜像，验证无 Node 仍能通过完整 LLM/eval/readiness。
7. 生成迁移 closure report。

退出标准：见第 13 节 Definition of Done。

---

## 11. 测试策略

### 11.1 单元测试

必须覆盖：

- 字符串、dict 消息和 LangChain message 归一化；
- system/user/assistant 顺序；
- 多模态 content block 校验；
- profile fallback 去重和循环检测；
- 凭证缺失、401、429、5xx、timeout、空输出错误映射；
- retry 次数和指数退避；
- 首 token 前 fallback；
- 已 emit 后失败不 fallback；
- generator 被客户端提前关闭时记录 partial；
- Langfuse disabled/init failed/send failed 不影响调用；
- input/output capture 关闭；
- 图片 base64 脱敏；
- `.name/.model/.fallback_models` 兼容；
- fake model 注入和现有 monkeypatch 模式。

### 11.2 合同测试

使用 fake Provider，不需要网络和 key：

```bash
PYTHONPATH=backend python eval/llm_provider_contract_smoke.py
```

验证：

- `.invoke().content`；
- `stream_text()`；
- fallback 序列；
- structured output repair；
- Langfuse generation metadata；
- debug health schema；
- `EDU_AGENT_LLM_DISABLED` 确定性禁用。

### 11.3 真实 Provider probe

必须显式 opt-in：

```bash
EDU_AGENT_REAL_LLM=1 \
LLM_PROVIDER=bailian \
PYTHONPATH=backend \
python eval/llm_provider_live_probe.py
```

真实 probe 不在 fork PR 的默认 CI 执行；只在受保护环境读取 `BAILIAN_API_KEY`，输出脱敏报告 artifact。

### 11.4 回归范围

至少运行：

- core eval；
- learning assistant multi-turn / semantic router；
- history character runtime / stream parity；
- textbook quiz / textbook learning；
- homework grading / essay grader；
- material multimodal；
- timeline/card/multiplayer generation；
- Langfuse tracing smoke；
- Runtime v2 adapter 和 rollout smoke。

### 11.5 构建验证

- 使用 constraints 从干净 Python 环境安装成功；
- 后端镜像构建成功；
- 最终镜像内不要求 `node`；
- shallow/deep readiness 均通过；
- 服务关闭能安全 flush Langfuse；
- 依赖扫描中没有仅由 Zode 路径遗留的 runtime package。

---

## 12. 灰度、指标与回滚

### 12.1 灰度顺序

```text
本地 fake contract
  → 受保护环境 live probe
  → staging 全链路
  → production 5%
  → 25%
  → 50%
  → 100%
  → 删除 legacy transport
```

按稳定 bucket 和 agent/profile 独立灰度，不按每次请求随机切换。多模态单独灰度，不与文本主路径绑定放量。

### 12.2 关键指标

| 指标 | 发布门槛 |
| --- | --- |
| LLM request success rate | 不低于基线 0.5 个百分点以上 |
| 空输出率 | 不高于基线，且绝对值 ≤ 0.5% |
| 结构化输出最终成功率 | 不低于基线 |
| stream interrupted rate | 不高于基线，且不得出现混模文本 |
| p95 总延迟 | 相比基线回退不超过 10%，超出需书面接受 |
| p95 首 token 延迟 | 相比基线回退不超过 15% |
| fallback rate | 无异常跃升；跃升必须能归因 |
| 单请求估算成本 | 相同 eval 集回退不超过 10% |
| Langfuse generation coverage | 启用观测的网关 attempt 为 100% |
| schema/API/SSE parity | 100% |
| 权限/工具审计 parity | 100% |

教学内容质量仍由现有 blind/real LLM/RAG eval 门禁判断，不能只以接口成功率替代。

### 12.3 Kill switch

保留：

- `EDU_AGENT_LLM_DISABLED`：确定性环境禁用真实调用；
- profile/model override：在百炼内部切换经验证 snapshot；
- Agent 既有 fallback/degraded flag；
- Tool Calling / native structured output 独立能力 flag。

临时 `legacy_zode` transport flag 只存在于迁移窗口。v1.44.2 后的故障回滚顺序：

1. 关闭高级能力，回到普通文本 + 现有解析器；
2. 切换到同 Provider 已验证 fallback model；
3. 降级业务能力或暂停真实 LLM；
4. 回滚到最近一个已验证的无 Zode 镜像。

最终态不以恢复 Zode proxy 作为常规回滚方案。

---

## 13. Definition of Done

只有同时满足以下条件，才能宣布 LLM 迁移完成：

### 13.1 代码与依赖

- [x] 所有在线 LLM 请求通过统一 registry/Managed model。
- [x] 生产代码无 `ZodeChatModel` import 或实例化。
- [x] 删除 `backend/zode_client.js`。
- [x] `backend/llm_config.py` 不再 import `subprocess` 或调用 Node。
- [x] `scripts/generate_textbook_yaml.py` 不再含 Zode endpoint。
- [x] 后端 Dockerfile 不安装 Node.js。
- [x] runtime requirements 不包含只服务于旧 Zode 路径的依赖。
- [ ] `langchain-openai` 和关键兼容依赖进入可复现 constraints/image seal。

### 13.2 配置与安全

- [x] 默认 Provider 为 Bailian，未知 Provider fail-fast。
- [ ] 删除 Zode endpoint、token 和部署 secret。
- [x] 不存在隐式跨 Provider fallback。
- [x] 日志、trace、probe artifact 不包含 key 或图片 base64。
- [x] readiness 能报告 provider/transport/profile 能力状态。

### 13.3 行为与质量

- [x] 普通 invoke、字符串流、多模态、structured output 行为通过合同测试。
- [x] 所有现有 Agent/API/SSE 离线回归通过。
- [ ] 每个启用模型有当前 release 的 capability report。
- [ ] 真实 LLM eval、production canary 和 Langfuse trace 证据达标。
- [x] 已 emit 后失败不发生跨模型拼接。
- [x] Runtime v2、Tool Registry、Evidence Verifier 权限与完成语义未被绕过。

### 13.4 文档与运营

- [x] `.env.example`、CLAUDE、SCHEMA 和现行开发指南已更新。
- [x] 历史 Zode 文档标记为 superseded，不再作为当前操作指南。
- [ ] 有迁移 closure report，记录 commit、镜像、模型、配置、测试、canary 和残余风险。
- [x] 有无 Zode 的故障处理和模型切换 runbook。

最终扫描建议：

```bash
rg -n "zode|Zode|zode\.qa\.qima-inc\.com|ZodeChatModel|zode_client" \
  backend scripts .env.example CLAUDE.md SCHEMA.md
```

预期：执行代码、配置和现行架构文档为零；历史文档只允许存在明确的 superseded 说明。

---

## 14. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| LangChain chunk 类型改变 | SSE 运行时报类型错误 | 显式 `stream_text()`，迁移 4 条已知流式链路 |
| SDK 自动重试与外层重试叠加 | 延迟和成本不可控 | Provider client 禁用隐式 retry，由 Managed model 统一管理 |
| Fallback Runnable 改变属性/trace | 业务 metadata 丢失 | 不直接把 `with_fallbacks()` 暴露给业务，由 registry 记录 profile |
| Omni 与 OpenAI-compatible 差异 | 材料上传失败 | 独立 vision probe；必要时只为多模态使用 `ChatTongyi` |
| 原生 structured output 支持不一致 | schema 成功率下降 | 首期保留 `structured_output.py` |
| Tool Calling 误绕过治理 | 权限和数据风险 | 工具请求必须回到 Runtime v2 + Tool Registry |
| 删除 Node 后仍有脚本依赖 | 镜像或离线任务失败 | 全仓搜索、脚本清单和无 Node 镜像 smoke |
| Provider alias 漂移 | eval 不可复现 | 生产/eval 使用 snapshot，alias 变更重跑 capability/eval |
| Langfuse callback 重复记录 | 成本与统计失真 | 首期保留单一手写 attempt generation，后续再迁移 callback |
| 线上实际环境与仓库示例不同 | 错删仍在使用的凭证/模型 | Milestone 0 导出脱敏运行配置并与部署平台核对 |

---

## 15. 待确认项

以下事项不影响 Spec 成立，但必须在 Milestone 0/1 给出证据结论：

1. 线上部署当前实际 `LLM_PROVIDER`、模型 override 和 endpoint host；仓库只能证明 CI/示例主路径为 Bailian。
2. 百炼账号应继续使用公共 compatible endpoint，还是切换到账号 workspace 专属 endpoint。
3. `qwen3.5-omni-flash/plus` 在目标区域对 OpenAI-compatible 图片 URL/base64、流式和 usage metadata 的实际支持。
4. `qwen3.7-plus` 与 `qwen3.7-max-2026-06-08` 在目标区域、thinking 配置下的 tool calling 和 native structured output 能力。
5. `eval/ragas_eval.py` 的 judge 是否继续使用真实 Anthropic，或统一迁移到经验证的百炼 judge profile。
6. 经 resolver 验证后应锁定的 `langchain-openai` 版本及其与当前 `langchain-core/langgraph/langsmith` 的兼容组合。

这些问题必须通过脱敏部署检查、官方能力文档和真实 capability probe 回答，不通过猜测填充。

---

## 16. 参考资料

- 阿里云百炼官方 LangChain 集成：<https://help.aliyun.com/zh/model-studio/use-bailian-in-langchain>
- 百炼 OpenAI-compatible Chat Completions：<https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions>
- 百炼 OpenAI-compatible Responses：<https://help.aliyun.com/en/model-studio/qwen-api-via-openai-responses>
- Qwen Function Calling：<https://help.aliyun.com/zh/model-studio/qwen-function-calling>
- 百炼视觉模型：<https://help.aliyun.com/en/model-studio/vision-model/>
- LangChain Agents：<https://docs.langchain.com/oss/python/langchain/agents>
- LangChain Structured Output：<https://docs.langchain.com/oss/python/langchain/structured-output>
- LangGraph Streaming：<https://docs.langchain.com/oss/python/langgraph/streaming>
