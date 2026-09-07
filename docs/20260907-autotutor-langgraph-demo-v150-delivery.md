# v1.50 本地 LangGraph 演示交付与验收

日期：2026-09-07。范围：免费个人展示项目的本地隔离演示，不是生产发布。

## 身份与边界

- 基线 commit：`eda3f94acf78bb98fd9bbd40ac9b50aec1fe52f3`；验收时工作区 **dirty**，包含本轮未提交实现。不是该基线 commit 单独通过了这些新增测试。
- 环境：macOS、本地 Python 3.13 虚拟环境、SQLite 临时目录、Chromium；另对专用临时 PostgreSQL 16 执行原子事务回归。
- 输入：`deterministic_fixture`；执行器：真实 `GraphActiveTransitionExecutor`，不是模型调用的替代证明。
- `production_evidence=false`。没有执行在线模型 probe、production-verification、云端配置变更、提交、push 或发布。

## 已实现

1. **隔离入口**：`scripts/dev_autotutor_graph_demo.py` 创建带 manifest 的独立目录、随机本地 JWT 与 SQLite，运行现有 Pilot seed。仅绑定回环地址，拒绝继承数据库连接；移除外部 Provider/追踪配置，后端额外阻断外部连接和 DNS 解析。复用目录不重复 seed，停止时不删除数据。
2. **独立准入**：新增默认关闭的 demo Graph 策略。仅 local/test、DB 当前 active/demo/student、强鉴权及独立数据库可选 Graph；Render 等托管标识、未知环境或冲突配置拒绝。生产 mode=legacy、BPS=0 不变。
3. **真实执行**：复用现有 Graph、单次 ObservationBundle、Legacy comparator、CAS 和唯一领域提交边界，没有引入第二套持久化。Graph 异常/不一致、kill、开关关闭、资格撤销会降级，记录 assigned Graph / selected Legacy 和安全原因，不自动升级。
4. **持久摘要**：profile/scope/summary 保存到已有 state_json。节点来自实际 diagnostics；demo-trace 和教师 evidence 复用白名单投影。旧会话显示未记录，Graph 与确定性模型来源分开，摘要与 revision 对齐。
5. **安全请求**：start/answer 在发出前保存按 API origin + actor 隔离的一小时 sessionStorage 意图；同键同内容恢复、不同开课内容 409。开始请求进程内条带锁去重，保留数据库唯一约束；答题仍使用 revision/CAS。响应丢失后不无键重发，不用 latest-session 猜测 pending 结果。
6. **前端体验**：读 30 秒、变更/登录 90 秒上限，8 秒慢响应说明；明确区分 HTTP、超时、断网与停止等待。取消不宣称撤销服务端事务。新行为显式接入，未接入的旧调用保留原生 AbortError 兼容性。
7. **证据隔离**：observation 为 local/demo/demo/organic、不具备 rollout 资格；生产聚合测试为零 Graph 样本。生产 evidence builder 拒绝 demo manifest，未放宽任何生产门禁。

会话 GET 是只读恢复，沿用所有权检查及数据库权威鉴权，不执行新的教学转换，也不会根据当前开关重写历史执行摘要。下一次教学变更前重新检查 demo 资格并持久化降级。`recovery_resume` 图分支通过真实执行器专项测试覆盖；不把普通 GET 标为一次 Graph 执行。

## 本地验收记录

| 项目 | 结果 |
|---|---|
| backend core | 138 个套件通过、0 个失败、1 个跳过；case 782 通过，9 个随真实模型套件跳过 |
| 新增 demo 专项 | policy、flow、projection 共 3 个通过，已纳入 core/smoke 注册 |
| frontend unit | 14 个文件、42 个测试通过，0 失败/跳过 |
| frontend lint / build | 均通过 |
| Graph Playwright | 5/5 通过，0 失败/跳过 |
| Legacy Playwright | 13/13 通过，0 失败/跳过 |
| PostgreSQL 原子事务专项 | `atomic_observation_transactions_postgresql=PASS` |
| demo 后端外部网络调用 | 0；网络阻断计数断言通过（不推广为全项目所有测试的网络统计） |

核心回归包含 Graph parity、routing、transaction、recovery、canary admission/aggregation、demo 授权及 observation 原子性。新增 flow 还验证同键并发只有一次 Provider 获取、同键目标冲突、新解释器读取持久状态、真实 recovery 节点、Graph 异常/不一致/开关关闭/资格撤销降级及 observation 失败不提交。

Graph E2E 使用真实后端：先完成 start/answer 提交，再由拦截层丢弃响应；刷新后开课同键返回同一 session，答题先 GET 同步 revision，未重复答题 POST。同时覆盖即时双击、答错重规划、独立退出票、教师证据、新会话和内容不足阻断。

本轮实际修复了验收发现的两个回归，而非修改断言使其通过：摘要重建响应导致 reflection 丢失；全局转换 AbortError 导致旧教材页误报加载失败。普通浏览器主线现在等待开课完成才跳转；主动丢响应仍由独立故障用例覆盖。

**未通过/未执行的范围：** `history_character_eval` 因真实模型前置条件跳过，不计入通过。完整本地 `postgres_schema_smoke` 在缺少 pgvector 扩展的断言处失败，因此不宣称完整 PostgreSQL schema 验收通过；本轮所需原子事务检查单独执行通过，原有 CI pgvector 服务及 schema 检查保留。新增 CI Graph 浏览器步骤尚未在远端执行。本地 schema 使用 metadata 创建，不等于生产迁移演练。

本机最终运行日志（临时文件，可能被系统清理，不进入历史生产回执）：

- `/tmp/edu-agent-v150-core-final.log`
- `/tmp/edu-agent-v150-graph-e2e.log`
- `/tmp/edu-agent-v150-legacy-e2e.log`
- `/tmp/edu-agent-v150-build.log`

## 复现

仓库根目录、已安装项目依赖的虚拟环境：

```bash
.venv/bin/python scripts/dev_autotutor_graph_demo.py
PYTHONPATH=backend .venv/bin/python eval/run_core_evals.py --suite autotutor_demo_graph_policy_smoke --suite autotutor_demo_graph_flow_smoke --suite autotutor_demo_execution_projection_smoke --no-report
npm run lint --prefix frontend
npm run test:unit --prefix frontend
npm run build --prefix frontend
E2E_GRAPH_DEMO=1 npm run test:e2e --prefix frontend
npm run test:e2e --prefix frontend
```

浏览器测试前先退出手动演示，避免默认端口冲突；必要时设置 `E2E_PYTHON` 为虚拟环境解释器绝对路径。Playwright 自动创建每轮独立数据库。Graph 与 Legacy 使用不同 Next 构建目录；新增 CI 步骤不替代原 Legacy 用例。

启动、复用、备份与五分钟演示见 README。本轮停止所启动的测试服务，但保留隔离目录供检查；不删除原有工作区数据或用户文档。

## 迁移结论

完成的是 LangGraph 本地教学闭环与恢复/可观测性收尾；已有 LangChain Provider 继续复用。没有全面改写所有 Agent，没有新增 checkpointer，也没有消除免费跨区云数据库的延迟。线上 Legacy、历史 NO_GO 和未完成的生产演练状态保持原样。
