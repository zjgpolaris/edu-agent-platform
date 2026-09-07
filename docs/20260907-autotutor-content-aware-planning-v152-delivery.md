# v1.52 AutoTutor 内容感知规划交付

日期：2026-09-07。对应 [Spec](20260907-autotutor-content-aware-planning-v152-spec.md)。

## 实现结果

自动选课按 weakpoints → weak_topics → recent_topics 的原顺序检查最多 20 个候选，跳过无有效教材、练习或独立退出票的目标。自动选择遵守年级/册次，支持七/八/九年级别名；未知年级与无同册内容安全阻断。显式 focus 保留原目标，不能通过替换目标伪装成功；可用难度只允许保持或降低。

新增 `autotutor_catalog.py`，复用 `prepare_content()` 的内容与独立检验规则，计算合法练习—退出票组合。实际选题限于这些组合，并继续排除 assessment_history。现有五个审核目标可查询，不扩充题库、不承诺无限重教。目录提供版本指纹；单次观察内复用同一内容快照。教材替换、同时间戳改写、撤回、删除、异常结构及读取失败不会沿用旧的可用判断；观察过程中版本变化安全阻断。新会话的练习和退出票提交前再次核验，撤回后不判题、不新增掌握证据。

新增登录只读 `GET /api/autotutor/targets?grade=八年级上册`；不传 grade 可浏览全部册次，空值/未知过滤返回空列表。学生、教师、管理员读取同一非个性化目录，不返回题目、答案、审核人或学生学情。

规划摘要随 LessonStep 状态持久化，通过白名单投影到学生会话、教师证据和演示旅程，并携带 revision。旧会话字段可缺省，无数据库迁移。Graph 与 Legacy 共享观察及转换逻辑，保留原有比较器、CAS、幂等重放与副作用提交边界。

前端开始页和 needs_content 页显示审核目标及册次；选择替代目标生成新开课意图和会话。双击受控，pending 未决时禁止切换；目录请求有超时、取消、旧响应丢弃和手动重试。新增说明展示自动跳过候选或按显式目标安排的原因。

## 验证来源与结果

基线 commit：`927852b8680a2099661feb30a50a5fe9914a856d`，验收工作区 **dirty**，包含本轮实现；不代表该基线 commit 单独通过新增测试。输入为本地审核教材、确定性合成学情和隔离数据库。真实执行器覆盖 LangGraph Active 与 Legacy，未调用在线模型。

| 检查 | 结果 |
|---|---|
| 完整 review 后端 | 9/9 suite，31/31 case；0 失败/跳过 |
| 新增内容目录专项 | 6/6 组合案例，含 API、配对负控、撤回及版本变化 |
| Legacy 浏览器 | 15/15；0 失败/跳过/flaky |
| Graph 浏览器 | 7/7；0 失败/跳过/flaky |
| 前端单测 | 15 文件、46 测试通过 |
| lint、TypeScript、生产 build | 通过 |
| PostgreSQL 业务事务原子性 | PASS |
| `git diff --check` | 通过 |

完整包：`/tmp/autotutor-v152-review-final`；源码开始/结束指纹一致，`source_stable=true`。包内保留 v1.51 教学成功/失败案例，并增加自动跳过甲午战争、显式甲午战争仍阻断的双执行器对照。临时产物可能被系统清理，可重新生成。

附加回归覆盖 observation provider、SQLite 原子事务、transition/full-outcome parity、active transaction、review 编排、false mastery、content blocked API 和自适应难度，共 9 suite 通过。部分旧脚本只输出 PASS，不应把其 suite 数当作 case 数。

PostgreSQL 检查在临时数据目录和 Unix socket 上执行 `metadata.create_all()` 后运行现有 `check_atomic_observation_transactions()`，结果 `atomic_observation_transactions_postgresql=PASS`，完成后已关闭临时数据库。这是实际业务事务检查，不等于 Alembic 全量迁移/pgvector schema 演练。

早期 trajectory 的三个夹具把赤壁、辛亥和鸦片战争默认课配置为不匹配册次；本轮修正夹具年级，保留教学断言，另新增跨年级必须阻断的专项。早期专项误把 kill-switch 下新建 Legacy 会话视为必有 demo execution 投影，已改为同时核对持久化实际 executor 和 Graph 投影。最终测试结果不包含这些早期失败。

验收后只补交付说明、README 和 Spec 状态，并恢复 Next build 自动改写的 next-env 路径，业务代码未变化。本轮未提交、push、触发远端 CI 或部署；v1.51 CI 成功不能替代本轮 CI。未重跑全量 core、真实 LLM 或生产性能/Canary 验收。

## 复现

已安装依赖与 Chromium、且未设置外部数据库变量时，在仓库根目录顺序运行：

```bash
.venv/bin/python scripts/build_autotutor_demo_review.py --output /tmp/edu-agent-v152-new-review
```

使用不存在的仓库外目录，等待上一轮结束；默认完整模式覆盖后端与两种浏览器，`--backend-only` 只算 partial。

演示：运行 `scripts/dev_autotutor_graph_demo.py` → 学生体验 → 打开 `/student/auto-tutor?demo=1&fresh=1&focus=甲午战争影响` → 查看保留目标的阻断 → 选择“洋务运动目的 · 八年级上册” → 查看新会话、规划说明和教师证据。无显式目标自动选择的排序对照见验收包案例。
