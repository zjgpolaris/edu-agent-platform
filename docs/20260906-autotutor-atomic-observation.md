# AutoTutor 业务与观测原子提交

基线：`872bc1c`。状态：本地实现，未提交/部署，不代表生产 writer rehearsal pass 或 v1.50 GO。

## 事务合同

生产 AutoTutor（包括 Legacy Control）以及所有 Graph / Graph 降级路径，使用现有业务连接写入 observation。
start 的会话 INSERT、学习事件，以及 answer 的 CAS、学习事件、弱点证据、复习记忆、mastery 更新和
finalize 副作用账本，与 observation 在同一个 SQLAlchemy `engine.begin()` 内提交。
不新开嵌套 writer 连接、不在事务中吞掉写入错误。服务层拒绝没有 observation callback 的 Graph 提交。
未配置部署信息的本地 Legacy 继续兼容原 best-effort 观测；本地强制 Graph 测试必须准备 schema 和 commit。

观测 INSERT 失败：业务事务回滚，返回固定 `503 / autotutor_observation_write_failed`；不返回 SQL/参数。
事务退出后独立记录脱敏健康告警并清除本进程 admission cache。即使别的 worker 仍有有效准入缓存，
其 Graph transition 也必须经过相同的事务内写入，不能提交缺少 observation 的业务状态。
answer 的独立 claim 在异常处理时释放；不能假设断网/COMMIT 回执丢失代表一定没提交，重试必须保持同一 key 和载荷。

重放、payload conflict、stale/CAS 失败不新增 observation。缓存更新和 trace/runtime 镜像仍在业务提交之后。
原子性仅覆盖上述数据库业务写入，不覆盖提交前已调用的 LLM/RAG、工具审计或提交后的诊断镜像。

## 保持延迟门禁，禁止以缩短统计边界制造通过

事务内先写入完整业务 observation，但 `status=measurement_pending`。
正常提交后，在原来的 post-commit/mirror 边界捕获延迟，UPDATE 同一 observation 的 latency/status，
不新增记录。总日志耗时包含整个路径；发布 latency 包含事务内 observation 的成本，不包含最后计时 UPDATE。
与旧实现相比不会因为前移写入而漏计 business COMMIT 或 runtime/trace 镜像成本。
新 SHA 必须重建 Control/Graph 基线；仍执行原 `20%` 和 `50ms` 阈值，不复用旧 SHA 的测量数据。

若进程在 COMMIT 后退出，或计时 UPDATE 失败，业务与 observation 已共同持久化，不再回滚/重做业务。
保留 pending 标记；即使健康告警也失败，聚合及生产 Control/Canary/rollback 判定仍以
`observation_latency_incomplete` 阻断。重放不伪造恢复耗时、不清除此标记。
本轮不提供自动补填或删除 pending 的操作，不能缩短失败窗口隐藏该记录。

## 验证

- 共享 SQLite/PostgreSQL 测试通过驱动发送 NULL agent_type，让真实 observation INSERT 触发 NOT NULL 错误。
- 检查 start 没有留下会话/学习事件；answer 在所有业务 effect 与 CAS 之后拒写时，完整回滚。
- observation INSERT 之后再故障，验证 observation 本身也回滚，不是独立提交。
- 同一 key 恢复后仅提交一次；重放/冲突/stale 时 writer 不运行。
- Graph 编排测试检查缓存、claim 清理、健康告警和固定 API 503；计时失败保留业务和 pending 标记。
- 聚合/预检测试检查 Control 和 Graph pending 都阻断放行。
- PostgreSQL 检查接入现有 CI `PostgreSQL migration and Runtime schema`，要求实际 `23502` 错误；本地未配置 PostgreSQL，不能把 SQLite 结果当作 PostgreSQL 已通过。

## 仍未完成的生产发布条件

CI（包括 PostgreSQL）通过后才能部署新 SHA。生产仍保持 Legacy/BPS0，先只读预检；随后按批准的时段
重建基线、核验实际演练、独立绑定测量与演练窗口，并完成 rollback/final evidence。
现有 scoped writer probe 仍只是隔离只读探针，不自动升级为完整生产演练 pass。
