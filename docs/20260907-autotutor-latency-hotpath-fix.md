# AutoTutor 生产延迟诊断与请求路径修复

## 事实与边界

失败运行：[34038532594](https://github.com/zjgpolaris/edu-agent-platform/actions/runs/34038532594)，
部署提交 `b1a006e592a9387465f5d0b7f93071be320de884`，配置 `v1.49.9-production-canary`。
100 条 Control / 20 条 Graph，Control p95 17816 ms，Graph p95 24544 ms。
实际停止原因 `verification_safety_stop:active_latency_regression`。
Comparator 20/20 一致、fallback=0、重复副作用=0、观测写入健康。
这不是缺列/内容不可用的重复故障，也不是应通过继续收集 100 条解决的样本不足。

用户提供的三条生产 `autotutor_transition_timing`（同一部署、均 cache_state=refresh）：

| transition_kind | total_ms | admission | admission_schema | business_commit | session_schema | provider | executor |
|---|---:|---:|---:|---:|---:|---:|---:|
| exit_ticket_answer | 11492.512 | 1845.683 | 1138.627 | 5526.150 | 1993.297 | 0.501 | 4.168 |
| lesson_answer | 10432.055 | 1851.259 | 1141.701 | 4549.420 | 2026.219 | 0.966 | 4.232 |
| exit_ticket_answer | 11349.100 | 1843.059 | 1134.739 | 5526.218 | 1988.781 | 0.384 | 5.032 |

这些答题请求主要耗时在数据库相关路径，而非模型或 Graph 内核。
`session_schema` 嵌套于 session_read/session_claim，`observation_write` 嵌套于 business_commit，
`admission_schema` 嵌套于 admission/admission_route；**不可将所有 phase 相加**。
三个非尾部 Graph 答题样本不足以解释全部 p95 差值：仍需同窗口 start_session 尾部日志及相同类型 Control 样本。
不通过分量 p95 相减推断单个请求的瓶颈，不宣称此次修改已通过生产性能门禁。

## 已确认、已复现的代码原因

1. `commit_autotutor_start/transition` 每次调用 `student_profile.init_db()`。
   原实现不仅在 SQLite，而且在 PostgreSQL 执行 5 条 CREATE TABLE、6 条 CREATE INDEX。
   表已存在也仍执行 11 次数据库语句；它位于 business_commit 计时范围内。
2. 会话读取和领取各自调用 `_ensure_session_table()`，每次获取完整列类型反射。
   生产准入刷新也使用完整类型反射，虽然门禁仅消费表名、列名。
   10 秒缓存保持不变；长请求/低频验证容易遇到下一次刷新。
3. CLI 在 Graph>=20 时硬停止延迟回归，但服务端到 committed_graph>=100 才将其放到摘要 blockers。
   造成顶层 `Blockers: none` / `collect_canary` 与实际安全停止矛盾。
   CLI 还漏掉了 `observation_latency_incomplete` 的停止和安全错误白名单。

## 修复

- PostgreSQL profile 初始化改为单次零行 SELECT，验证原有五张表全部声明列；不读取学生行、不建表建索引、不缓存成功结果。
  SQLite 原有本地兼容初始化不变；生产迁移仍由 Alembic 负责。
- PostgreSQL 会话 schema 校验以单次零行 SELECT 验证原有必需列，不跳过校验。
- 准入 schema 读取仅查询 `pg_class`/`pg_attribute` 中的名称及 Alembic 版本。
  与 SQLAlchemy 原有可见、非临时、普通/分区表范围一致，排除系统/已删除列。
  参考 [PostgreSQL pg_attribute 定义](https://www.postgresql.org/docs/16/catalog-pg-attribute.html)。
- 共用无外部依赖的 `autotutor_safety`，服务端摘要与 CLI 按同一规则停止。
  latency floor=20、发布样本下限=100、原始延迟阈值均不变；补齐 pending timing 的硬停止。
- 新增 `business_schema`、`observation_finalize` 分段计时；原发布 latency 计时边界不变。

## 验证

本地安装 PostgreSQL 16.15，启动在私有临时目录的 Unix socket，禁用 TCP，仅操作临时测试库。
在真实 PostgreSQL 上直接执行旧提交的函数和修复后函数：

| 检查 | 旧提交 SQL 次数 | 修复后 SQL 次数 | 修复后 DDL |
|---|---:|---:|---:|
| profile init_db | 11 | 1 | 0 |
| session schema | 4 | 1 | 0 |
| runtime schema（紧邻上一版批量反射） | 5 | 2 | 0 |

共享测试覆盖每次调用都检查（无陈旧缓存）、列删除/重命名、表缺失、版本漂移、异常安全输出。
真实 PostgreSQL 原子观测失败回滚、成功提交、幂等重放/冲突/过期状态测试通过。
本地临时库使用 metadata 建表，**不将其冒充 Alembic 完整升级演练**；现有 PostgreSQL CI 在 Alembic head 后运行相同检查。
新的本地 SQL 契约测试通过 SQLite 执行同一零行 SQL，原生 PostgreSQL 另行验证，不混淆两者。

最终本地结果：专项 12/12 通过；核心回归 135 项通过、1 项 `history_character_eval` 跳过（无失败）；
冒烟 130 项通过、1 项 `history_character_smoke` 跳过（无失败）。外部模型/RAG 跳过不视为通过。
测试自动更新的历史 active/shadow 报告已恢复，不把本次离线重跑的时间戳混入发布证据。
临时 PostgreSQL 实例已关闭；Homebrew 安装的测试二进制及依赖保留，未注册开机服务。

## 发布前必须完成

1. 确认恢复 Legacy/BPS=0；此前失败回执仍为 active_canary/BPS=100，脚本停止不是配置自动回滚。
2. 本地回归及 PostgreSQL CI 通过后再提交/部署；本次开发本身不更改生产环境、不自动 push/部署或重跑。
3. 补齐旧窗口 Graph start_session 尾部和同类型 Control 日志，定位剩余延迟，不假定减少 SQL 次数即可满足 p95 门禁。
4. 新版本重新绑定 commit/config/window，先验证分段耗时确实下降，再按既有门禁验证；不混用旧提交基线、不缩窗排除坏样本、不调整阈值。

## 2026-09-07 部署后核查与下一步

### 已确认的结果

- `eda3f94acf78bb98fd9bbd40ac9b50aec1fe52f3` 的 CI
  [34074641176](https://github.com/zjgpolaris/edu-agent-platform/actions/runs/34074641176) 通过，包含真实 PostgreSQL 迁移与请求路径检查。
- Legacy/BPS=0 小样本诊断
  [34077321513](https://github.com/zjgpolaris/edu-agent-platform/actions/runs/34077321513) 完成 6 条 transition；
  Control p50=6516 ms、p95=14252 ms。它不是 100 条正式基线，更不是 Canary 发布通过。
- 用户提供的新版本 Legacy 日志：start 总耗时 10408.296 ms，其中 provider=6017.398 ms；
  exit_ticket_answer=7081.116 ms、lesson_answer=6092.104 ms。
  答题 provider 均低于 1 ms，business_schema 约 565 ms，observation_write 约 285 ms。
  provider 包含观察数据准备，不等同于纯模型调用。
- 从已登录的 Render Settings 页面确认：后端在 Oregon (US West)，实例为 Free。
- 从同一服务 Environment 页的实际 `DATABASE_URL` 仅提取主机与端口：
  `aws-1-ap-southeast-2.pooler.supabase.com:6543`。没有保存连接用户名、密码或完整 URI。
  [Supabase 地区表](https://supabase.com/docs/guides/platform/regions) 将 `ap-southeast-2` 定义为 Sydney；
  [连接文档](https://supabase.com/docs/guides/database/connecting-to-postgres) 将共享 pooler 的 6543 定义为 transaction mode。
  本次尚未核验 `DIRECT_URL`，不能假定其类型或地区正确。

### 判断与不确定性

已确认应用到数据库 pooler 是 Oregon → Sydney 的跨洲路径。
多次串行数据库调用会放大往返成本；该部署拓扑与日志的稳定耗时阶梯吻合，是需优先处理的延迟风险。
但尚未从 Render 实例测量纯网络 RTT、连接池排队和数据库执行时间，不能把 285 ms 直接标为实测 RTT，
也不能宣称它单独解释了全部 Graph/Control p95 差值。
Free 冷启动与预热后持续数据库延迟需要分开分析。
6543 不是天然错误；持久后端可以评估 session/direct 模式，但改端口不会消除跨洲延迟，不能盲改。

### 下一步执行顺序（外部变更待授权）

1. 保留 Legacy/BPS=0，不自动重跑完整 Canary，不降低性能阈值。
2. 用户选择同地区部署路线：
   - 保留当前 Render 后端，评估将数据库迁至 Oregon；涉及数据迁移、数据驻留变化与可能的新资源费用。
   - 保留 Sydney 数据库，评估可部署在 Sydney 的后端托管；涉及新托管资源和 API 地址切换。
   [Render 地区说明](https://render.com/docs/regions) 当前不含 Sydney，且现有服务不能原地改地区。
   仅将后端搬到 Singapore 仍不是同地区，不能承诺解决问题。
3. 获得路线与资源授权后，先核验配额、费用、备份恢复、数据库扩展/角色/序列/数据量及其他 Supabase 依赖；
   准备只读或隔离验证环境。保留原服务与数据库，不做双写，不删除旧资源。
4. 在目标实例使用不读取业务数据的数据库连通性/往返诊断，分别记录预热连接、事务及 SQL 耗时；
   核验 session/direct 容量与迁移 advisory lock 兼容性，禁止输出 DSN/凭据。
5. 制定维护窗口、停写与最终同步方案，经切换确认后才修改 `DATABASE_URL`/`DIRECT_URL`。
   若 API 地址变化，同时核对 Vercel `NEXT_PUBLIC_API_BASE_URL`、CORS 与 GitHub
   `AUTOTUTOR_PRODUCTION_API_BASE` / `AUTOTUTOR_PRODUCTION_ALLOWED_HOSTS`。
   新库接受写入后不能仅改回旧 URL 当作回滚，必须先处理新写入的数据一致性。
6. 验收 schema、鉴权、幂等性、原子观测与 Legacy 小样本，再为新拓扑重新建立正式 Control 基线；
   后续 Canary/回滚验证绑定相同提交、配置和受控窗口，不混入旧拓扑样本。

本次仅补充诊断文档，未创建资源、迁移数据、切换生产连接、升级付费计划或重新触发验证。
