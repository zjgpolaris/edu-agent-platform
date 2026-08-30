# EduAgent LLM Provider v1.44 实施报告

**日期：** 2026-08-30

**基线：** `main@1c89bbd`

**状态：** Code complete · Real-provider validation pending

## 完成内容

- 新增 `backend/llm/`：Profile 合同、Provider Factory、统一 Registry、Managed model、能力探测。
- 使用 `langchain-openai` 直连百炼 OpenAI-compatible API。
- `llm_config.py` 收敛为兼容 facade，保留现有 profile 导出。
- 保持 invoke、字符串流、同 Provider fallback、Langfuse attempt 和确定性禁用语义。
- 迁移材料处理、多人卡池、教材问答、历史人物、历史地图及教材生成脚本。
- RAGAS judge 改用显式百炼模型。
- 删除旧 Node LLM helper、代理配置、跨 Provider fallback 和后端镜像 Node.js 依赖。
- Docker 和 CI 使用 `constraints-runtime.txt` 安装可复现依赖。
- 新增离线 Provider 合同 smoke 和显式 opt-in 的真实 capability probe。
- 更新现行架构文档并提供运维 Runbook。

## 验证证据

### 核心评测

```text
Total cases: 641/650 passed
Suites: 81/82 passed
Skipped suites: history_character_eval
```

`history_character_eval` 依赖真实外部模型，在当前无百炼密钥环境中按既有 optional suite 规则跳过。其余核心 Agent、RAG、Runtime、安全、工具、材料、批改和流式 parity 套件通过。

### 定向回归

```text
llm_provider_contract_smoke        PASSED
history_character_runtime_smoke    PASSED
agent_runtime_stream_parity_smoke  PASSED
textbook_quiz_smoke                3/3
material_rag_smoke                 4/4
readiness_smoke                    4/4
```

合计 6/6 suites、11/11 cases。

### 扩展 Smoke

```text
Total cases: 405/406 passed
Suites: 93/94 passed
Skipped suites: history_character_smoke
```

唯一跳过项同样需要真实 LLM/RAG 外部环境；新增适配的 `history_map_stream_smoke` 已通过。

### 环境与依赖

- Python compileall：通过
- `pip check`：No broken requirements found
- `verify_environment.py`：通过
- `langchain-openai==1.6.0`
- `langchain-core==1.6.1`
- `langgraph==1.2.11`
- `langsmith==0.11.2`

## 尚待外部环境完成

以下不是代码缺口，需要受保护的百炼凭证或部署平台权限：

1. 运行 `eval/llm_provider_live_probe.py`，确认当前账号/区域的文本、流式、JSON、多模态、Tool Calling 和 native structured output。
2. 执行真实 `history_character_eval` 和 blind/real LLM profile。
3. 在 staging/production 执行深健康检查和 canary。
4. 从部署 secret store 删除旧代理凭证；仓库无法读取或修改部署平台 secret。
5. 构建生产 Docker 镜像；当前开发环境未提供 Docker CLI。

未完成这些外部证据前，不启用原生 Tool Calling/native structured output，不宣称生产迁移闭环。
