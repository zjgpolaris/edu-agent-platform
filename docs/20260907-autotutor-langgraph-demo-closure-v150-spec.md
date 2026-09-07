# v1.50 AutoTutor LangGraph 演示闭环与迁移收尾 Spec

日期：2026-09-07

状态：本地功能已实现；验收结果及跳过项见 [交付记录](20260907-autotutor-langgraph-demo-v150-delivery.md)。本文不是生产放行证据。

代码基线：`eda3f94acf78bb98fd9bbd40ac9b50aec1fe52f3`

定位：个人自研 Agent / 全栈求职展示项目，免费托管优先，不承担生产 SLA

## 1. 迭代决策

复用已实现的 LangChain 模型接入和 AutoTutor LangGraph Active 状态图，交付一个可重复运行、真实标注执行来源、能够安全恢复失败请求的本地演示闭环。

**本轮必须交付的是本地隔离 Graph 演示，不是免费云端 Graph 全量切换。**
现有 Render + Supabase + 前端站点保持当前部署；不迁移数据库、不新增托管资源、不升级套餐。
普通 CI、内容可信度、鉴权、事务与幂等性仍是硬要求；生产 Canary 延迟门禁不再是本轮功能开发前置条件。

v1.50 是本轮功能版本主题，与既有 AgentOps 的 `v1.50 Entry GO` 生产判定不是同一个状态。
历史 Canary 失败、生产 NO_GO、未执行的演练保持原样，不能因为本轮通过而变成 GO。

## 2. 实际代码基线与缺口

以下结论来自实现和测试代码；历史 spec 仅作为背景，不作为完成证据。

| 能力 | 代码事实 | 本轮处理 |
|---|---|---|
| LangChain 模型接入 | `backend/llm/providers.py` 已用 ChatOpenAI；ManagedChatModel 提供原生接口与能力检查 | 复用，不再次重写 Provider |
| AutoTutor Graph | `autotutor_graph.py` 已有 Shadow 与独立 Active 节点；execution 模块已有两个执行器 | 复用真实 Active 图，不创建第三套教学算法 |
| 副作用边界 | `autotutor_transition_service.py` 管理领域提交，会话有 revision/CAS 与幂等记录 | 保留唯一业务提交入口 |
| 演示主线 | `frontend/e2e/autotutor-student-ui.spec.ts` 已覆盖答错、反思、退出票、恢复与教师证据 | 增加 Graph 断言和故障场景，不重建演示页 |
| 演示资格 | `rollout_eligibility()` 排除 demo；Graph Canary 要求 verified/runtime | 新增独立本地演示策略，不能修改生产资格来放行 demo |
| 内部强制执行 | `select_executor()` 有非生产 internal_force_graph 分支，早于常规配置/kill 检查 | 不把它暴露为 HTTP 开关或直接用作演示授权 |
| 演示轨迹 | `project_demo_trace()` 投影教学事件与模型来源，尚无真实 Graph 节点执行摘要 | 增量扩展投影，不能把教学事件当成 Graph 节点 |
| 请求可靠性 | 页面 start 未传幂等键；answer 传 revision，后端有默认幂等保护；异常后缺少明确恢复状态 | 补齐客户端请求意图和结果待确认处理 |
| 登录体验 | AuthContext 对非成功响应统一报密码错误；首页演示失败统一提示 seed | 区分鉴权、网络、超时、限流和服务错误 |
| 测试环境 | Playwright 已禁用 LLM，使用本地后端与 SQLite | 扩展隔离配置与确定性测试，无须外部模型调用 |

相关文件：

- `backend/agents/auto_tutor.py`
- `backend/agents/autotutor_execution.py`
- `backend/agents/autotutor_canary_admission.py`
- `backend/agents/autotutor_graph.py`
- `backend/api/routers/learning.py`
- `backend/agents/autotutor_demo_trace.py`
- `frontend/app/(student)/student/auto-tutor/page.tsx`
- `frontend/components/DemoAgentJourney.tsx`
- `frontend/contexts/AuthContext.tsx`
- `frontend/lib/api.ts`

## 3. 目标与非目标

### 3.1 必须完成

1. 经服务端验证的本地 demo 学生可以通过现有教学 API 运行真实 Graph。
2. 用户完成“登录 → 开课 → 答错 → 调整教学 → 退出票 → 教师证据”的完整闭环。
3. 页面如实展示 assigned/selected executor、真实节点、模型或确定性来源、降级原因。
4. 启动/答题响应丢失、重复点击、刷新时可以安全恢复，不重复写入学习副作用。
5. 无凭据的本地/CI 路径不访问外部 LLM、embedding、远程检索或追踪服务。
6. 演示结果不会计入生产验证证据，也不会改变现有生产准入规则。

### 3.2 明确不做

- Learning Assistant 全面迁移、所有 Agent 统一重写、LangChain create_agent 替换现有教学逻辑。
- 引入 LangGraph checkpointer/interrupt 或第二套持久化/事务所有者。
- 购买 LangSmith、Agent Server 或其他托管服务；迁移数据库或变更生产连接。
- 线上开放 force_graph 参数、修改 production 为 local 来绕过限制。
- 改小生产样本量、放宽 p95 阈值、重标历史验证结果或触发完整 production-verification。
- 新建通用大屏、全站请求层重构、多租户演示账号系统和全天保活。

## 4. 执行配置与信任边界

### 4.1 新增本地演示配置（拟定接口）

新增 `EDU_AGENT_AUTOTUTOR_DEMO_GRAPH_ENABLED`，默认 false；不复用 Canary BPS 作为演示开关。
普通配置继续使用 `legacy|shadow|active_canary`，本轮不新增公开 executor 参数。

演示启用必须同时满足：

- 服务进程 environment 精确为 `local` 或 `test`；production、未知值及托管环境均拒绝。
- 检查已有 Render 平台标识；即使显式 environment=local，只要检测到 Render 托管仍拒绝启动该演示配置。
- `EDU_AGENT_AUTH_REQUIRED=true`；学生身份由服务端账户查询确认 active、student、traffic_cohort=demo，不能只相信客户端字段或旧 JWT。
- 演示进程强制 `data_scope=demo`，账户、会话、事件和证据使用独立本地数据库。
- 生产 executor mode 保持 legacy、BPS=0；与 active_canary、shadow 或 release_verification 流量混用时拒绝配置。
- comparator 与安全 fallback 开启；kill switch 始终优先。
- 默认离线确定性输入：`EDU_AGENT_LLM_DISABLED=1`，显式禁用外部 embedding/追踪，并使用仓库本地教学资源。

提供 `scripts/dev_autotutor_graph_demo.py`（拟新增）作为唯一推荐启动入口：

- 默认绑定 `127.0.0.1`；本轮不提供公网监听选项。
- 创建独立临时目录和 SQLite 数据库，输出恢复所需的目录位置，不输出密钥。
- 启动前拒绝继承已有 `DATABASE_URL` / `DIRECT_URL`，不能让默认演示 seed 接触云端数据。
- 不修改调用者 .env；仅对子进程注入配置与随机本地 JWT 密钥。
- 在此隔离数据库执行现有 seed；不直接对未知目标调用 seed。
- 支持显式复用该演示目录以演示进程重启恢复；不存在或不匹配的目录拒绝复用。
- 不自动删除历史演示目录；文档给出退出、备份与定向清理方式。

环境变量防误配不等于能抵抗有权修改服务器配置的人。公网 Graph 演示需另立部署/隔离方案，不在本轮验收内。

### 4.2 路由与持久会话

新增集中式服务端 demo 策略模块，负责资格、配置和执行上下文构造，避免 start/answer 各自拼接条件。

- 保持现有 `/api/autotutor/start`、`answer`、session GET 路径；页面 `demo=1` 只控制展示。
- start 的 demo 选择结果为实际 `graph_active`，assignment reason 使用独立的 `demo_graph_selected`。
- 新增持久元数据 `execution_profile=local_demo_graph|standard`、`execution_scope=demo|runtime|eval`，旧会话按 standard 兼容。
- 元数据先落现有 `state_json`，避免为显示信息新增数据库表；修改后检查 canonical comparator 是否需要排除纯诊断字段。
- answer、恢复和重新加载必须按会话持久标识再次授权，不能只在 start 检查一次。
- 既有 Legacy 会话不隐式升级；用户选择“重新演示”才创建新 Graph 会话。
- demo 开关关闭、kill switch 开启、账户资格被撤销时，存量 demo Graph 会话在 Provider 前降级 Legacy；持久化原因，后续不自动升级。
- 切换用户时不能恢复其他学生的 pending 请求或会话。
- 不扩大 demo-trace 的现有学生/admin 权限；教师继续使用现有受授权 evidence 接口。

### 4.3 观测与生产证据隔离

- 演示 observation 使用 `environment=local|test`、`data_scope=demo`、`traffic_cohort=demo`、`rollout_eligible=false`。
- 保持现有合法 traffic_source 值，本轮使用 organic；不得创建 verification_run_id 或伪造 release_verification。
- 使用独立 demo config 标识，不能复用 `v1.49.9-production-canary` 为演示配置身份。
- 不修改生产聚合器来忽略真实越权 Graph；用测试证明 demo 记录不进入 production/runtime/verified 聚合窗口。
- 演示 manifest 显式 `production_evidence=false`；生产 evidence builder 必须拒绝该 manifest。

## 5. Graph 与事务执行合同

执行路径保持：

`鉴权/演示资格 → 获取一次 ObservationBundle → 现有 Graph → 对照 Legacy → 唯一领域事务提交 → 安全投影`

1. 使用 `GraphActiveTransitionExecutor`，禁止创建只返回“Graph 成功”的伪执行器。
2. Graph 与 comparator 共享同一份观察输入；comparator 不再次调用模型、检索或写库。
3. 实际响应由已选择且通过核验的 outcome 产生，不得只在后台跑 Graph、仍返回 Legacy 却标记 Graph。
4. Graph 异常/不一致沿用现有安全降级；记录实际 selected=legacy。若 Legacy 也失败则明确失败，不伪造成功。
5. 保留 CAS、expected_revision、唯一幂等副作用与业务/observation 原子提交。演示模式不能跳过 schema、内容可信度或写入失败检查。
6. 完成状态沿用独立退出票语义；练习答对、固定数据执行成功都不能直接视为掌握已验证。
7. 本轮只要求诊断元数据在最终提交的 state_json 中与该 revision 一致；不把整段原始运行日志存入响应。

## 6. 真实执行摘要与前端呈现

扩展现有 demo-trace 响应，保留现有 events，新增可空 `execution`；evidence 中复用安全摘要。

拟定字段：

```json
{
  "execution": {
    "schema_version": 1,
    "profile": "local_demo_graph",
    "revision": 2,
    "transition_kind": "lesson_answer",
    "assigned_executor": "graph_active",
    "selected_executor": "graph_active",
    "graph_attempt_status": "completed",
    "visited_nodes": [],
    "fallback_reason": null,
    "input_mode": "deterministic_fixture",
    "production_evidence": false
  }
}
```

上例仅示字段，不是完成证据。成功 Graph 的测试必须断言实际非空 visited_nodes。

- visited_nodes 只来自真正执行过的 Active Graph diagnostics；不能从教学事件标签推算。
- Graph 尝试失败后降级时，Graph 节点标为“尝试轨迹”，不能显示为最终成功路径。
- 节点名、reason code 使用白名单，限制节点数量与字段长度；不暴露提示词、答案键、模型原文、连接信息、学生输入或其他用户数据。
- 模型决策 provenance 与 executor 分开展示：运行 Graph 不代表调用了 LLM；固定输入明确显示“确定性演示”。
- `revision` 对齐页面会话；新会话/新 revision 正在加载时不把旧轨迹当成新轨迹。页面切换后旧响应不能覆盖当前状态。
- 老会话无摘要显示“执行来源未记录”，不能根据当前环境开关补写 Graph 标签。
- 不展示未经测量的逐节点耗时；已有总耗时如保留必须注明统计边界。
- 轨迹读取失败只影响轨迹卡片，辅导仍可继续；提供手动重试，不无限自动轮询。

## 7. 请求意图、幂等与异常恢复

### 7.1 启动

- 用户发起开课时创建一次随机幂等键；对同一 pending 意图重试必须复用相同键与请求内容。
- 请求发出前保存恢复元数据；优先 sessionStorage，按 API origin + actor 隔离，版本化且有过期时间。
- 不在浏览器新增密码、token、模型原文存储；敏感学习原因不放入可持久 pending 对象。
- 用户更换学习目标或明确“重新演示”视为新意图；不能将同一键绑定不同参数。
- 后端检查同键关键输入冲突，返回明确冲突结果；不能返回另一个目标的旧课冒充新请求成功。
- 超时/断网属于结果未知，不证明服务器取消；避免再次无键开课。恢复必须依靠同键重放或精确会话，不用 latest-session 猜测本次请求是否成功。
- 对同时进行中的同键请求，允许返回可识别的处理中状态；不得无界并发重发或提交两节课。

### 7.2 答题

- 保留 expected_revision，并为同一次答题固定幂等键；重试不改变 revision、答案或键。
- 响应未知时先查询当前会话。已推进则同步状态；尚未确认则显示“结果待确认”，不当成失败或鼓励换答案重提。
- revision 未变不代表旧请求已停止；后续只允许同键恢复，继续依赖服务端 CAS/claim 去重。
- 刷新后不猜测用户答案；若不能安全重建 pending 请求，提供只读同步与明确操作提示。
- logout/切换用户后清理本用户 pending；所有恢复请求仍走服务端所有权校验。

### 7.3 请求体验

- 在现有 `fetchApiJson` 上增加可配置 timeout、调用方 AbortSignal 合并与类型化错误；本轮仅接入登录和 AutoTutor 路径。
- 不默认重试 POST。GET 的重试必须有次数/总时长上限；取消前端等待不宣称取消服务端事务。
- 建议交互阈值：等待超过 8 秒显示慢响应说明；读请求 30 秒、开课/答题 90 秒、登录 90 秒超时，可集中配置。
- 这些阈值是前端等待策略，不是后端性能承诺，也不修改生产延迟门禁。
- 401、403、409、429、503、超时、断网分别展示可操作文案；不能将 503/超时显示为密码错误。
- 可选 root-cause 读取需有独立有界等待，失败按现有纯 focus 路径降级，不让辅助读取无限阻塞开课。
- 复用请求状态与健康探测，不要求引入 SWR 等新依赖，不做全站 fetch 改造。

## 8. 免费与真实性要求

- 必需验收使用真实 Graph + 确定性观察输入，不消费在线模型配额。
- 用 transport spy/网络隔离验证禁止外部调用，而非只检查一个 LLM_DISABLED 环境变量。
- PostgreSQL 事务回归在本地或 CI 临时服务执行；不得连接现有 Supabase 运行测试或 seed。
- 真实模型演示是单独可选项，本轮不承诺其零费用，不执行 live probe、不自动切换在线模型。
- 保持现有免费线上站点 Legacy；手动小量检查与本地 Graph 验收分开记载。
- 先前涉及的数据库密码轮换单列运维事项；本 spec 不授权重置、切换连接或读取更多密钥。

## 9. 开发工作包

| 工作包 | 主要修改 | 完成条件 |
|---|---|---|
| A：本地隔离与资格 | 新增 demo policy/runner；execution context、start/answer/recovery 集成 | 默认关闭；仅本地 demo 身份运行 Graph；托管误配拒绝；kill/fallback 生效 |
| B：执行摘要 | Graph outcome diagnostics、state_json、demo-trace/evidence、DemoAgentJourney | 前端显示真实执行器和节点；旧会话兼容；无敏感字段 |
| C：安全恢复 | AutoTutor 页面、公共 API 工具、AuthContext、首页 | 同键恢复、不重复副作用、错误准确、无过期响应覆盖 |
| D：验收与文档 | eval、组件测试、Playwright、脚本与 README | 一条本地启动命令；离线端到端证据；生产合同回归不变 |

按 A → B → C → D 集成，每包独立可测；不要先改生产配置来验证 A。
复用 seed、已有 comparator、事务服务和测试基础设施，不复制教学逻辑或生产 evidence pipeline。

## 10. 测试矩阵与验收

新增测试名称为计划名称，开发时注册到现有 suite runner，不能在未实现前宣称可运行。

| 测试组 | 必测场景 |
|---|---|
| demo policy | 默认关闭；local/test 合法身份；普通学生/教师/匿名拒绝；账户撤销；生产与 Render 伪装 local 拒绝 |
| scope 隔离 | 请求参数伪造 executor/cohort/scope 不生效；demo 不进入生产聚合；demo manifest 不能作为生产证据 |
| Graph 主线 | start、lesson_answer、exit_ticket_answer、recovery_resume 真正经过现有图；节点序列与实际分支一致 |
| 原子性 | 成功只提交一次；observation 写失败业务回滚；重复请求/revision 冲突不重复事件和薄弱点副作用 |
| 降级 | Graph 异常、comparator 不一致、kill、demo 开关关闭；记录 assigned Graph / selected Legacy；不自动升级 |
| 摘要安全 | 敏感字段注入后仍白名单输出；旧状态兼容；非本人/无教师关系越权拒绝 |
| 前端恢复 | 启动提交成功后丢响应；答题提交成功后丢响应；双击；刷新；用户切换；旧请求晚到；409/429/503/断网 |
| 离线保证 | 带有开发者外部凭据的父环境也不会联网；Provider/检索仅一次；comparator 零外部调用 |
| 全流程 | demo 学生答错→重规划→退出票→教师证据；刷新与进程重启恢复；重新演示产生新会话 |

执行要求：

1. 新增 `autotutor_demo_graph_policy_smoke`、`autotutor_demo_graph_flow_smoke`、`autotutor_demo_execution_projection_smoke` 等小型专项，并纳入现有 eval 注册。
2. 复跑既有 Graph parity、active routing、active transaction、recovery、demo authorization、生产准入/聚合相关回归；保留旧断言。
3. frontend lint、unit、build 通过，扩展现有 Playwright Graph 配置；保留 Legacy 主线测试，不能用 Graph 配置替换全部旧覆盖。
4. Playwright 数据库改为每次运行的独立目录，避免现有固定 `/tmp/edu-agent-playwright.sqlite3` 与其他任务串扰；前后端配置必须指向同一轮后端。
5. 故障 E2E 应至少覆盖一次“真实后端已提交，拦截层丢弃响应”，不能所有场景都只返回静态 mock JSON。
6. 新增测试生成文件写临时目录；不要覆盖旧生产回执或将生成时间变化混入历史报告。

最终验收记录至少包含：commit、工作区是否 dirty、测试环境、输入模式、selected executor、通过/失败/跳过数量、外部调用数、报告位置。
跳过不能计入通过；离线通过不能写“真实 LLM 通过”；本地耗时不能写成云端性能改善。

## 11. 交付与回滚

交付物：实现与回归测试、本地启动/复用说明、五分钟演示脚本、简短迁移边界说明，以及独立 demo 验收报告。

演示脚本顺序：

1. 启动隔离后端与前端，进入 Pilot 学生。
2. 开课，确认显示“本地 Graph / 确定性演示”和实际节点。
3. 答错一次，展示分支与教学调整；答对后完成独立退出票。
4. 刷新恢复原会话，再切换教师查看对应证据。
5. 在测试环境演示响应丢失恢复或 kill 降级，并明确来源状态变化。

回滚：关闭新增 demo 开关即可停止新 Graph 演示选择；存量会话按约定安全降级，保留数据与原因。
新增 state_json 字段必须可选、老版本可忽略；不删除 Legacy 执行器，也不改原生产默认配置。

本 spec 仅授权后续开发范围的设计，不代表已执行提交、push、发布、线上切流或数据迁移。
