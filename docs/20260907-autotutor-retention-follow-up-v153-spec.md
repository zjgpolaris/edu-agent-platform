# v1.53 延迟复测发布门禁与课后证据一致性 Spec

日期：2026-09-07

状态：已实现并完成本地验收，详见 [v1.53 交付记录](20260907-autotutor-retention-follow-up-v153-delivery.md)。下文保留设计时的基线与需求。

代码基线：`29d5207fad46fbd921c0539ccdda0d68bfb0958e`（v1.52），已推送 `origin/main`；分析开始时工作区 clean。

## 1. 迭代决策

下一轮优先保证：**课后展示的复测题可以合法提交；没有独立题时明确说明内容缺口；课内通过与隔日留存的状态一致、可追踪。**

v1.52 改善了“今天选什么课”，已经有内容目录、显式目标保护、真实 Graph/Legacy 和完整 review 包。接下来处理真实课后路径中的缺陷，继续复用现有复习和证据服务。

本轮不扩展审核题库，不把普通练习重新标成退出票来绕开独立性，也不增加生产 Canary、在线模型或新的 Agent 框架。

| 候选方向 | 本轮判断 |
|---|---|
| 延迟复测与课后状态 | 优先：已复现展示旧题后提交冲突，以及完成状态与真实排期不一致 |
| 扩大审核内容覆盖 | 后续：有价值，但需要实际内容审核；不能把开发时的合成题冒充教师审核 |
| 真模型教学效果、云端延迟 | 后续：需要模型预算和独立环境证据，不解决当前确定性流程缺陷 |
| 继续扩展规划策略 | 后续：先保障现有教学结果能安全进入后续复习 |

## 2. 基线证据

### 2.1 v1.52 状态

[v1.52 交付记录](20260907-autotutor-content-aware-planning-v152-delivery.md)记录本地验收：后端 9 suite / 31 case，Legacy 浏览器 15 项、Graph 浏览器 7 项、前端 46 项单测，以及 lint、类型检查、build、PostgreSQL 原子事务检查通过。

本次只读查询到 [EduAgent CI 34107896506](https://github.com/zjgpolaris/edu-agent-platform/actions/runs/34107896506)，headSha 与本基线一致。首次查询为 `in_progress`，本次分析结束前再次核查已为 `completed / success`。这证明该提交的 CI 通过，不代表生产 Canary 或真实模型验收通过。v1.52 交付记录中的“未提交/未触发 CI”是开发交付时点的记录，后续提交和推送已完成。

### 2.2 实际代码

| 位置 | 实际行为 | 本轮处理 |
|---|---|---|
| `autotutor_transition_service.py::commit_autotutor_transition()` | independent_correct 与父证据存在时，在业务事务内写入 `retention_due` 和 24 小时后的 due_at | 保留；结果展示应承认已发生的排期 |
| `auto_tutor.py::_finalize()` | 成功分支写 independent_correct 证据，但 `review_action` 仍沿用 `no_new_review_needed` | 修正语义，不在事务提交前虚报成功 |
| `history_review_question.py::build_curated_review_question()` | retention 从 exit_ticket_items 选题，排除历史题号与指纹；无新题返回 None | 保留角色与独立性条件 |
| `review_service.py::_generate_question()` | 上述返回 None 后调用通用 `build_grounded_review_question()`，未传 task_role 和排除集合 | 修复约束丢失；无合法候选必须阻断 |
| `review_mastery_service.py::validate_retention_chain()` | 提交时拒绝未到期、缺少父证据、题号/指纹重复 | 保留最后门禁，不能为让页面成功而放松 |
| `review_service.py::_attach_due_retention_tasks()` | 有内容阻断分支，但新建与已有今日会话的处理不同；阻断状态不在 retention_due 查询内 | 统一首次进入、刷新及补充内容后的恢复 |
| AutoTutor 完成页 | 只识别旧 `verified_correct_evidence_recorded` 标签；当前独立答对可能显示“未改变掌握记录” | 区分已写入即时证据与留存尚待验证 |
| `AutoTutorEvidenceCard` / session evidence | 展示课内 verified，没有当前课后复测状态 | 补充有来源绑定的课后查询，不重写历史掌握结论 |
| `ReviewTab` | 空任务时可显示 scheduled_reviews；有其他任务时没有对应统一排期区 | 等待、到期、阻断均可见，不能被其他任务遮蔽 |

### 2.3 本次隔离复现

复用 `eval/autotutor_demo_graph_flow_smoke.py` 的临时目录、种子数据、真实 ASGI API 和外部网络阻断。测试脚本位于本机 `/tmp/v153_probe.py`、`/tmp/v153_probe_medium.py`，输出 `/tmp/v153-probe.log`、`/tmp/v153-probe-medium.log`；均为临时分析产物，不是版本验收报告。

操作：学生登录 → 显式洋务运动 → 练习答对 → 退出票答对 → 创建今日复习 → 用服务测试时钟推进到 retention_due_at + 1 秒 → 读取复测题 → 尝试提交。没有真的等待 24 小时，没有变更系统时间或生产数据。

| 观察 | 结果 |
|---|---|
| 实际执行器 | `graph_active` |
| AutoTutor 完成结论 | `completed` / `mastery.status=verified` |
| 公共 review_action | `no_new_review_needed` |
| 实际数据库课后状态 | `retention_due`，due_at 为提交时间 + 24 小时 |
| 保留 Pilot 错题数据时 | 起始 easy；到期生成普通 medium practice，说明角色约束在 fallback 中丢失 |
| 清空该隔离学生弱点后 | 起始 `westernization-purpose-practice-2`；退出票 `westernization-purpose-exit-1` |
| 后者到期展示 | 又是 `westernization-purpose-practice-2`，被装饰成 retention |
| 后者提交结果 | `evidence_chain_conflict`；最后提交门禁仍有效，不能声称已经错误计入留存 |
| 外部网络尝试 | 两次复现均为 0 |

当前五个目标各只有一张 exit ticket。AutoTutor 成功完成时已经用过该题，所以按现有 retention 角色规则，这些来源链通常没有剩余合法退出票。本轮正确结果是明确“延迟复测待补充独立题”，不能承诺所有 AutoTutor 课程次日都能完成留存验证。

## 3. 范围与交付结果

必须完成：

1. 修复角色化复习的 fallback 丢约束，禁止展示提交时必然重复的旧题。
2. 到期但无独立题时显示明确阻断，保留原证据、到期时间及待处理目标。
3. 课内通过、已排期、到期可复测、内容阻断和留存通过分别展示。
4. 学生完成页、今日复习、教师证据能核对同一来源链；旧会话与新同目标课程不串线。
5. 真实服务/API、Graph/Legacy、浏览器和事务故障测试进入现有验收体系。

非目标：不改 24 小时规则；不放宽题目独立性、难度或现有发布门禁；不引入普通练习池作为 retention 的隐式替代；不自动生成/审核新题；不为所有历史会话补写或改判掌握记录；不建立多链排课系统或主动通知服务。

## 4. 复测发布合同

### 4.1 约束贯穿所有生成分支

`task_role`、target_difficulty、excluded_assessment_ids、excluded_fingerprints、父链引用必须在每次候选生成、fallback、存量任务 hydration 中保留。角色化调用没有合法审核题时返回现有 blocked 合同；通用生成不能成为跳过角色校验的备用出口。

优先采用最小修复：角色化 curated 选题失败后直接生成安全 blocked 结果。若实现选择继续调用通用 helper，必须证明其完整接收并验证所有约束，不能依靠末端覆盖 task_role。

发布前对当前链重新验证：候选题号、内容指纹不重复；角色来源合法；审核内容仍有效；题干在当前展示方式下可独立作答，不引用被隐藏的材料。复用现有内容模型和质量校验，不复制另一套宽松规则。

提交阶段继续独立检查链、时间和题目。发布与提交之间发生内容撤回、链替换或并发更新时返回明确冲突/阻断，不判题、不写新掌握证据。API 不接受客户端伪造 occurred_at、eligible_at 或 evidence key。

存量已经展示但尚未提交的非法任务需要被撤下或标记不可作答，刷新可恢复到说明页；仅修复新建任务而让旧页面永远 409 不算完成。

### 4.2 缺题可见且可恢复

首次创建今日复习与已有会话附加到期任务遵守同一规则：缺题目标计入阻断说明，不计为一道可作答题或一道已完成题。保留其到期时间与证据引用，不删除弱点、不设置 retained、不把阻断伪装为“没有复习任务”。

内容恢复后允许有界重新核验 blocked 链。可复用今日复习的现有加载路径，但单次最多处理 8 个待复测/阻断目标，不设置客户端自动重试循环；重复读取相同失败状态不得不断递增 revision。没有合法新题仍保持阻断。

合法题恢复时按当前链去重、CAS 附加任务；只有状态/任务实际变化才推进 revision。并发首次进入、并发刷新、跨日新会话都不能为同一链创建可重复计分的复测副本。候选缺失后的状态更新也需要检验链 revision，防止覆盖刚完成的留存结果。

保留现有单个 student/tag 当前链模型：新一节同目标课程可替换当前链；旧任务不能对新链计分。重复提交同一课程的完成请求不得重新排期或推迟 due_at。多条待处理链队列不是本轮范围。

## 5. 课后状态与 API

### 5.1 历史课程与当前复测分开表达

保留现有 `mastery.status=verified` 的课内独立检验语义，文案明确为“本节已通过独立检验”。只有成功的 retention_correct 才展示“间隔复测通过”。等待和缺题均不能撤销历史课内证据，也不能写成稳定掌握。

修正 review_action 和完成页证据标签，使 `independent_correct_evidence_recorded` 展示为“即时检验证据已记录”；兼容旧标签，不声称弱点已移除。排期必须来自已提交状态；副作用回滚、CAS 失败或未知提交结果不显示成功。

建议新增只读 `GET /api/autotutor/session/{session_id}/follow-up`。复用 session evidence 的学生所有权、教师关联关系与管理员权限；不允许仅凭知道 session_id 跨学生访问。响应示意：

```json
{
  "schema_version": 1,
  "session_revision": 3,
  "as_of": "<server UTC time>",
  "follow_up": {
    "status": "scheduled",
    "objective_label": "洋务运动目的",
    "due_at": "<server UTC time>",
    "chain_revision": 0,
    "reason_code": null
  }
}
```

状态白名单：`not_scheduled`、`scheduled`、`due`、`content_blocked`、`retention_verified`、`needs_retrieval`、`superseded`、`unavailable`。`due` 仅表示时间到期，不保证已发布题目；有明确发布结果后才提供进入可作答复测的入口。

服务通过证据引用的 source_session_id 验证来源关系。当前 student/tag 链若属于另一课程，返回 superseded，不能拿另一课程的留存结果补在旧课程名下。历史缺引用、孤立证据或无法可靠关联时返回 unavailable，不猜测、不补写证据。

接口不创建今日复习、生成题目或改写掌握状态。只读状态查询与现有带任务维护行为的 review/today 路径分开；不得在每次渲染老师证据时触发排课写入。不返回答案、选项、私有原始状态、证据键、其他课程 ID 或未授权画像。

课后状态带自己的 chain_revision/as_of，不因跨过 due_at 而增加历史 AutoTutor session revision，不把动态结果混入原幂等重放响应。同一时点的学生和教师投影应一致。

### 5.2 页面

- AutoTutor 完成页：即时通过说明、最早复测时间、课后状态、进入今日复习。缺题时说明“课内检验已通过，延迟复测暂缺独立题”，保留原结果。
- 今日复习：无任务、有其他任务、全部答完时都显示排期/阻断区；服务器时间判定到期，浏览器仅负责格式化时间。
- 教师证据：并列展示本节独立检验与后续留存状态；不能用后续失败覆盖原始课程退出结果。
- 独立加载课后状态，设置超时、取消和旧响应丢弃；失败不遮蔽课程证据。按会话、身份变化重新读取；不无界轮询。
- 请求未决时不能把超时当作未提交或触发重复作答。保留原 review 的 revision/idempotency 协议，冲突后重新同步再操作。

## 6. 实施任务

| 任务 | 优先级 | 主要位置 | 交付 |
|---|---|---|---|
| T1 阻断约束丢失 | P0 | review_service、history_review_question | 角色化 fallback 与存量 hydration 不再发布重复/错角色题 |
| T2 到期阻断和恢复 | P0 | review_service、review_mastery_service | 新建/读取一致、阻断可见、有界重检、链去重与 CAS |
| T3 课后状态投影 | P1，版本必需 | learning router、独立投影/helper | 授权只读 follow-up，来源链与 revision 明确 |
| T4 产品结果一致性 | P1，版本必需 | AutoTutor 完成页、ReviewTab、EvidenceCard | 即时通过与留存分层，排期和缺题可见 |
| T5 回归与验收包 | P1，版本必需 | eval、Playwright、review 脚本、README | 本轮失败复现变成防回归，成功与缺题案例都保留 |

按 T1 → T2 → T3/T4 → T5 集成。预计 3–4 个开发日，按实现工作量估计。优先使用既有 review_mastery_state、weakpoint_evidence、review_sessions 及可选 JSON 字段；本轮预计无需数据库迁移。如果现有字段不能表达必要的来源/恢复信息，显式补 Alembic 与升级测试，不能只在 SQLite 自动补列。

## 7. 测试与退出标准

| 范围 | 必须覆盖 |
|---|---|
| 约束与负控 | curated 返回 None 后不丢 role/排除集合；去掉修复时复现旧题并失败；只换题号但相同指纹仍阻断 |
| 真实 AutoTutor 来源 | easy 和 medium 起始、曾重教、退出票通过后的实际排期；现有内容不足时发布前阻断，不让学生提交后才 409 |
| 成功链 | 保留现有 Review 原生 retrieval → verification → retention 成功主线；AutoTutor 来源可用额外独立题只用明确标注的隔离测试夹具验证，不据此宣称当前题库全覆盖 |
| 时钟 | due_at 前 1 秒、恰好到期、之后；拒绝客户端时间；切日期/时区不能提前算留存 |
| 页面状态 | 空今日复习、有其他任务、已完成任务仍能看到排期/阻断；即时证据标签准确 |
| 恢复与内容 | 已存旧题任务、题撤回/删除、内容恢复、同题换号、无合法新题、重复读取与重新进入 |
| 并发与幂等 | 同链重复/并发完成不重排；并发追加只生成一次；新同目标链替换后旧任务不能改新链 |
| 权限与泄漏 | 匿名、跨学生、无关联教师拒绝；投影无答案/私有键；身份切换与晚到响应不串会话 |
| 事务 | 在排期写入后、附加任务/状态提交前注入故障，证据/排期/会话/副作用一致回滚；SQLite 与真实 PostgreSQL |

验收要求：

1. 新专项注册现有 runner；现有 review mastery、retention scheduler、AutoTutor catalog/content/teaching、parity、授权和原子事务回归通过。
2. 对成功路径与缺题路径都核对数据库证据和掌握状态，不只断言 UI 文案或 status；不能把 content_blocked 当成 retention_verified。
3. Legacy 与真实 Graph 浏览器分别覆盖“完成 → 看见排期 → 到期无独立题安全说明”；测试时钟仅由隔离服务测试入口/fixture 控制，不开放生产调时 API。
4. lint、unit、build 通过；review 包保留 v1.51/v1.52 案例，新增本轮课后排期与缺题说明。完整 PASS 仍需要两种浏览器，缺项/跳过不计通过。
5. 交付记录明确 commit/dirty、输入来源、执行器、通过/失败/跳过、PostgreSQL 范围和远端 CI；不声称真实 LLM 或长期教学效果已经提高。

## 8. 后续与回退

未来若补充审核独立退出票，或明确审核“哪些未见练习可用于延迟复测”的角色政策，可提高 AutoTutor 后续留存覆盖。本轮仅保障现有标准被忠实执行与内容缺口可见，不通过降低规则制造成功率。

回退 UI/课后投影可保留历史字段兼容；不得回退最后提交门禁、删除排期或将已阻断题恢复为可提交。新逻辑失效时显示 unavailable/content_blocked，原始课内证据仍可读。

设计时仅新增 spec 并在临时环境复现；随后已按本 spec 完成开发和本地验收，范围与结果见交付记录。本轮开发未提交、push、发布或修改生产配置。
