# ADR：Agent Runtime v2 与 LangGraph 的职责边界

**日期：** 2026-08-28
**状态：** Accepted

## 背景

EduAgent 同时存在 LangGraph 状态图、确定性顺序计划、自研教学状态机和单次 Function/Chain。Runtime v2 已提供统一 Run/Event/Artifact、权限、预算、幂等、完成判定和灰度能力，但生产链路中的 Adapter 仍未成为通用执行入口。

继续让 Runtime v2 复制图调度、节点重试和图 checkpoint，会形成两套执行引擎，并扩大流式/非流式行为不一致、恢复状态双真相和升级兼容风险。

## 决策

Runtime v2 定位为框架无关的 Agent 控制与治理平面，不发展为 LangGraph 的替代执行引擎。

Runtime v2 拥有：

- actor、owner、student、data scope 等可信业务上下文；
- Capability/Tool allowlist、风险、确认和调用预算；
- Run/Event/Artifact 对外合同与 SSE cursor replay；
- 外部写操作的幂等键、side-effect ledger 和审计；
- Evidence/Completion 业务判定；
- rollout、kill switch、AgentOps 和 deployment readiness。

LangGraph 拥有：

- 图节点调度、条件分支和有界循环；
- 图内部状态合并；
- interrupt/resume 和节点重试；
- 图级 checkpoint 与节点执行位置；
- graph update/custom stream 的产生。

两层 checkpoint 的边界为：

- LangGraph checkpoint 保存图执行位置和节点状态；
- Runtime checkpoint 只保存业务恢复边界、公开状态以及 LangGraph checkpoint 引用；
- 学生正文、确认令牌等敏感内容只进入受控 Artifact，不进入通用事件或 trace。

## 接入规则

1. 复杂、有状态、存在分支或暂停恢复的工作流使用 LangGraph。
2. 确定性顺序计划可保留原执行器，通过 Runtime 合同记录结果，不为统一形式强制改写成图。
3. 单次工具、推荐和游戏生成保持 Function/Capability，不升级成开放式 Agent。
4. 同一产品能力只允许一个业务执行源；stream 和 non-stream 必须消费同一执行源。
5. Adapter 负责协议转换，不复制 ToolSpec、安全策略或业务完成判定。
6. 未通过真实 LLM、production RAG 和 canary 门禁前，不启用 dynamic re-plan、read fan-out 或 Agent 委派。

## 当前迁移策略

历史人物 Agent 作为首个纵向切片：由单一 compiled graph 调用现有 retrieve/generate/verify/fact-card/memory 流程，通过 `LangGraphAdapter` 转换 graph custom/update stream，流式和非流式 API 共同消费该适配流。

学习助手保持单一 `stream_learning_assistant_events()` 执行源；AutoTutor 优先验证数据库 CAS、幂等和重启恢复，暂不因架构统一而重写为 LangGraph。

## 后果

- Runtime API 和治理合同不依赖具体 Agent 框架；
- LangGraph 升级或替换不会改变产品 Run/Event 合同；
- 不再把未被生产调用的 Adapter 数量视为迁移完成度；
- 每个 Agent 的迁移以“单执行源、真实 Adapter 调用、行为 parity、灰度证据”作为完成标准。
