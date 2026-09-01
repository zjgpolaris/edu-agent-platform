# EduAgent Agent Demo 主线收敛与可观测演示 v1.46 Spec

**创建时间：** 2026-08-31

**状态：** Proposed · 待开发

**目标版本：** v1.46.0

**优先级：** P0 Demo 可用性与叙事闭环；P1 运维界面和 CI 降噪

**适用定位：** 个人用于展示 Agent 工程能力的单环境 Demo，不以企业级多租户、生产灰度或不可变发布为目标

**分析基线：** `main@c3b7340edcecf7a9b6cd6f06c6a4fb941d812ae6`，生成本文时工作区无未提交修改

**关联文档：**

- `docs/20260821-autotutor-content-validity-v135-spec.md`
- `docs/202608280000-agent-runtime-langgraph-boundary-adr.md`
- `docs/20260830-llm-provider-langchain-migration-v144-spec.md`
- `docs/20260831-immutable-deployment-llm-evidence-v1452-spec.md`（已归档，不作为本轮发布要求）
- `README.md`

---

## 0. 决策摘要

EduAgent 已具备 AutoTutor 状态机、受限计划、RAG、Tool Governance、Trace、Eval、AgentOps、认证和 PostgreSQL 等能力。下一迭代不再横向增加 Agent、页面或生产基础设施，而是把已有能力收敛为一条可在 5 分钟内稳定完成、能够证明“这是 Agent 而不是普通聊天”的演示主线。

本轮作出以下决策：

1. **演示主线以 AutoTutor 为唯一主角。** 核心故事固定为“薄弱点 → 教学计划 → 作答 → 判断 → 反思重规划 → 退出票 → 学习证据”。随问、教师端和 Eval 作为补充证据，不再与 AutoTutor 争夺首页主叙事。
2. **统一为一套 Pilot Demo 合同。** 首页、README、种子脚本和 E2E 统一使用 `pilot-student`、`pilot-teacher` 及 `seed_pilot_demo.py`；旧 `demo-student` 只做兼容迁移，不再作为现行文档入口。
3. **生产 Demo 展示脱敏后的 Agent 决策轨迹。** 不直接打开 raw trace，不暴露 Prompt、模型输入输出、Token、密钥、异常堆栈或其他用户数据。
4. **演示轨迹必须按会话授权。** 新增 AutoTutor 会话级轨迹投影接口；不能因为知道 `trace_id` 就读取任意轨迹。
5. **Demo readiness 只对适用能力负责。** Runtime v2、rollout evidence、不可变镜像和 capability manifest 在关闭时标记为 `not_applicable`，不得把健康的 Demo 标为 `degraded`。
6. **Eval 默认展示作品集指标。** 生产 rollout、verified cohort、48 小时观察等信息在 Runtime v2 关闭时隐藏，保留在高级诊断中而不是删除底层能力。
7. **CI 必须证明完整主线。** 新增确定性的 AutoTutor 浏览器 E2E，覆盖一次答错、反思重规划和退出票闭环；默认 CI 不依赖真实外部 LLM。
8. **停止每日真实证据任务。** `agent-evidence.yml` 改为仅手动触发，避免个人 Demo 每天消耗 Actions 和模型 Token。

目标演示链路：

```text
首页「体验 Agent 主线」
  → 自动登录 pilot-student
  → 打开预置薄弱点的 AutoTutor
  → 展示本节目标与计划
  → 演示者故意答错
  → judge 判断 + reflect 错因 + re-plan 调整
  → 完成重教后的验证
  → 完成独立 exit ticket
  → 展示掌握证据 / 错题与复习状态变化
  → 可选：管理员进入 Eval 查看聚合证据
```

---

## 1. 当前项目基线

### 1.1 产品规模与定位不匹配

截至基线版本，仓库包含：

| 项目 | 数量 |
| --- | ---: |
| Next.js `page.tsx` | 52 |
| FastAPI 路由 Endpoint | 152 |
| `eval/` 顶层 Python 脚本 | 140 |
| `docs/` 文档 | 101 |
| 学生端桌面导航叶子入口 | 16 |
| 教师端桌面导航叶子入口 | 8 |

这些能力适合作为工程资产，但不应全部成为演示者必须解释的产品主线。v1.46 不进行大规模删除，而是通过入口、默认视图和演示合同收敛认知负担。

### 1.2 已具备的核心 Agent 资产

当前无需重写的能力包括：

- AutoTutor：`plan → act → observe → judge → reflect → re-plan → exit_ticket → finalize`；
- 内容有效性门禁和独立退出票；
- 学习事件、薄弱点、掌握度与教师辅导效果回流；
- Learning Assistant 最多 3 步受限计划和高风险工具确认；
- RAG source、verification summary 和失败归因；
- Runtime run、trace、tool audit 和 AgentOps 聚合；
- LangChain Provider Registry 与百炼模型接入；
- PostgreSQL schema、认证和常规 CI。

本轮必须复用这些资产，不创建第二套 Demo Runtime、第二套 AutoTutor 或第二套 Trace Store。

### 1.3 演示账号存在双重合同

当前存在两套公开口径：

| 位置 | 学生账号 | 教师账号 | 初始化脚本 |
| --- | --- | --- | --- |
| README 顶部与旧主线 | `demo-student / demo123` | 未统一 | `seed_demo_student.py` |
| 首页一键体验与 E2E | `pilot-student / pilot123` | `pilot-teacher / pilot123` | `seed_pilot_demo.py` |

`seed_pilot_demo.py` 已同时准备学生薄弱点、作业、欠交、质检盲区和 AutoTutor 效果证据，覆盖范围明显更完整，应成为唯一现行 Demo 数据合同。

### 1.4 文档主线与权限边界不一致

README 当前要求学生在演示末尾打开 `/eval`。实际 API 和页面已要求管理员权限，核心 E2E 也必须通过 `bootstrap_admin.py` 创建管理员后才能访问。

现有 `AuthGuard` 在已登录用户访问首页时只区分 teacher 和其他角色，admin 会被归入 student 跳转分支。v1.46 必须统一三角色跳转合同：

```text
student → /student
teacher → /teacher
admin → /eval
```

### 1.5 核心 Agent 轨迹在线上不可见

AutoTutor 当前仅在以下条件同时满足时展示开发轨迹：

```text
NODE_ENV=development
query.debug=1
```

这保护了学生界面，但导致线上 Demo 无法展示最有区分度的 Agent 决策。README 宣称的 reflect / re-plan / TraceTimeline 在正常线上演示中不可见。

本轮不能简单移除 `NODE_ENV` 判断，因为 raw trace 可能包含内部字段，且通用 `/api/traces/{trace_id}` 当前只要求登录，没有按 AutoTutor 会话所有者验证。

### 1.6 浏览器验收只覆盖“能打开”

当前 E2E 已覆盖：

- Pilot 学生/教师一键登录；
- 学生复习、作业、智能练习和随问；
- 随问受限计划和高风险确认；
- AutoTutor 正常内容展示；
- AutoTutor 内容不足时安全阻断；
- 管理员 Eval 页面。

尚未覆盖 README 的核心演示承诺：

```text
答错 → judge → reflect → re-plan → 重教 → exit ticket → evidence
```

### 1.7 线上 readiness 语义与 Demo 定位冲突

基线部署的 `/api/ready` 实测：

- HTTP 200；
- `ok=true`；
- `failed_required_checks=[]`；
- 认证、数据库、LLM 配置和 RAG 均正常；
- 但 `status=degraded`。

造成 degraded 的 warning 为：

- `llm_capabilities`：manifest missing；
- `latest_eval`：容器内没有最新报告；
- `rollout_evidence`：Runtime v2 disabled。

这些检查在企业级 rollout 中有意义，但在当前单环境 Demo 中不适用。关闭的能力不应产生告警。

### 1.8 Eval 默认信息密度过高

当前 AgentOps 面板同时展示 20 余个指标，并默认展示 Runtime Rollout、Control 样本、Verified Cohort、Shadow Runs、Provenance、Evidence 和 48 小时观察建议。

这会产生两个问题：

1. 演示者无法在短时间内讲清楚最重要的 Agent 证据；
2. 已停用的生产能力长期显示 `missing`、`unknown` 或 blocker，降低可信度。

---

## 2. 用户、场景与核心需求

### 2.1 主要用户

本轮主要用户不是大规模真实学校用户，而是项目作者本人在以下场景中的演示需求：

- 向面试官或技术同行展示 Agent 工程能力；
- 展示 AutoTutor 与普通 Chatbot 的区别；
- 快速说明 RAG、Tool、Trace、Eval 和学习证据如何形成闭环；
- 在免费或低成本托管环境中稳定运行。

### 2.2 演示者需求

1. 打开首页后不需要记忆多套账号和路径。
2. 两次交互以内进入核心 Agent 主线。
3. 能够主动制造一次错误，稳定触发 reflect / re-plan。
4. 能看到用户可理解的 Agent 决策，而不是原始日志。
5. 能说明最后产生了什么学习证据。
6. 演示前可以用一条命令恢复固定数据。
7. 线上健康页不会因已停用的企业功能持续显示 degraded。

### 2.3 观看者需求

1. 在 5 分钟内理解 Agent 的目标、计划、工具、判断和状态变化。
2. 明确看到系统不是一次 Prompt 直接输出完整答案。
3. 明确看到失败时会调整，而不是机械重试相同内容。
4. 明确看到结论有来源、题目有门禁、掌握有独立证据。
5. 不需要理解 rollout、cohort、image digest 等生产运维概念。

---

## 3. 目标与非目标

### 3.1 P0 目标

1. 建立唯一、可重复、可验证的 Demo 数据合同。
2. 首页一键进入预置薄弱点的 AutoTutor 演示。
3. 在线上环境安全展示脱敏的 AutoTutor 决策轨迹。
4. 完整覆盖答错、反思重规划、退出票和证据写入的 E2E。
5. 修正 student / teacher / admin 的路由和文档边界。
6. 让 `/api/ready` 只对当前适用的能力报告 degraded/failed。
7. 保持现有业务 API、Runtime、内容门禁和数据模型不被重写。

### 3.2 P1 目标

1. 将 Eval 默认视图收敛为 6–8 个作品集指标。
2. Runtime rollout 信息仅在启用时或高级诊断模式下出现。
3. 真实 LLM / blind evidence workflow 改为手动触发。
4. README 提供一条与实现完全一致的 5 分钟演示脚本。

### 3.3 非目标

- 全面迁移 LangSmith；
- 替换现有 Langfuse 或自研 Trace；
- 扩大 LangGraph Runtime v2 覆盖范围；
- 开启 production shadow、active rollout 或 verified cohort；
- 恢复不可变镜像、staging、deploy hook 或 canary 工作流；
- 新增学科、新 Agent、语音或多模态能力；
- 大规模删除 52 个页面或历史 API；
- 建设多租户、学校组织架构或企业权限系统；
- 用真实 LLM 作为默认 CI 的硬依赖；
- 声称离线 E2E 等价于真实学生学习效果。

---

## 4. 信息架构与演示脚本

### 4.1 首页入口

首页学生体验按钮调整为明确的主线入口：

```text
主按钮：体验 Agent 自主辅导
说明：从薄弱点出发，观察计划、判断、反思与退出票
```

点击后：

1. 使用 `pilot-student / pilot123` 登录；
2. 跳转到：

```text
/student/auto-tutor?focus=洋务运动目的&demo=1
```

3. 页面展示“演示讲解模式”引导；
4. 不自动替用户提交答案，不伪造运行过程。

教师体验按钮继续进入 `/teacher`，说明文案强调“查看 Agent 形成的班级证据和待处理任务”。

### 4.2 五分钟标准脚本

演示脚本固定为：

| 时间 | 操作 | 要证明的能力 |
| --- | --- | --- |
| 0:00–0:30 | 首页一键进入 AutoTutor | Demo 可达性、预置薄弱点 |
| 0:30–1:00 | 查看目标和计划 | Agent 读取画像并规划 |
| 1:00–2:00 | 故意答错固定题目 | judge、错因识别 |
| 2:00–3:00 | 查看 reflect / re-plan 并完成重教 | 运行时状态变化，不是固定流水线 |
| 3:00–4:00 | 完成独立 exit ticket | 掌握证据不是同题复用 |
| 4:00–4:30 | 查看学习证据摘要 | weakpoint / mastery / review 回流 |
| 4:30–5:00 | 可选打开 Eval | Trace、工具、核验和延迟聚合 |

### 4.3 页面引导状态

AutoTutor 演示讲解区采用以下阶段：

```text
ready
planning
teaching
waiting_answer
judging
reflecting
replanning
reteaching
exit_ticket
evidence_written
completed
blocked
```

引导只描述当前已发生的事实，不提前把未来步骤标记为完成。

### 4.4 完成后的证据摘要

课程完成后显示最小证据摘要：

- 本节学习目标；
- 首次作答结果；
- 是否发生 reflect / re-plan；
- 退出票是否通过；
- `practice` 或 `verified mastery` 层级；
- 薄弱点/复习计划是否更新；
- 会话 ID 的短格式；
- “查看 Agent 决策过程”入口。

不得把 `content_blocked`、无效题或未通过独立退出票的会话显示为 verified mastery。

---

## 5. Demo 账号与种子数据合同

### 5.1 唯一现行账号

```text
教师：pilot-teacher / pilot123
学生：pilot-student / pilot123
辅助学生：pilot-student-b/c/d / pilot123
管理员：由 bootstrap_admin.py 创建，不在仓库固定公开密码
```

所有 Pilot 账号保持 `traffic_cohort=demo`，不得加入 verified rollout cohort。

### 5.2 唯一种子入口

现行入口：

```bash
PYTHONPATH=backend python3 scripts/seed_pilot_demo.py
```

要求：

- 可重复执行；
- 不创建重复作业或重复通知；
- 重置主学生的演示学习事件和 AutoTutor 演示证据；
- 保证当天有可执行复习任务；
- 保证教师端存在待复核、欠交和质检盲区；
- 不打印数据库连接串、Hash、JWT 或第三方密钥；
- 最终输出学生、教师账号、主路径和 assignment ID；
- 非 Demo 账号和真实学习数据不受影响。

### 5.3 旧脚本处理

`scripts/seed_demo_student.py` 采用以下二选一方案，实施时优先 A：

- **A（推荐）：** 删除脚本，并同步删除所有引用；
- **B（兼容）：** 保留薄包装，输出 deprecation 提示后调用 `seed_pilot_demo.seed()`。

不允许继续维护两份独立数据逻辑。

### 5.4 演示重置边界

本轮只提供 CLI 重置，不新增公开 HTTP reset endpoint。原因：

- 项目由作者本人演示，不需要访客自助重置；
- reset 会覆盖共享 Demo 数据，属于高风险副作用；
- CLI 已满足部署后或演示前恢复数据的需要。

如未来开放多人公开试用，再单独设计 session-isolated demo workspace，不在本轮实现。

---

## 6. 认证与角色跳转合同

### 6.1 登录响应扩展

`POST /api/auth/login` 在保持现有字段的基础上增加：

```json
{
  "token": "<jwt>",
  "role": "student",
  "actor_id": "pilot-student",
  "display_name": "Pilot 学生A",
  "demo_mode": true
}
```

`demo_mode` 由服务端账户的 `traffic_cohort == "demo"` 计算。前端不得仅凭用户名字符串判断 Demo 身份。

前端 `AuthUser` 增加：

```ts
demoMode?: boolean;
```

兼容历史 localStorage：字段缺失时按 `false` 处理。

### 6.2 服务端权威性

`demo_mode` 客户端字段只控制 UI 展示，不作为后端授权依据。所有 Demo trace、会话和数据访问仍由后端根据当前 Token 解析出的 `Actor` 决定。

### 6.3 路由跳转

统一函数：

```ts
function homeForRole(role) {
  if (role === "admin") return "/eval";
  if (role === "teacher") return "/teacher";
  return "/student";
}
```

首页登录、AuthGuard 已登录跳转和 401 后重新登录必须复用同一逻辑，避免各自维护分支。

### 6.4 `/eval` 权限

- `/eval` 继续保持 admin-only；
- README 不再要求学生账号直接访问 `/eval`；
- 教师和学生访问时跳转回各自首页或显示明确 403；
- 不在公开仓库写入固定管理员密码；
- E2E 使用 `bootstrap_admin.py` 创建测试管理员。

---

## 7. 安全的演示轨迹

### 7.1 原则

演示轨迹是面向观看者的领域投影，不是 raw trace viewer。

允许展示：

- 阶段名称；
- 用户可理解的阶段说明；
- 成功、失败、等待、阻断状态；
- 是否使用 RAG / 内容包；
- source 数量；
- 是否触发 reflect / re-plan；
- 耗时；
- exit ticket 和 evidence 状态。

禁止展示：

- system/developer prompt；
- 完整模型输入和未脱敏输出；
- API key、JWT、Cookie、Authorization header；
- 数据库连接串；
- Python traceback；
- 内部文件路径；
- 其他学生 ID、会话或 trace；
- hidden chain-of-thought；
- provider 原始 request/response body。

### 7.2 新 API

新增：

```http
GET /api/autotutor/session/{session_id}/demo-trace
Authorization: Bearer <token>
```

授权规则：

1. student 只能读取 `session.student_id == actor.actor_id` 的会话；
2. 仅当服务端 `actor.traffic_cohort == demo` 时返回 `enabled=true`；
3. admin 可读取用于演示诊断；
4. teacher 本轮不自动获得学生 raw/demo trace 权限；
5. 会话不存在返回 404；越权返回 403；
6. 不接受客户端传入任意 `trace_id`。

响应合同：

```json
{
  "enabled": true,
  "session_id": "session-id",
  "status": "in_progress",
  "events": [
    {
      "sequence": 1,
      "phase": "plan",
      "label": "制定教学计划",
      "status": "completed",
      "summary": "根据薄弱点选择了 1 个主目标",
      "duration_ms": 84,
      "occurred_at": "2026-08-31T10:00:00Z"
    }
  ]
}
```

### 7.3 事件映射

领域投影至少支持：

| 内部事件/状态 | Demo phase | 用户文案 |
| --- | --- | --- |
| plan | `plan` | 制定教学计划 |
| evidence/retrieval | `observe` | 检索并核验教学依据 |
| teach/act | `teach` | 生成针对性讲解 |
| answer/judge | `judge` | 判断作答并识别错因 |
| reflect | `reflect` | 反思当前教学是否有效 |
| re_plan | `re_plan` | 调整后续教学计划 |
| exit_ticket | `exit_ticket` | 执行独立退出票检验 |
| learning event write | `evidence` | 写入学习证据 |
| finalize | `finalize` | 完成本节辅导 |
| content_blocked | `blocked` | 内容证据不足，安全停止 |

未知内部事件默认忽略，不把内部 event name 原样输出到用户界面。

### 7.4 数据来源

投影优先从 AutoTutor session state、受控 runtime event 和 learning event 构建。不得通过让 LLM 总结 raw trace 生成演示文案。

文案必须确定性、可测试，避免演示轨迹本身产生额外模型调用和失败点。

### 7.5 前端呈现

新增 `DemoAgentJourney` 组件：

- 在 `demo=1` 且服务端 `demo_mode=true` 时展示；
- 桌面端作为右侧或折叠面板；
- 移动端作为课程进度下方折叠区；
- 当前阶段高亮；
- 已完成阶段显示简短结果；
- 未发生阶段不伪造时间或状态；
- `content_blocked` 走安全停止分支；
- 网络失败不阻断 AutoTutor 主任务，只显示“决策轨迹暂不可用”。

### 7.6 raw trace 边界

现有开发环境 `?debug=1` raw TraceTimeline 可以继续保留，但必须满足：

- 仍只在 development 生效；
- 不作为线上 Demo 的数据源接口；
- 通用 trace API 的所有权问题单独记录为安全整改；若本轮修改该接口，必须保持现有测试和管理员诊断能力。

---

## 8. AutoTutor 演示主线合同

### 8.1 固定主目标

默认演示目标使用：

```text
洋务运动目的
```

选择理由：

- 已在 Pilot weakpoint 数据中；
- 已有审定内容与固定题目；
- 易于构造有意义的错误选项；
- 适合短时间解释 purpose 与影响的区别；
- 现有学习助手 E2E 也使用该知识点，可复用上下文。

如该目标无法通过内容门禁，页面必须安全阻断，不能自动切换到未说明的其他主题以伪造成功演示。

### 8.2 答错分支

首次作答必须存在至少一个稳定、可解释的错误选项，用于演示：

- judge 判定错误；
- misconception 或错误维度；
- reflect 说明原讲解哪里需要调整；
- re-plan 产生与初始讲解不同的后续动作；
- 第二题或重教题不得与首次题完全相同。

不得仅把 `attempt_count += 1` 包装成 re-plan。

### 8.3 退出票

退出票继续遵守 v1.35：

- 与练习题不是同一 assessment item；
- 有 answer-bearing evidence；
- 通过验证器；
- 只有有效 practice 与独立 exit ticket 均通过，才能产生 verified mastery；
- 未通过时保留过程证据，但不提升掌握状态。

### 8.4 Demo 完成状态

演示主线的终态：

| 状态 | 含义 | UI |
| --- | --- | --- |
| `completed_verified` | 完成且独立退出票通过 | 绿色完成 + 掌握证据 |
| `completed_practice_only` | 完成练习但未形成 verified mastery | 中性完成 + 继续复习 |
| `content_blocked` | 内容证据不足 | 安全阻断说明 |
| `failed_recoverable` | 临时依赖失败 | 保留进度 + 重试 |
| `cancelled` | 用户取消 | 不写掌握证据 |

---

## 9. Readiness 语义收敛

### 9.1 检查状态模型

每个 readiness check 增加明确适用性：

```text
pass
warn
fail
not_applicable
```

为保持兼容，现有 `ok` 字段保留。建议响应补充：

```json
{
  "status": "ok",
  "required_checks": ["auth_configuration", "database", "llm_config"],
  "failed_required_checks": [],
  "warning_checks": [],
  "not_applicable_checks": ["llm_capabilities", "rollout_evidence"],
  "checks": {
    "rollout_evidence": {
      "ok": true,
      "applicable": false,
      "status": "not_applicable",
      "reason": "runtime_disabled"
    }
  }
}
```

### 9.2 默认 Demo 规则

默认 `/api/ready`：

- required：生产认证配置、数据库、LLM 基础配置；
- RAG 继续返回诊断，但只有 `require_rag=true` 时 blocking；
- external dependencies 只有 `require_external=true` 时 blocking；
- Runtime schema / observations 只在 `require_runtime=true` 时 blocking；
- Runtime 未启用时 rollout evidence 为 `not_applicable`；
- optional capability flags 全关闭且不要求 manifest 时，LLM capability manifest 为 `not_applicable`；
- 容器内没有 eval report 不再默认导致 degraded，标记为 `informational` 或 `not_available`；
- 只有可采取行动的非阻断异常进入 `warning_checks`。

### 9.3 高级检查保持

以下调用继续保留严格语义：

```text
/api/ready?require_rag=true
/api/ready?require_external=true
/api/ready?require_runtime=true
```

`require_runtime=true` 时，runtime schema、deployment provenance、capability manifest、rollout evidence 和 observation health 可继续 fail-closed。

本轮只是改变默认 Demo 口径，不删除高级诊断能力。

### 9.4 Demo 成功条件

默认线上 readiness 满足以下条件时必须返回：

```json
{
  "ok": true,
  "status": "ok",
  "failed_required_checks": [],
  "warning_checks": []
}
```

不得因为明确关闭的 Runtime v2 或未配置的生产 evidence 返回 degraded。

---

## 10. Eval / AgentOps Demo 视图

### 10.1 默认指标

Eval 页默认“Demo 概览”只突出：

1. Agent 任务完成率；
2. AutoTutor reflect / re-plan 次数；
3. exit ticket 完成率与 verified mastery；
4. RAG / 内容核验通过率；
5. Tool 调用成功率与确认次数；
6. Trace 覆盖率；
7. LLM fallback 率；
8. p95 latency。

无样本时显示“暂无演示样本”，不得显示 0% 造成错误含义。

### 10.2 高级诊断

以下指标移入折叠的“高级诊断”：

- 数据口径细分；
- semantic router shadow；
- planner active rate；
- repair rate；
- LLM model 分布；
- RAG diagnosis / failure stage；
- Runtime rollout。

### 10.3 Runtime Rollout 可见性

Runtime Rollout 面板仅在以下任一条件成立时展示：

- deployment `runtime_enabled=true`；
- URL 明确包含管理员高级诊断开关；
- 后端返回非空且可采取行动的 runtime blocker。

Runtime 关闭时不得在默认视图展示：

```text
0/100 control samples
verified cohort missing
evidence missing
run rollout evidence
```

### 10.4 权限与数据

- `/eval` 继续 admin-only；
- Demo 概览不得放宽底层 Eval API 权限；
- 页面不内嵌管理员账号或密码；
- 默认只读加载不触发真实 LLM eval；
- “运行评测”继续需要管理员主动操作。

---

## 11. CI 与工作流调整

### 11.1 保留

- `ci.yml` 的 frontend lint / unit；
- release gate；
- PostgreSQL migration/schema；
- core browser E2E；
- `keep-alive.yml`，因为 Render 免费实例冷启动会直接影响现场演示；
- 手动真实 LLM / blind evidence 能力。

### 11.2 调整

`.github/workflows/agent-evidence.yml`：

- 删除每日 `schedule`；
- 保留 `workflow_dispatch`；
- 默认 `release_required=false`；
- README 说明真实模型证据只在准备演示或 Provider 变更后手动运行。

### 11.3 不恢复

不得恢复以下已删除链路：

- GHCR immutable image release；
- staging environment deploy；
- Render deploy hook；
- runtime rollout evidence 自动放量；
- production canary/promotion contract。

### 11.4 默认 CI 的外部依赖边界

新增完整 AutoTutor E2E 必须：

- 使用 SQLite E2E 数据库；
- 使用 `seed_pilot_demo.py`；
- 使用项目审定内容包或确定性替身；
- 不要求 `BAILIAN_API_KEY`、Jina API 或外部网络；
- 在 60 秒单测超时内完成；
- 失败时输出当前 UI 阶段、session ID 和最近脱敏 Demo event。

---

## 12. 测试与验收矩阵

### 12.1 后端确定性测试

新增或扩展：

| Suite | 核心断言 |
| --- | --- |
| `demo_contract_smoke.py` | Pilot 账号、作业、薄弱点、复习和效果证据幂等 |
| `demo_trace_projection_smoke.py` | raw event 正确映射、未知字段忽略、敏感字段不泄露 |
| `demo_trace_authorization_smoke.py` | owner/demo/admin 可读，其他 student/teacher 越权 403 |
| `readiness_smoke.py` | Runtime disabled → not_applicable；默认 status=ok |
| `auth_api_smoke.py` | login 返回 demo_mode，三角色跳转合同数据正确 |
| `autotutor_false_mastery_smoke.py` | 演示路径仍不允许 false mastery |

敏感字段回归至少扫描：

```text
prompt
authorization
api_key
token
password
database_url
traceback
chain_of_thought
```

### 12.2 前端单元测试

至少覆盖：

- `homeForRole(admin) === "/eval"`；
- 历史 localStorage 没有 `demoMode` 时兼容；
- 非 Demo 用户即使手工添加 `?demo=1` 也不显示演示轨迹；
- Demo event 到中文阶段文案映射；
- Runtime disabled 时 Eval 隐藏 rollout 面板；
- 无指标样本时显示“暂无样本”而不是 `0%`；
- Demo trace 获取失败不影响答题。

### 12.3 浏览器 E2E

保留现有 12 条 E2E，并新增主线场景：

```text
一键进入 Pilot 学生
→ 自动到预置 AutoTutor 目标
→ 开始课程
→ 选择固定错误答案
→ 页面出现 judge / reflect / re-plan
→ 完成重教题
→ 完成独立 exit ticket
→ 显示 evidence_written / completed
→ 刷新页面后仍可恢复完成状态
```

另增加最小角色回归：

- admin 登录后访问 `/` 最终进入 `/eval`；
- student 访问 `/eval` 不得看到管理员数据；
- teacher 一键体验仍进入 `/teacher`。

### 12.4 发布前命令

```bash
PYTHONPATH=backend .venv/bin/python scripts/seed_pilot_demo.py
npm run test:unit
npm run test:e2e
PYTHONPATH=backend .venv/bin/python scripts/release_gate.py --fast
```

如本地没有 `.venv`，可使用项目支持的 `PYTHON_BIN` 或 `python3`，但最终 CI 必须在干净环境通过。

### 12.5 线上手工验收

1. `/api/health` HTTP 200；
2. 默认 `/api/ready` 为 `ok`，没有已停用 rollout 的 warning；
3. 首页学生按钮可登录并进入固定 AutoTutor 目标；
4. 故意答错后可看到脱敏 reflect / re-plan；
5. 完成退出票后出现证据摘要；
6. 刷新后会话可恢复；
7. Pilot 教师能看到预置作业与班级证据；
8. 管理员 Eval 默认不展示关闭状态的 rollout blocker；
9. 浏览器网络面板和 UI 中没有 raw prompt、Token 或其他学生轨迹。

---

## 13. 实施里程碑

### Milestone A：Demo 合同统一（0.5–1 天）

- 统一 README、首页、seed 和 E2E 账号；
- 收敛旧 `seed_demo_student.py`；
- 登录响应增加 `demo_mode`；
- 抽取三角色 home route；
- 修复 admin 首页跳转；
- 增加 demo contract/auth 回归。

完成条件：所有入口只描述一套账号和一套主路径。

### Milestone B：安全演示轨迹（1–2 天）

- 建立 deterministic event projector；
- 增加会话级授权 API；
- 新增 `DemoAgentJourney`；
- 首页学生体验深链到固定目标；
- 完成敏感信息负向测试。

完成条件：线上 Demo 能显示 reflect / re-plan，且无法跨会话读取轨迹。

### Milestone C：完整主线验收（1 天）

- 增加答错到 exit ticket 的浏览器 E2E；
- 验证学习证据写入和会话恢复；
- 保持 v1.35 false mastery 门禁；
- 将新增 suite 纳入 fast release gate。

完成条件：默认 CI 无外部 LLM 时稳定证明完整主线。

### Milestone D：健康与 Eval 降噪（0.5–1 天）

- readiness 增加 not_applicable 语义；
- Runtime disabled 时不再 degraded；
- Eval 默认收敛作品集指标；
- Runtime rollout 移入高级诊断；
- agent-evidence 改为 manual-only。

完成条件：健康页和 Eval 不再要求已明确停用的生产能力。

### Milestone E：文档与线上验收（0.5 天）

- README 更新为唯一 5 分钟脚本；
- 执行 lint、unit、E2E、fast release gate；
- 部署后执行线上验收；
- 生成实施报告，记录实测 commit 与限制。

完成条件：首次接触项目的人可以只按 README 完成演示。

---

## 14. 文件影响面

预计修改：

```text
README.md
frontend/app/page.tsx
frontend/components/AuthGuard.tsx
frontend/contexts/AuthContext.tsx
frontend/lib/auth.ts
frontend/app/(student)/student/auto-tutor/page.tsx
frontend/app/eval/page.tsx
frontend/e2e/core-flows.spec.ts
frontend/e2e/autotutor-student-ui.spec.ts
backend/api/routers/auth.py
backend/api/routers/learning.py
backend/api/routers/debug.py
scripts/seed_pilot_demo.py
scripts/release_gate.py
.github/workflows/agent-evidence.yml
```

预计新增：

```text
backend/agents/autotutor_demo_trace.py
frontend/components/DemoAgentJourney.tsx
frontend/components/DemoAgentJourney.test.tsx
eval/demo_contract_smoke.py
eval/demo_trace_projection_smoke.py
eval/demo_trace_authorization_smoke.py
docs/20260831-agent-demo-showcase-v146-implementation-report.md
```

预计删除或兼容降级：

```text
scripts/seed_demo_student.py
```

实际实施可根据现有模块边界调整文件名，但不得改变本 Spec 的授权、脱敏、readiness 和验收要求。

---

## 15. 数据库与迁移

本轮原则上不新增数据库表或 Alembic migration。

原因：

- Demo trace 可从现有 AutoTutor session、runtime events 和 learning events 投影；
- `traffic_cohort` 已存在；
- Pilot seed 已有数据模型；
- 本轮重点是展示和语义收敛，不是持久化架构升级。

如果实现过程中发现现有 session state 无法确定性证明 reflect / re-plan，可在已有 session JSON/metadata 中增加向后兼容字段，但必须先证明无法从现有事件获得，且不得为 Demo 单独复制一套状态表。

---

## 16. 可观测性

新增最小审计事件：

```text
demo.entry
demo.trace_viewed
demo.flow_completed
demo.flow_blocked
```

字段：

```json
{
  "actor_id": "pilot-student",
  "session_id": "...",
  "trace_id": "...",
  "demo_phase": "re_plan",
  "status": "success",
  "duration_ms": 1234
}
```

要求：

- 这些事件属于 runtime/demo 口径，不进入真实学习增益统计；
- `demo.trace_viewed` 不记录完整事件内容；
- Demo 账号继续从 verified rollout 样本中排除；
- 不增加真实 LLM 调用；
- 日志不打印账号密码。

---

## 17. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 直接暴露 raw trace | Prompt/隐私/内部实现泄露 | 会话级授权 + 确定性脱敏投影 |
| Demo query 被普通用户伪造 | 非 Demo 用户看到内部信息 | 后端 traffic cohort 权威判断 |
| 固定演示数据被前次操作污染 | 现场路径不稳定 | 演示前幂等 seed；E2E 使用独立 SQLite |
| 完整 E2E 依赖真实 LLM | CI 抖动、超时、成本 | 审定内容包和确定性 fixture |
| readiness 放宽掩盖真实故障 | 假健康 | 只把关闭能力标记 N/A；required 仍 fail-closed |
| Eval 过度简化丢失工程证据 | 无法深入讲解 | 高级诊断保留，不删除底层指标 |
| shared Pilot 账号并发修改状态 | 多人演示互相影响 | 当前仅作者使用；多人隔离列为未来版本 |
| seed 误改真实数据 | 数据损坏 | 仅操作 `traffic_cohort=demo` 和固定 Pilot ID |
| 新 Demo 事件污染学习指标 | 效果统计失真 | demo/runtime 分域，明确排除 |

---

## 18. 回滚策略

### 18.1 前端回滚

- 演示轨迹组件失败时隐藏该组件，不阻断 AutoTutor；
- 首页深链可回退到 `/student`；
- Eval 新默认视图可回退为现有面板，但不得恢复错误权限。

### 18.2 后端回滚

- Demo trace API 是新增只读接口，可独立禁用；
- readiness 保留现有 `checks` 字段，回滚不影响 Render `/api/health`；
- login 新字段为向后兼容扩展，旧前端可忽略；
- 不涉及数据库 migration，因此代码回滚无需 schema downgrade。

### 18.3 工作流回滚

`agent-evidence.yml` 改为 manual-only 后，如确有需要可恢复 schedule；恢复必须由作者明确决定，不作为 Demo 发布门禁。

---

## 19. 完成定义

只有同时满足以下条件，v1.46 才能标记 Development Complete：

- [ ] 首页、README、脚本和 E2E 只使用一套 Pilot Demo 合同；
- [ ] `seed_pilot_demo.py` 幂等，且不修改非 Demo 数据；
- [ ] admin/student/teacher 跳转正确；
- [ ] `/eval` 保持 admin-only；
- [ ] Demo trace API 按 AutoTutor 会话所有权授权；
- [ ] Demo trace 不包含敏感字段、raw prompt 或其他用户数据；
- [ ] 线上生产构建可展示脱敏 plan / judge / reflect / re-plan / exit ticket；
- [ ] 完整答错到 evidence 的浏览器 E2E 通过；
- [ ] false mastery 与 content blocked 回归通过；
- [ ] Runtime disabled 时默认 `/api/ready` 不因 rollout/evidence degraded；
- [ ] Eval 默认隐藏不适用的 Runtime Rollout；
- [ ] agent-evidence 不再每日自动运行；
- [ ] frontend lint、unit、E2E、fast release gate 全部通过；
- [ ] README 5 分钟脚本在本地从零执行成功。

只有额外满足以下条件，才能标记 Demo Deployment Verified：

- [ ] 目标 commit 已部署；
- [ ] `/api/health` HTTP 200；
- [ ] 默认 `/api/ready` 为 `ok`；
- [ ] 线上一键学生体验成功；
- [ ] 线上完整 reflect / re-plan / exit ticket 手工演示成功；
- [ ] 线上教师补充路径成功；
- [ ] 线上管理员 Eval 默认视图正确；
- [ ] 浏览器检查未发现敏感数据泄露。

本地测试通过不等于线上部署已验证；线上部署未执行时，状态必须保持 `Development Complete · Deployment NOT_RUN`。

---

## 20. 后续版本边界

v1.46 完成后，再根据真实演示反馈决定下一步：

### 候选 v1.47-A：页面与导航减法

仅当演示中仍明显迷路时：

- 合并重复入口；
- 将历史游戏、地图、辩论移入“更多能力”；
- 删除确认无引用的旧 route alias；
- 将 52 个页面收敛为作品集主路径和能力附录。

### 候选 v1.47-B：公开多人 Demo 隔离

仅当需要把链接公开给多人使用时：

- 每个访客独立 demo workspace；
- TTL 自动清理；
- 限流和成本预算；
- 不共享 Pilot 学习状态。

### 候选 v1.47-C：真实 LLM 演示证据包

仅当面试或作品集明确需要 Provider 实证时：

- 手动 live probe；
- 一组真实业务样本；
- 脱敏报告；
- 不恢复 staging、immutable image 或自动灰度链路。

LangSmith、企业级 rollout、多租户和新 Agent 仍不因 v1.46 完成而自动进入优先队列。
