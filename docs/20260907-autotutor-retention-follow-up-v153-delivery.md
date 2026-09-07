# v1.53 延迟复测发布门禁与课后证据交付

日期：2026-09-07。对应 [Spec](20260907-autotutor-retention-follow-up-v153-spec.md)。

## 实现

角色化复习选题失败后直接返回内容阻断，不再经通用出题路径丢失 task_role、排除题号和内容指纹。候选再次经过审核状态、AutoTutor 内容校验与复习题质量校验；提交时重新验证当前链、到期时间、题目角色及当前内容。新增请求模型拒绝客户端传入 occurred_at 等额外参数。

保留同一角色内原有难度选择行为，没有扩大 retention 候选池。retrieval 中的 recall 题保留“先答、后展示反馈材料”，并按实际认知动作标为普通提取题，不再错误标为变式题；未降低变式题的认知动作门槛。原复习质量和独立检验主线保持通过。

今日复习的新建与刷新共用任务维护事务。未答旧题若不符合当前链或内容要求会撤下；到期无合法独立题时保留来源、到期时间与阻断状态。单次最多重新生成 8 个待复测/阻断目标，重复失败读取不持续增加 revision。内容恢复后重新核验并附加合法题；维护和提交使用 SQLite 写事务、PostgreSQL 行锁及 CAS，防止并发刷新、跨日任务重复计分。已替换链上的旧任务不更新新链。

新增只读 `GET /api/autotutor/session/{session_id}/follow-up`，复用学生所有权、教师关联和管理员授权。按 source_session_id 和父证据关系返回 scheduled、due、content_blocked、retention_verified、needs_retrieval、superseded 等有限状态。不生成任务、不补写证据、不暴露答案/私有证据键。动态课后状态携带 as_of 和 chain_revision，独立于历史 AutoTutor revision 与幂等重放响应。

课程完成结果修正 review_action 为 retention_scheduled，并识别 independent_correct_evidence_recorded。学生完成页和教师证据显示独立加载的课后状态，区分本节检验与留存验证；今日复习无任务、有其他任务、已完成时都展示排期和缺题说明。新增请求支持超时、取消、手动重试及丢弃晚到响应，教师视角不展示学生复习导航。

本轮复用既有表与 JSON 状态，未新增数据库迁移、审核教材或在线模型调用。现有五个 AutoTutor 目标成功完成后通常没有未用过的独立退出票，因此其正确课后结果是“已排期，到期暂缺独立题”，不是留存通过。

## 验证

基线 `29d5207fad46fbd921c0539ccdda0d68bfb0958e`；验收时工作区 **dirty**，包含本轮实现。输入为本地审核教材、合成学情、隔离 SQLite/PostgreSQL；执行器包含真实 LangGraph Active 和 Legacy。不是该基线 commit 单独通过了本轮测试。

| 检查 | 结果 |
|---|---|
| 完整 review 后端 | 10/10 suite、37/37 case；0 失败/跳过 |
| 新增课后专项 | 6/6 组合案例 |
| Legacy 浏览器 | 16/16；0 失败/跳过/flaky |
| Graph 浏览器 | 8/8；0 失败/跳过/flaky |
| 前端 unit | 16 文件、51 测试通过 |
| lint / TypeScript / production build | 通过 |
| 附加回归 | 9/9 suite 通过：原复习证据/调度/质量/系统、observation、完整 parity、active transaction、review 编排、AutoTutor 原子性 |
| PostgreSQL | 新增复测事务检查和既有 AutoTutor 原子性检查 PASS |
| 来源与格式 | source_stable=true；git diff --check 通过 |

完整包：`/tmp/autotutor-v153-review`，包含源码开始/结束指纹、后端与两类浏览器计数，以及保留 v1.51/v1.52 案例后的新增课后说明。产物是本机临时文件，可按下方命令重建。

新增 `autotutor_retention_follow_up_eval` 覆盖 Graph/Legacy × easy/medium（含重教）、真实排期、到期缺题、只读/权限、普通 fallback 负控、同题换号指纹负控、旧非法题撤下、合成新题恢复、发布后撤回、来源链替换。

`review_retention_checks.py` 在 SQLite 和 PostgreSQL 上使用同一业务检查：状态写入后回滚、附加任务后回滚、提交证据后回滚、并发刷新、跨日重复提交与同键重放。PostgreSQL 使用临时目录与 Unix socket，metadata 建表后运行现有及新增事务检查，结束后已停止；不等于 Alembic 全量升级或 pgvector 演练。

成功留存路径保留原 Review 原生证据链，并使用仅存在于临时内容文件的额外合成退出票验证 AutoTutor 后续恢复。该题不是新增生产审核内容，不能据此宣称现有题库已经覆盖全部延迟复测。

浏览器通过独立的 `eval/retention_e2e_server.py` 注入复习时钟；只读取 Playwright 创建的临时文件，只绑定回环地址。业务应用没有导入该测试启动器，没有生产调时 API，也未改变系统时间。图执行配置与网络隔离继续复用现有本地 Graph demo 工具。

早期回归暴露了事务内重复调用 SQLite schema helper 的锁冲突，以及 retrieval 被一律标为变式后触发认知动作规则的问题；已将弱点读取移到事务外，并修正题型标记。最初还尝试收紧角色内难度 fallback，随后保留既有角色内策略，仅阻断角色/排除约束丢失。最终验收不包含这些早期失败。

验收后补交付说明、README 与 Spec 状态。未提交、push 或部署本轮开发；远端 CI 尚未运行本轮 dirty 改动。基线 v1.52 CI success 不能替代本轮 CI。未重跑全量 core/真实模型或生产性能验收。

## 复现

在已安装 Python/前端依赖和 Chromium、未设置外部数据库变量的仓库根目录：

```bash
.venv/bin/python scripts/build_autotutor_demo_review.py --output /tmp/edu-agent-v153-new-review
```

使用不存在的仓库外目录，等待上一轮结束后再运行。完整模式覆盖后端、Legacy 与 Graph；backend-only 仍只算 partial。

日常演示继续使用 `scripts/dev_autotutor_graph_demo.py`：完成一课 → 查看“本节独立检验”和“课后间隔复测” → 查看今日复习排期 → 切换教师证据。到期缺题路径由上述隔离浏览器测试推进时间验证，不需要等待或修改生产时间。
