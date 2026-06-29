# AI Agent 工程师技能点梳理

本文档整理当前市场上 AI Agent 工程师需要掌握的核心技能，用于后续学习规划、项目能力建设和岗位能力对标。

## 1. 基础工程能力

AI Agent 工程师首先需要具备扎实的软件工程能力。Agent 不是简单调用大模型 API，而是需要把模型、业务系统、工具调用、数据存储和用户交互组合成稳定可用的产品。

核心能力包括：

- Python 或 TypeScript 至少熟练掌握一门。
- 熟悉后端开发框架，如 FastAPI、Flask、Node.js、NestJS。
- 理解 REST API、SSE、WebSocket、异步任务和后台任务队列。
- 熟悉 PostgreSQL、MySQL、Redis、MongoDB 等常见数据存储。
- 具备 Docker、环境变量管理、日志、部署和 CI/CD 基础能力。
- 熟悉 Git、Linux、命令行和常见调试手段。

对于 AI Agent 产品来说，工程落地能力通常比单纯的算法能力更重要。

## 2. 大模型基础能力

AI Agent 工程师不一定需要训练大模型，但必须理解如何稳定、可控、低成本地使用大模型。

需要掌握：

- Prompt Engineering。
- System Prompt、User Prompt、Tool Prompt 的设计。
- Function Calling 和 Tool Use。
- Structured Output，如 JSON Schema、Pydantic、Zod。
- 多轮对话上下文管理。
- Token、上下文窗口和调用成本控制。
- Streaming 输出。
- 模型选择与模型路由，如 fast model、quality model、fallback model。
- 常见模型生态，如 Claude、GPT、Gemini、Qwen、DeepSeek、Llama。

重点不是写复杂的 prompt，而是让模型输出稳定、行为可控、结果可评估。

## 3. Agent 框架与工作流

Agent 工程师需要理解智能体如何规划、执行、调用工具、维护状态并在必要时交给用户确认。

常见框架和平台包括：

- LangChain。
- LangGraph。
- LlamaIndex。
- AutoGen。
- CrewAI。
- Dify、Coze、Flowise 等低代码 Agent 平台。
- OpenAI Agents SDK、Anthropic Tool Use、MCP。
- 企业内部自研 Agent workflow。

需要理解的模式包括：

- ReAct：Reason + Act。
- Planner / Executor 架构。
- 多 Agent 协作。
- 状态机和图式工作流。
- Human-in-the-loop。
- Agent Memory。
- 工具调用失败重试。
- 任务拆解与结果合成。
- Agent 终止条件与防死循环机制。

当前生产级 Agent 越来越倾向于使用可控状态图，而不是不可控的自由循环。

## 4. RAG 检索增强生成

RAG 是 AI Agent 工程师的高频核心能力，尤其适用于企业知识库、教育、法律、金融、客服和内部工具场景。

需要掌握：

- 文档解析与清洗。
- 文档切分 chunking。
- Embedding 模型选择。
- 向量数据库，如 Chroma、Milvus、Weaviate、Pinecone、Qdrant、pgvector。
- Hybrid Search：关键词检索 + 向量检索。
- Rerank：bge-reranker、Cohere Rerank 等。
- Query Rewrite。
- Multi-query Retrieval。
- Context Compression。
- 引用来源与可追溯回答。
- 知识库更新与增量索引。

RAG 的难点通常不在于“能不能检索”，而在于解决检索不准、上下文过长、引用不可信、多文档冲突和模型幻觉等问题。

## 5. Tool、MCP 与外部系统集成

Agent 的核心价值在于“能做事”。因此，工具调用和外部系统集成能力非常关键。

常见集成对象包括：

- 数据库查询。
- 文件读写。
- 浏览器自动化。
- 企业系统 API。
- 搜索引擎。
- 日历、邮件、Slack、飞书、钉钉。
- GitHub、Jira、Linear。
- 内部知识库。
- 代码执行环境。
- MCP Server。

需要重点关注：

- 工具权限控制。
- 工具参数校验。
- 工具调用日志。
- 工具失败恢复。
- 敏感操作确认。
- 沙箱隔离。
- Prompt injection 防护。

MCP 正在成为 Agent 连接外部工具和数据源的重要协议，值得重点学习。

## 6. Agent 记忆系统

高级 Agent 通常需要记忆能力，但记忆系统的关键不只是“存下来”，而是判断什么时候记、记什么、什么时候用以及如何处理冲突。

需要理解：

- 短期记忆：当前对话上下文。
- 长期记忆：用户偏好、项目背景、历史任务。
- 向量记忆。
- 结构化记忆。
- Memory CRUD。
- 记忆过期和冲突处理。
- 隐私和权限控制。

好的记忆系统应该服务于任务完成，而不是无差别记录所有内容。

## 7. 评测与可靠性

评测能力是区分 Demo Agent 和生产级 Agent 的关键。

需要掌握：

- Prompt eval。
- Golden dataset。
- 单轮和多轮对话评测。
- Tool call accuracy 评测。
- RAG 命中率评测。
- 幻觉率评测。
- LLM-as-a-judge。
- A/B 测试。
- 回归测试。
- 日志分析。
- 失败样本归因。

常见指标包括：

- Task success rate。
- Tool call success rate。
- Retrieval precision / recall。
- Latency。
- Cost per request。
- Human escalation rate。
- Hallucination rate。

企业场景更关注 Agent 是否能稳定完成任务，而不是单次演示效果。

## 8. 前端与产品交互能力

AI Agent 产品的前端体验和普通聊天机器人不同。用户需要理解 Agent 当前在做什么、为什么这么做、哪里失败了，以及是否需要人工介入。

需要理解：

- Chat UI。
- Streaming UI。
- Agent 执行步骤展示。
- 工具调用过程展示。
- 可中断和可恢复任务。
- 用户确认弹窗。
- 文件上传。
- 多模态输入。
- 历史记录。
- 错误状态设计。

优秀的 Agent 产品需要让用户既感受到自动化能力，也能清楚掌控关键操作。

## 9. 安全与权限

Agent 一旦可以调用工具，就会带来更高的安全风险。生产系统必须设计清晰的权限边界。

需要关注：

- Prompt Injection。
- Data Exfiltration。
- 越权工具调用。
- SSRF。
- 命令注入。
- SQL 注入。
- 文件系统越权。
- 用户数据泄露。
- 敏感信息脱敏。
- 操作审计。
- 权限分级。
- 人工确认机制。

Agent 不应该在没有确认和权限控制的情况下执行删除文件、发邮件、转账、修改数据库、推送代码或调用内部敏感 API 等操作。

## 10. 多模态能力

多模态 Agent 正在变得越来越常见，尤其在教育、办公、合同、报表和浏览器自动化场景中。

相关能力包括：

- 图片理解。
- PDF 解析。
- 表格解析。
- OCR。
- 语音输入输出。
- 截图理解。
- 浏览器视觉操作。
- 视频理解。

典型场景包括读合同、批改作业、分析报表、操作网页、处理截图和自动生成课件。

## 11. 热门业务方向

当前 AI Agent 工程师常见的热门方向包括：

### 企业知识库 Agent

- RAG。
- 权限知识库。
- 内部搜索。
- 文档问答。
- 工单助手。

### 编程 Agent

- 代码理解。
- 自动改代码。
- 测试生成。
- PR Review。
- DevOps 自动化。

### 数据分析 Agent

- Text-to-SQL。
- 自动生成图表。
- 数据解释。
- BI 助手。

### 教育 Agent

- 智能答疑。
- 作文批改。
- 个性化辅导。
- 学情分析。
- 题目生成。

### 客服与销售 Agent

- 多轮对话。
- CRM 集成。
- 工单流转。
- 自动跟进。

### 办公自动化 Agent

- 邮件。
- 日程。
- 文档。
- 表格。
- 审批流程。

## 12. 推荐学习路线

建议按照以下顺序学习：

1. Python 或 TypeScript 后端基础。
2. LLM API 调用。
3. Prompt 与 Function Calling。
4. RAG 知识库。
5. LangGraph 或 LangChain。
6. 多工具 Agent。
7. Memory 设计。
8. Agent 评测。
9. 部署、日志和成本控制。
10. 安全与权限控制。

对于已有工程基础的人来说，可以从 LLM API、Tool Calling 和 RAG 开始快速切入；对于工程基础薄弱的人，应先补齐后端和数据存储能力。

## 13. 推荐项目作品

如果用于求职或能力展示，建议准备 2 到 3 个完整项目。

### 企业知识库 Agent

展示能力：

- 文档上传。
- 向量检索。
- RAG 问答。
- 引用来源。
- 权限控制。
- 评测集。

### 多工具任务 Agent

例如“自动调研一个主题并生成报告”。

展示能力：

- 搜索工具。
- 网页读取。
- 信息汇总。
- 多步骤计划。
- 结果校验。
- Markdown 或 PDF 输出。

### 垂直行业 Agent

例如教育、法律、医疗、金融、电商或编程 Agent。

展示能力：

- 业务理解。
- 工作流设计。
- 专用工具。
- 可靠性优化。
- 用户体验设计。

## 14. 面试高频问题与参考回答

### 14.1 RAG 怎么做，如何提升准确率？

RAG 的基本流程是：文档解析、清洗、切分、生成 embedding、写入向量库，用户提问时先检索相关片段，再把检索结果和问题一起交给大模型生成回答。

提升准确率可以从几个方向入手：

- 优化 chunk 切分，避免片段过短丢上下文或过长引入噪声。
- 使用更适合业务语言和领域的 embedding 模型。
- 结合关键词检索和向量检索做 Hybrid Search。
- 增加 rerank 阶段，把初步召回的结果重新排序。
- 对用户问题做 query rewrite 或 multi-query retrieval。
- 要求模型基于检索内容回答，并输出引用来源。
- 建立评测集，持续观察命中率、引用准确率和幻觉率。

核心思路是先提升“检索到正确材料”的概率，再约束模型“只能基于材料作答”。

### 14.2 Agent 和普通 Chatbot 有什么区别？

普通 Chatbot 主要负责对话和回答问题，通常是输入文本、输出文本。Agent 不只是回答，还能围绕目标进行规划、调用工具、读取外部信息、执行任务、观察结果并继续下一步。

两者的关键区别包括：

- Chatbot 偏问答，Agent 偏任务完成。
- Chatbot 通常只依赖模型上下文，Agent 会调用外部工具和系统。
- Chatbot 的流程较短，Agent 可能包含多步骤工作流。
- Chatbot 结果通常是文本，Agent 结果可能是文件、数据库变更、API 操作或业务流程推进。
- Agent 更需要权限控制、状态管理、失败恢复和评测体系。

一句话概括：Chatbot 是“会聊”，Agent 是“能做事”。

### 14.3 Function Calling 如何设计？

Function Calling 的设计重点是让模型能稳定、准确、安全地调用工具。

设计原则包括：

- 工具职责要单一，不要把多个业务动作塞进一个函数。
- 参数 schema 要清晰，字段名语义明确，必要字段和可选字段分开。
- 参数尽量结构化，避免让模型传大段自由文本。
- 工具返回值也要结构化，方便模型继续判断下一步。
- 对外部输入和工具参数做校验，防止越权、注入和非法操作。
- 对高风险操作增加人工确认，比如删除、发送、支付、修改生产数据。
- 记录工具调用日志，便于审计和问题排查。

好的 Function Calling 不是简单暴露接口，而是把模型可以安全使用的能力封装成边界清晰的工具。

### 14.4 如何防止 Agent 死循环？

Agent 死循环通常来自目标不清晰、终止条件缺失、工具结果无法推进或模型反复尝试同一动作。

常见防护方式包括：

- 设置最大步骤数、最大工具调用次数和最大运行时间。
- 定义明确的任务完成条件和失败条件。
- 记录最近几步行为，检测重复调用同一工具或重复生成相同计划。
- 工具失败后限制重试次数，并要求换策略或上报失败。
- 对复杂任务使用状态机或 LangGraph 这类可控工作流，而不是完全自由循环。
- 在关键节点引入 human-in-the-loop，让用户确认或补充信息。

生产环境中应优先使用可控流程和显式终止条件，而不是完全依赖模型自行判断何时结束。

### 14.5 多 Agent 有什么问题？

多 Agent 可以提升分工能力和并行能力，但也会带来明显的工程复杂度。

常见问题包括：

- 成本更高，因为多个 Agent 会产生更多模型调用。
- 延迟更高，尤其是存在串行依赖时。
- 结果可能冲突，需要仲裁或合并机制。
- 上下文传递容易丢信息或重复信息。
- 调试困难，不容易定位是哪一个 Agent 出错。
- 多个 Agent 可能互相放大错误，导致错误结论看起来更可信。
- 权限管理更复杂，不同 Agent 应该拥有不同工具能力。

多 Agent 适合明确分工、并行研究、审查验证、复杂任务拆解等场景，不应该为了“看起来智能”而滥用。

### 14.6 如何做 Agent 评测？

Agent 评测要围绕任务完成情况，而不只是回答是否流畅。

可以从以下层面评测：

- 最终任务是否完成，即 task success rate。
- 工具是否调用正确，即 tool call accuracy。
- 参数是否正确，是否有多调、漏调、错调。
- RAG 是否检索到正确材料。
- 回答是否基于证据，是否存在幻觉。
- 多轮对话中是否保持上下文一致。
- 延迟和成本是否可接受。
- 失败时是否能正确降级、重试或请求人工介入。

常见方法包括构建 golden dataset、记录真实用户失败样本、使用 LLM-as-a-judge 做初筛，再用人工复核关键样本。生产级评测应结合自动化指标和人工质检。

### 14.7 如何降低 token 成本？

降低 token 成本可以从输入、输出、模型选择和缓存几个方向入手。

常见方法包括：

- 精简 system prompt 和上下文，只保留当前任务必要信息。
- 对历史对话做摘要，而不是每轮都传完整历史。
- RAG 只传最相关片段，并控制 chunk 数量和长度。
- 使用 fast model 处理简单任务，quality model 处理复杂任务。
- 对固定 prompt、工具说明、知识片段使用 prompt caching。
- 使用结构化输出，减少冗长自然语言中间过程。
- 限制最大输出长度。
- 对可复用结果做应用层缓存。

成本优化不能只靠换便宜模型，还要优化上下文设计和任务路由。

### 14.8 如何处理幻觉？

幻觉是大模型在缺少可靠依据或约束不足时生成不真实内容的问题。

常见处理方式包括：

- 使用 RAG 提供可信上下文，并要求模型基于上下文回答。
- 要求输出引用来源，便于用户追溯。
- 对事实性回答增加校验模型或规则校验。
- 对不确定内容允许模型回答“不知道”或请求更多信息。
- 降低不必要的创造性参数，减少自由发挥。
- 对高风险领域引入人工审核。
- 建立幻觉样本集，持续回归测试。

核心原则是：事实性任务要让模型“有据可依”，并让结果“可验证”。

### 14.9 如何做权限控制？

Agent 权限控制要限制它能看什么、能调用什么、能执行什么操作。

常见设计包括：

- 按用户身份和角色决定可访问的数据范围。
- 按 Agent 类型配置可用工具，不同 Agent 不共享全部权限。
- 对工具做参数级校验，避免越权访问资源。
- 高风险操作必须人工确认。
- 对生产数据、外部发送、删除、支付、权限变更等操作设置强约束。
- 记录完整审计日志，包括用户、Agent、工具、参数、结果和时间。
- 对敏感信息做脱敏，避免泄露到模型上下文或日志。

权限控制不能只写在 prompt 里，必须在后端和工具层做强制校验。

### 14.10 LangChain 和 LangGraph 有什么区别？

LangChain 更偏向组件库，提供模型调用、prompt、chain、tool、retriever 等模块，适合快速搭建 LLM 应用。

LangGraph 更偏向状态图和工作流编排，适合构建多步骤、可控、有状态、可循环、可中断的 Agent 流程。

可以简单理解为：

- LangChain 适合做 LLM 应用的基础积木。
- LangGraph 适合做生产级 Agent 的流程控制。
- LangChain 更像链式调用框架。
- LangGraph 更像状态机或图工作流。

如果任务简单，LangChain 就够用；如果任务涉及规划、工具调用、多节点状态、重试、人工确认和循环控制，LangGraph 更合适。

### 14.11 工具调用失败怎么办？

工具调用失败时，Agent 不应该无限重试，也不应该假装成功。

合理处理方式包括：

- 区分失败类型，如参数错误、权限错误、网络错误、服务异常、业务规则失败。
- 对临时错误做有限次数重试。
- 对参数错误让模型修正参数后再调用。
- 对权限错误直接停止，并告知用户需要授权。
- 对业务失败返回清晰原因，让 Agent 换方案或请求用户确认。
- 记录失败日志，便于排查。
- 在无法恢复时给出明确失败状态，而不是继续编造结果。

工具失败处理的关键是可恢复、可解释、可审计。

### 14.12 如何设计长期记忆？

长期记忆应该围绕未来任务是否有帮助来设计，而不是把所有对话都保存。

设计时需要考虑：

- 记忆类型，如用户偏好、项目背景、业务规则、常用资源、长期目标。
- 写入条件，即什么时候应该保存记忆。
- 读取条件，即什么时候应该把记忆带入上下文。
- 更新和删除机制，避免过期记忆污染结果。
- 冲突处理，当新信息和旧记忆不一致时应以最新确认信息为准。
- 权限和隐私，不同用户或项目的记忆不能混用。
- 可解释性，必要时能告诉用户使用了哪些记忆。

长期记忆的目标是减少重复沟通和提升个性化，而不是无限扩大上下文。

### 14.13 如何保证回答可追溯？

回答可追溯的关键是让结论能对应到明确来源。

常见做法包括：

- RAG 检索时保留文档 ID、标题、段落、页码、URL 或数据库主键。
- 生成回答时要求模型在关键结论后附引用。
- 前端展示引用来源，用户可以点击查看原文。
- 对引用片段和最终回答建立映射，避免引用和结论不一致。
- 对无法找到依据的内容标注不确定或不回答。
- 在日志中保存检索结果、模型输入、模型输出和引用信息。

可追溯不是简单在答案末尾贴几个链接，而是要确保每个关键事实都能回到可信来源。

## 15. 2026 年线上岗位和生产实践新增重点

结合 2026 年 AI Agent 工程岗位描述、生产级 Agent 技术文章和 AgentOps 相关资料，市场要求已经从“会调用模型、会写 Prompt”明显转向“能把 Agent 做成可观测、可评测、可治理、可持续迭代的工程系统”。

需要额外重点补齐以下能力：

### 15.1 AgentOps 与可观测性

线上岗位越来越强调 Agent 的 trace、span、工具调用轨迹、成本、延迟、错误率和用户反馈闭环。

需要掌握：

- LLM / Agent tracing：记录每次模型调用、工具调用、检索结果和中间状态。
- Token、成本、延迟和失败率监控。
- 生产问题排查：从用户反馈定位到 prompt、retrieval、tool、model 或数据问题。
- 常见工具：LangSmith、Langfuse、Helicone、MLflow Tracing、OpenTelemetry、Datadog、Weights & Biases。
- Trace 到 eval 的闭环：把线上失败样本沉淀为回归测试集。

### 15.2 Evaluation Engineering

Agent 评测已经成为独立能力，而不是简单写几个 smoke test。

需要掌握：

- Offline eval：固定数据集、golden answer、检索命中率、幻觉率、格式稳定性。
- Online eval：用户满意度、人工接管率、失败转化率、真实任务完成率。
- Trajectory eval：评估 Agent 的中间步骤、工具选择、参数、重试和终止条件。
- Regression eval：每次改 prompt、模型、知识库和工具后自动回归。
- LLM-as-a-judge 的校准：抽样人工复核，避免 judge 自身偏差。

### 15.3 Guardrails、Runtime Safety 与治理

生产 Agent 的安全重点在工具和行动边界，而不只是 prompt 层提醒。

需要掌握：

- Prompt injection / indirect prompt injection 防护。
- Tool allowlist、参数级权限、风险分级和人工确认。
- 数据脱敏、审计日志、租户隔离和访问控制。
- Runtime interception：在工具执行前拦截高风险动作。
- Policy-as-code：把权限策略放在后端或策略引擎，而不是只写在 system prompt。
- 红队测试和安全评测集。

### 15.4 上下文工程与动态上下文

Agent 的效果越来越依赖 context engineering，而不是单次 prompt 技巧。

需要掌握：

- 动态选择上下文：用户画像、历史记忆、RAG 片段、工具结果、任务状态。
- Context compression 和对话摘要。
- 记忆读写策略：什么时候写入、什么时候召回、什么时候过期。
- Prompt caching 和上下文成本优化。
- 多来源上下文冲突处理。

### 15.5 Schema-first 与可靠工具编排

线上 Agent 更偏向 schema-first 的工具和输出设计。

需要掌握：

- JSON Schema、Pydantic、Zod 等结构化约束。
- Native function calling / tool use API。
- 工具返回值标准化。
- 工具调用幂等性、重试、超时和错误分类。
- 对高风险工具增加权限、确认和审计。

### 15.6 多智能体与人机协作边界

多 Agent 能提升复杂任务处理能力，但岗位更看重是否能控制复杂度。

需要掌握：

- 多 Agent 分工、仲裁、反思和验证。
- 并行执行和结果合并。
- 人工确认、人类反馈和可恢复任务。
- 成本与延迟控制。
- 避免无意义的多 Agent 表演式架构。

### 15.7 生产交付能力

越来越多岗位要求 AI Engineer 同时具备后端、MLOps/LLMOps 和产品交付能力。

需要掌握：

- Docker、CI/CD、灰度发布和环境隔离。
- Secrets 管理和模型供应商切换。
- 缓存、限流、降级和 fallback。
- 数据库迁移、任务队列和异步作业。
- 产品指标和业务指标联动。

## 16. 当前 EduAgent 项目完成度评估

以下评估基于当前项目代码与文档，重点看“是否能体现 AI Agent 工程能力”，而不是单纯功能数量。

| 能力模块 | 当前完成度 | 项目证据 | 主要缺口 | 建议优先级 |
| --- | --- | --- | --- | --- |
| 基础后端工程 | 高 | `backend/api/main.py` 使用 FastAPI，覆盖角色聊天、学习助手、材料、游戏、作文、辩论等 API | 缺少系统化 API 测试和 OpenAPI 级别契约测试 | 中 |
| 前端产品化交互 | 高 | `frontend/app/history-character/page.tsx`、`frontend/app/learning-assistant/page.tsx`、`frontend/app/material-upload/page.tsx` 已支持流式对话、工具轨迹、材料上传和 RAG 问答 | 复杂 Agent 执行过程还可以进一步可视化，如步骤时间线、失败恢复、用户确认节点 | 中 |
| LLM 调用与模型路由 | 中高 | `backend/llm_config.py` 支持 fast / quality / fallback / reasoning / multimodal 等模型配置，并通过 Node helper 兼容 Anthropic 和 DashScope/Bailian | 缺少 prompt caching、请求预算控制、统一结构化输出重试层 | 高 |
| LangGraph / Agent Workflow | 高 | `backend/agents/history_character.py`、`essay_grader.py`、`debate_supervisor.py` 使用 `StateGraph` 建立可控流程 | 部分 Agent 仍是应用逻辑编排，尚未统一成可观察、可恢复的 workflow 标准 | 中 |
| RAG 检索增强 | 高 | `backend/rag/knowledge_base.py` 使用 Chroma + BGE embedding，支持历史知识库；`backend/materials/service.py` 支持材料入库和问答 | 可补 hybrid search 质量评测、rerank 对比、增量索引策略和引用准确率评测 | 高 |
| Tool / Function Calling | 中 | `backend/tools/registry.py` 有工具注册表，`backend/agents/learning_assistant.py` 能编排工具，前端能展示 tool_start / tool_result | 主要是应用侧意图识别和工具编排，缺少 native provider function calling、schema-first tool call、参数级权限策略 | 高 |
| Memory / 用户画像 | 中高 | `backend/session_store.py` 做短期会话，`backend/user_memory.py` 和 `backend/student_profile.py` 做学习画像、弱项和事件记录 | 缺少跨 Agent 统一记忆策略、记忆召回评测、用户可查看/删除记忆的产品入口 | 中 |
| Streaming UX | 高 | `backend/api/main.py` 多处 `StreamingResponse`，角色聊天、学习助手、辩论等支持 SSE；前端解析流事件 | 可增加中断、恢复、重试和更细粒度 step trace | 中 |
| 多模态与文档处理 | 中高 | `backend/materials/service.py` 支持 PDF、图片 OCR、multimodal transcription；`frontend/app/material-upload/page.tsx` 支持上传和 OCR 复核 | 可补表格结构化、版面理解、批量材料处理和多模态评测集 | 中 |
| Evaluation / 回归测试 | 中高 | `eval/history_character_smoke.py`、`eval/material_rag_smoke.py`、`eval/rag_retrieval_eval.py`、`eval/ragas_eval.py`、`eval/run_core_evals.py` 已有 smoke/eval 基础 | 还缺统一指标看板、trajectory eval、线上失败样本自动沉淀、CI 自动跑核心 eval | 高 |
| Observability / AgentOps | 中 | `backend/tracing.py` 有 Langfuse tracing，`backend/tools/registry.py` 包装工具 span，`backend/security/audit_log.py` 做审计日志 | 缺少 OpenTelemetry/Prometheus 指标、告警、成本看板、trace 与 eval dataset 的闭环 | 高 |
| Guardrails / 安全权限 | 中 | `backend/security/prompt_injection.py`、`auth.py`、`rate_limit.py`、`audit_log.py` 已有 prompt injection、JWT、限流、审计和脱敏基线 | 规则偏轻量，缺少 per-tool policy、运行时拦截、沙箱、高风险操作确认、安全评测集 | 高 |
| 部署与配置 | 中 | `backend/Dockerfile`、`frontend/Dockerfile`、`docker-compose.yml`、`.env.example` 已覆盖本地容器化和环境配置 | 缺少云部署流水线、CI/CD、数据库迁移、生产 secrets 管理、监控告警 | 中 |
| 教育业务垂直化 | 高 | 历史角色、时间线游戏、材料学习、作文批改、辩论等场景明确，符合 K-12 教育 Agent 方向 | 还可增强学习路径推荐、学情分析闭环、教师端运营数据 | 中 |

### 总体判断

EduAgent 已经不是简单聊天 Demo，而是一个具备较完整 Agent 工程雏形的垂直教育 Agent 项目。当前最强的部分是：

1. 教育场景完整度。
2. LangGraph 状态图工作流。
3. 历史知识库与材料 RAG。
4. SSE 流式产品体验。
5. 多模态材料解析。
6. 基础评测和 Langfuse tracing。

如果用于 AI Agent 工程师求职展示，当前项目已经能覆盖大部分核心技能，但还需要把“生产级能力”做得更显性：eval 指标、AgentOps 看板、工具权限、运行时安全和部署流水线。

## 17. 建议补齐路线

### 第一优先级：把项目从“功能完整”升级为“可评测”

建议补齐：

- 为历史角色问答、材料 RAG、学习助手工具调用分别建立 golden dataset。
- 增加统一 eval runner 输出 JSON 指标：task success、retrieval hit、source correctness、format validity、latency、cost。
- 把线上/手动失败样本保存为回归用例。
- 为工具调用增加 trajectory eval：是否选对工具、参数是否正确、是否多调/漏调。

这部分最能体现 Agent 工程师区别于普通应用开发的能力。

### 第二优先级：把 Tool Calling 做成 schema-first

建议补齐：

- 为 `backend/tools/registry.py` 的每个工具定义严格 JSON Schema 或 Pydantic schema。
- 支持 Anthropic/OpenAI 兼容的 native tool use 调用路径。
- 标准化工具返回结构：`ok`、`data`、`error_code`、`message`、`trace_id`。
- 增加 per-tool permission 和 high-risk confirmation 字段。

这样可以把项目从“应用侧模拟工具调用”提升到“生产级工具编排”。

### 第三优先级：完善 AgentOps 闭环

建议补齐：

- 在 Langfuse trace 中统一记录 session_id、user_id、agent_name、tool_name、retrieval_docs、model、tokens、latency、cost。
- 增加 AgentOps 仪表盘或至少导出指标脚本。
- 把 trace 中失败样本转成 eval case。
- 增加成本预算和模型路由策略说明。

这部分可以直接对齐线上岗位对 observability / monitoring / evaluation 的要求。

### 第四优先级：加强 Guardrails 和权限治理

建议补齐：

- 对所有工具增加风险等级：read、write、external、destructive。
- 对 write/external/destructive 工具增加后端强制确认，不只依赖 prompt。
- 增加 prompt injection 测试集和 indirect prompt injection 测试。
- 对 RAG 上下文继续保持 untrusted 标记，并在输出层校验引用是否来自检索结果。
- 增加用户可见的数据删除和记忆管理入口。

### 第五优先级：补齐部署与 CI/CD

建议补齐：

- GitHub Actions 或等价 CI：lint、frontend build、核心 eval、Docker build。
- 生产环境 secrets 管理说明。
- 数据库迁移方案。
- Redis、SQLite/数据库、Chroma 持久化策略。
- 基础监控告警：错误率、延迟、模型失败率、成本异常。

## 18. 面向求职展示的项目包装建议

如果把 EduAgent 作为 AI Agent 工程师作品集，建议突出以下卖点：

- 垂直教育 Agent：覆盖历史角色扮演、材料学习、题目生成、作文批改、辩论和游戏化学习。
- 可控 Agent Workflow：使用 LangGraph 状态图，而不是自由循环 Agent。
- RAG 能力：历史知识库和用户上传材料两类知识源，支持引用来源。
- 多模态能力：支持 PDF、图片 OCR 和多模态转写。
- 流式 UX：SSE 输出、状态事件、来源展示、工具轨迹展示。
- AgentOps 基线：Langfuse tracing、审计日志、限流和安全检查。
- 评测意识：已有 smoke/eval 目录，可继续扩展为标准 eval harness。

建议在 README 或作品集里用一张矩阵展示：

| 展示点 | 对应岗位能力 |
| --- | --- |
| LangGraph 角色 Agent / 作文批改 / 辩论 | Agent workflow、状态机、多步骤任务 |
| Chroma + BGE + sources | RAG、embedding、引用可追溯 |
| Learning Assistant 工具注册表 | Tool calling、工具编排 |
| Material Upload + OCR + multimodal | 多模态、文档理解 |
| Langfuse tracing + audit log | Observability、AgentOps、安全审计 |
| eval 目录 | Evaluation engineering、回归测试 |
| Next.js 流式前端 | Agent 产品交互、Streaming UX |

## 19. 参考资料

以下资料用于补充 2026 年 Agent 工程岗位与生产实践趋势：

- [LangChain: State of Agent Engineering](https://www.langchain.com/state-of-agent-engineering)
- [LangChain: Agent observability powers agent evaluation](https://www.langchain.com/blog/agent-observability-powers-agent-evaluation)
- [MLflow: Building Production-Ready AI Agents in 2026](https://mlflow.org/articles/building-production-ready-ai-agents-in-2026/)
- [MLflow: Setting Up LLM Observability Pipelines in 2026](https://mlflow.org/articles/setting-up-llm-observability-pipelines-in-2026/)
- [OpenTelemetry: GenAI Observability](https://opentelemetry.io/blog/2026/genai-observability/)
- [O'Reilly Radar: The AI Agents Stack 2026 Edition](https://www.oreilly.com/radar/the-ai-agents-stack-2026-edition/)
- [Cognizant: ML Ops / Agent Ops Engineer](https://careers.cognizant.com/us-en/jobs/00069014281/ml-ops-agent-ops-engineer/)
- [AI Agent Engineer role examples](https://agentic-engineering-jobs.com/jobs/general-motors-ai-agent-engineer-xcO1WX)
- [AgentTrust: Runtime Safety Evaluation and Interception for AI Agent Tool Use](https://arxiv.org/abs/2605.04785)
- [A Comparative Evaluation of AI Agent Security Guardrails](https://arxiv.org/abs/2604.24826)

## 20. 总结

AI Agent 工程师的核心能力不是单纯调用大模型 API，而是把大模型、工具、知识库、业务流程、安全权限和工程系统组合成稳定可用的智能体产品。

优先级最高的能力可以概括为：

1. 后端工程能力。
2. LLM API 与 Tool Calling。
3. RAG。
4. LangGraph 或 Agent Workflow。
5. 评测与可靠性。
6. 安全与权限。
7. 产品化交互体验。
8. AgentOps、可观测性和成本治理。
9. 生产级 eval 与线上反馈闭环。
10. Runtime guardrails 和工具权限治理。
