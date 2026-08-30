# EduAgent LLM Provider v1.44 运维 Runbook

**更新时间：** 2026-08-30

**适用实现：** `backend/llm/` + `backend/llm_config.py` + 百炼 OpenAI-compatible API

## 1. 正常配置

生产必需：

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
LLM_MAX_ATTEMPTS=2
```

运行时只支持 `bailian`；`dashscope` 作为兼容别名会归一化为 `bailian`。未知 Provider 会在加载 LLM 配置时失败。

## 2. 发布前检查

```bash
PYTHONPATH=backend .venv/bin/python scripts/verify_environment.py
PYTHONPATH=backend .venv/bin/python eval/llm_provider_contract_smoke.py
PYTHONPATH=backend .venv/bin/python eval/run_core_evals.py --no-report
```

有受保护百炼密钥时：

```bash
EDU_AGENT_REAL_LLM=1 \
PYTHONPATH=backend \
.venv/bin/python eval/llm_provider_live_probe.py \
  --output /tmp/edu-agent-llm-capabilities.json
```

多模态 profile 的 `vision_base64` 必须通过后才能发布材料图片理解。`tool_calling` 和 `native_structured_output` 是探测项，未通过不影响普通 chat 发布，但不得启用对应高级能力。

## 3. 健康检查

浅检查：

```bash
curl -s -H "Authorization: Bearer $API_TOKEN" \
  "$API_BASE/api/debug/llm/health"
```

深检查：

```bash
curl -s -H "Authorization: Bearer $API_TOKEN" \
  "$API_BASE/api/debug/llm/health?deep=true"
```

重点字段：

- `provider=bailian`
- `transport=langchain_openai`
- `credentials_configured=true`
- `profiles.fast.model` 与发布配置一致
- 深检查 `ok=true`

## 4. Langfuse 排障

按以下顺序过滤：

1. `release` / `deployed_commit`
2. `trace_id` / Agent 名称
3. `profile` / `attempt_model`
4. `model_attempt` / `model_retry`
5. `finish_reason` / `provider_request_id`

典型判断：

| 现象 | 重点字段 | 动作 |
| --- | --- | --- |
| 401/403 | `LLMAuthenticationError` | 检查百炼 secret 是否存在、是否过期，不要重试 |
| 429 | `LLMRateLimitError` | 检查配额和并发；受控重试或切换已验证 fallback model |
| timeout | `LLMTimeoutError` | 检查 Provider 延迟、prompt 大小、`LLM_REQUEST_TIMEOUT_SECONDS` |
| 空输出 | `LLMEmptyResponseError` | 检查模型 snapshot/finish reason；允许切换 fallback |
| 流式中断 | `LLMStreamInterruptedError` + `partial_output=true` | 不切换模型拼接；前端结束当前 SSE 并显示降级 |
| Langfuse 无记录 | `LANGFUSE_ENABLED`/key/host | 业务可继续，但 readiness/运营标记观测降级 |

## 5. 回滚顺序

1. 关闭 Tool Calling 或 native structured output 能力 flag，恢复普通文本 + `structured_output.py`。
2. 在同一百炼 Provider 内切换到 capability report 已通过的固定模型 snapshot。
3. 关闭对应 Agent 增强能力，走产品现有确定性 fallback/degraded 路径。
4. 必要时设置 `EDU_AGENT_LLM_DISABLED=true` 暂停真实模型调用。
5. 回滚到最近一个通过核心 eval 和 live probe 的无旧代理镜像。

不得把旧代理、旧 Node helper 或隐式跨 Provider fallback 作为常规回滚方案。

## 6. 模型变更流程

任何 `LLM_MODEL_*` 变更都必须：

1. 使用明确 snapshot；
2. 重跑对应 profile 的 live probe；
3. 重跑受影响 Agent 的真实 eval；
4. 记录模型、commit、配置版本、能力报告和 Langfuse trace ID；
5. 按 profile/Agent 稳定分桶灰度；
6. 达标后再全量。

模型 alias 被 Provider 推进时视同模型变更。

## 7. 安全约束

- 不在日志、trace 或 probe artifact 输出 API key、Authorization header、图片 base64。
- 自定义 endpoint 仅用于受控测试；生产不要设置 `EDU_AGENT_LLM_ALLOW_CUSTOM_ENDPOINT=true`。
- 模型 tool call 必须返回 Runtime v2 与 Tool Registry 执行，不能直接执行任意函数。
- 生产可关闭 `LANGFUSE_CAPTURE_INPUT/OUTPUT`，只保留必要 metadata。
