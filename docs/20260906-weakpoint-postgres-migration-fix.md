# PostgreSQL weakpoints 迁移缺口修复

基线：`88d0b75`。CI run `34033427877` 的 PostgreSQL 原子性测试在业务弱点写入处失败：
`UndefinedColumn: weakpoints.correct_streak`。尚未走到该 answer 的 observation 拒写断言，
因此不能把它解释为原子性验证通过或简单的偶发超时。

根因：迁移 002 创建 weakpoints 时没有 correct_streak；后续迁移也未补齐。
SQLAlchemy metadata 和 SQLite 的运行时兼容建表/补列逻辑已有该列，掩盖了迁移链缺口。
PostgreSQL 使用 Alembic，不执行 SQLite 补列逻辑。

## 修复

- 新增迁移 018（依赖 017），缺列时新增 INTEGER NOT NULL DEFAULT 0；不改历史迁移。
- 旧行默认 0，已有列及非零 streak 保留；不清空 weakpoints 或重建业务表。
- 启动迁移要求和 runtime readiness head 升到 018。
- readiness 同时核查 weakpoints.correct_streak，版本号正确但列缺失也不得就绪。
- PostgreSQL CI 在执行业务测试前比较涉及原子事务的七张表与 metadata 的列合同。
- PostgreSQL 升级演练加入旧 weakpoints 行及数据指纹，验证升级后保留旧数据。
- 将 postgres_schema_smoke=PASS 移至全部断言之后，避免失败日志中提前出现通过提示。

## 验证与发布边界

本地使用真实 Alembic 链验证 017→018、重复升级、已有列非零值保留、隔离数据库降级/再升级；
对七张业务表做列差异检查。PostgreSQL 原子事务故障测试仍须由新提交的 CI 实际通过。

Render 部署记录显示 88d0b75 已自动部署；这不是 CI 放行证明，也未在本轮直接读取生产库确认缺列。
本轮不执行生产 DDL、不修改 BPS、不启动演练。修复提交并通过 CI 后再部署，检查 018 和实际服务 SHA。
不要靠重跑旧提交、跳过弱点效果或把本次失败标成 pass 绕过验证。

迁移 downgrade 会删除 correct_streak 列及其值，只用于受控数据库回退；不得为回滚应用随意在生产执行。
旧应用的 readiness 精确要求旧版本，保留 018 时可能不就绪，需按兼容性核查安排回退，而非自动降级数据库。
