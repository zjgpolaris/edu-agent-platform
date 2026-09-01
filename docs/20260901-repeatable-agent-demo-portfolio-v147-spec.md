# EduAgent 可重复 Agent Demo 与作品集导航收敛 v1.47 Spec

**状态：** Development Complete（本地验证完成，待部署验证）  
**日期：** 2026-09-01  
**优先级：** P0 可重复演示、会话级证据闭环；P1 作品集叙事与导航减法  
**前置版本：** v1.46 Agent Demo 主线收敛与可观测演示

---

## 0. 决策摘要

v1.46 已把 AutoTutor 的 `plan → judge → reflect → re-plan → exit ticket → evidence` 收敛为一条可运行主线，但当前合同更接近“第一次演示成功”，还不是“可反复、可讲解、可跨角色验证的作品集 Demo”。

v1.47 不增加新 Agent、不扩大生产基础设施，也不建设公开多人沙箱。本迭代只解决四个问题：

1. 首页进入应明确开始一次全新 Demo，刷新应恢复同一次 Demo；
2. 已完成课程不应被下一次首页进入误恢复；
3. 学生完成后的证据应能被有班级权限的教师按会话直接查看；
4. Demo 账号的首页和导航应突出 Agent 主线，其他能力降级到“更多能力”。

版本主题：**从“单次可演示”升级为“可重复、可切换视角、叙事聚焦的 Agent 作品集”。**

---

## 1. 当前基线与问题

### 1.1 已具备能力

- 首页 Pilot 学生、教师一键登录；
- AutoTutor 确定性教学主线与内容门禁；
- 答错后的 reflect / re-plan / reteach；
- 独立退出票和 verified mastery；
- 会话级脱敏 Demo Journey；
- 学习事件、复习、错题和教师辅导效果聚合；
- admin-only Eval / AgentOps；
- 13 条核心浏览器流程。

### 1.2 Demo 重复运行语义不清

当前 `demo=1` 会查询 `include_completed=true` 的最近会话。结果是：

- 演示者完成一次课程后再次从首页进入，会看到已完成小结；
- “开始新的演示”和“刷新恢复”使用同一套最近会话逻辑；
- 只有完成页底部的“再上一节”能隐式创建新会话；
- URL 没有绑定当前 `session_id`，刷新依赖“最近会话”猜测。

### 1.3 证据已产生，但跨角色路径不直达

AutoTutor 已写入退出票和验证掌握事件，教师班级学情页也有聚合统计，但：

- 学生完成页只显示“教师端可见”；
- 没有会话级教师证据详情；
- 教师无法从一个明确的 `session_id` 验证本次 reflect / re-plan / exit ticket；
- 演示者需要自行在多个页面中寻找相关聚合指标。

### 1.4 作品集叙事仍然过宽

当前线上首页仍以“多 Agent、史料、作文、辩论、学习平台”为主叙事。代码中共有 52 个页面；学生桌面导航约 16 个目的地，移动端另有独立导航配置。

对个人 Agent Demo 而言，这会稀释 AutoTutor 的决策闭环证据。

### 1.5 旧路由与标准路由并存

项目同时存在：

- `/learning-assistant` 与 `/student/assistant`；
- `/history-character` 与 `/student/history/chat`；
- `/student-home`、`/teacher/dashboard` 等 redirect alias；
- 部分内部链接仍指向旧路径。

本迭代只做标准路径收敛和引用修正，不进行大规模功能删除。

---

## 2. 用户与核心场景

### 2.1 主要用户

- 项目作者：在面试、作品集讲解或录屏中反复演示；
- 观看者：希望快速理解 Agent 的决策、纠错和证据闭环；
- Pilot 教师：验证学生本次辅导结果，而不是只看班级平均值。

### 2.2 标准演示场景

1. 首页点击 Pilot 学生 Agent Demo；
2. 系统开始一次全新课程；
3. 演示者故意答错，观察 reflect / re-plan；
4. 完成调整后练习和退出票；
5. 查看本次会话证据；
6. 切换 Pilot 教师账号；
7. 教师按同一 session 查看证据；
8. 返回首页再次点击，可开始另一轮全新演示。

---

## 3. 目标与非目标

### 3.1 P0 目标

- 首页一键 Demo 总是开始新的演示尝试；
- 页面刷新恢复 URL 指定的同一会话；
- 默认 AutoTutor 入口只恢复未完成会话；
- 完成页明确提供“重新演示”和“切换教师视角查看证据”；
- 提供安全、会话级、只读的 AutoTutor evidence API；
- 教师只有在现有班级/作业关系授权后才能查看学生证据；
- 完整浏览器 E2E 覆盖新建、刷新、完成、重演、教师证据。

### 3.2 P1 目标

- 首页 Hero 聚焦 AutoTutor Agent 决策闭环；
- Demo 学生和教师导航首屏主要目的地不超过 5 个；
- 其他能力保留在“更多能力”；
- 桌面/移动 Demo 导航由同一份 manifest 派生；
- 内部入口优先使用标准 `/student/*`、`/teacher/*` 路径；
- README 与实际 Next.js / React 版本一致。

### 3.3 非目标

- 不建设公开多人独立 workspace；
- 不提供全局 Demo 数据删除/reset HTTP API；
- 不引入 LangSmith；
- 不全面迁移 LangGraph；
- 不增加新的教学 Agent；
- 不恢复 staging、immutable image 或自动灰度部署；
- 不删除历史游戏、地图、辩论、作文等能力；
- 不要求真实 LLM 作为默认 CI 前置条件。

---

## 4. Demo 会话 URL 合同

### 4.1 首页新演示入口

Pilot 学生按钮跳转：

```text
/student/auto-tutor?focus=洋务运动目的&demo=1&fresh=1
```

`fresh=1` 只表达“本次入口要求创建新会话”，不触发历史数据删除。

### 4.2 新会话创建后

创建成功后，前端必须使用 `router.replace` 将 URL 改为：

```text
/student/auto-tutor?focus=洋务运动目的&demo=1&session_id=at_xxx
```

同时移除 `fresh=1`，防止刷新时重复创建。

### 4.3 刷新恢复

当 URL 包含 `session_id`：

- 优先调用 `GET /api/autotutor/session/{session_id}`；
- 后端继续执行会话所有权授权；
- 成功时恢复该会话，包括 completed 状态；
- 404 时清除失效 `session_id` 并回退到未完成会话查询；
- 403 时显示无权访问，不得回退查询其他会话。

### 4.4 默认入口恢复

不含 `fresh=1` 和 `session_id` 时：

- 只查询 `include_completed=false`；
- 恢复最近未完成会话；
- 没有未完成会话时显示启动页，或在有 focus 时自动新建；
- 不自动恢复已完成会话。

### 4.5 重新演示

完成页“重新演示”调用现有 start API 创建新会话，并把 URL 替换为新 `session_id`。

不得：

- 删除旧会话；
- 清除学习事件；
- 修改其他 Pilot 学生数据；
- 暴露服务端全局 reset 能力。

---

## 5. 会话级证据 API

### 5.1 路由

```http
GET /api/autotutor/session/{session_id}/evidence
Authorization: Bearer <token>
```

### 5.2 授权

- 学生：只能查看自己的会话；
- 教师：必须通过 `assert_teacher_student_access` 的现有班级/作业关系；
- 管理员：允许查看；
- anonymous、其他学生、无班级关系教师：403；
- 会话不存在：404。

不得复用当前宽松的 `assert_student_access` 作为教师证据授权终点。

### 5.3 响应 allowlist

```json
{
  "session_id": "at_xxx",
  "student_id": "pilot-student",
  "status": "completed",
  "knowledge_points": ["洋务运动目的"],
  "replans": 1,
  "reflection_count": 1,
  "exit_ticket": {
    "recorded": true,
    "knowledge_point": "洋务运动目的",
    "passed": true
  },
  "mastery": {
    "status": "verified"
  },
  "evidence": {
    "learning_event_recorded": true,
    "weakpoint_action": "verified_correct_evidence_recorded",
    "tutor_effectiveness_ready": true
  }
}
```

响应不得包含：

- 正确答案；
- 学生具体选项；
- prompt、模型原文、工具原始输入；
- raw runtime metadata；
- trace_id、run_id；
- 其他学生信息。

### 5.4 审计

成功读取记录：

```text
action = autotutor.evidence_viewed
resource_type = autotutor_session
resource_id = session_id
metadata = { viewer_role, session_status }
```

---

## 6. 教师证据页面

### 6.1 路由

```text
/teacher/evidence?session_id=at_xxx
```

### 6.2 页面状态

- 无 session_id：展示从学生完成页进入的说明；
- loading：骨架或明确加载状态；
- 404：证据不存在；
- 403：无权查看该学生证据；
- completed：显示会话证据卡；
- 非 completed：标记课程尚未完成，不伪造结果。

### 6.3 显示内容

- 学生 ID；
- 知识点；
- reflect / re-plan 次数；
- 退出票是否通过；
- verified mastery；
- 学习事件和教师效果聚合是否就绪；
- 返回班级学情链接。

---

## 7. 角色切换合同

学生完成页链接：

```text
/?role=teacher&next=/teacher/evidence?session_id=at_xxx
```

实际 URL 必须正确编码 `next`。

首页：

- `role=teacher` 时默认选中教师 tab；
- Pilot 教师一键登录后跳转安全的 `next`；
- 普通登录同样支持安全 `next`；
- `next` 只允许站内绝对路径；
- 教师只允许 `/teacher` 路径，学生只允许 `/student` 路径，管理员只允许 `/eval`；
- `//host`、协议 URL、角色不匹配路径一律忽略。

---

## 8. 首页作品集叙事

首页 Hero 改为：

- 核心标题：看得见决策的 AutoTutor Agent；
- 流程：Plan → Judge → Reflect → Re-plan → Exit Ticket → Evidence；
- 三项证据：自主规划、答错后调整、独立验证与教师回流；
- 保留普通账号登录和教师入口；
- 不在首屏强调与主线无关的功能数量。

---

## 9. Demo 导航

### 9.1 学生 Demo 主导航

- 今日主线 `/student`；
- Agent 辅导 `/student/auto-tutor`；
- 学习证据 `/student/review`；
- 更多能力：随问、作业、资料、能力展厅。

### 9.2 教师 Demo 主导航

- 教师总览 `/teacher`；
- 班级证据 `/teacher/class-analytics`；
- Pilot 作业 `/teacher/assignments`；
- 更多能力：批改、命题质量、资料与资源。

### 9.3 普通账号

普通账号继续使用现有完整导航，本迭代不改变通用产品信息架构。

### 9.4 实现约束

- Demo 桌面和移动导航从同一 manifest 派生；
- 不在两个数组中重复手写同一目的地；
- badge 合计逻辑保持；
- active route 判定保持 query-aware；
- 直接访问被折叠能力仍然可用。

---

## 10. 标准路由收敛

本迭代修正已确认的内部链接：

- `/learning-assistant` → `/student/assistant`；
- `/history-character` → `/student/history/chat`；
- 其他已存在标准 `/student/*` 或 `/teacher/*` 的链接优先改为标准路径。

旧外部 URL 继续由 `next.config.js` redirect 兼容。本迭代不删除大型页面源文件。

---

## 11. README 与工程配置

- README 主线加入“重新演示”和“教师证据”步骤；
- 技术栈更新为 Next.js 16、React 19；
- 默认仍为 Git push 触发 Vercel / Render 部署；
- CI Node 版本与根 `package.json` 的 Node 24 合同对齐；
- 本地 release gate 优先使用项目 `.venv`，CI 无 `.venv` 时继续使用 Actions 已安装依赖的 Python；
- 不在本迭代删除 PostgreSQL、Docker 或 production readiness job。

---

## 12. 测试与验收

### 12.1 后端

- evidence 投影 allowlist 测试；
- owner student 成功；
- authorized teacher 成功；
- unrelated teacher 403；
- other student 403；
- admin 成功；
- 404；
- 响应不含敏感字段。

### 12.2 前端单元测试

- `safeNextForRole` 拒绝外部和角色不匹配路径；
- Demo 导航 manifest 首屏目的地不超过 5；
- 教师证据页面成功与错误状态；
- Demo Journey 既有测试保持。

### 12.3 E2E

必须覆盖：

1. 首页学生按钮包含 `fresh=1`；
2. start 后 URL 包含 `session_id` 且移除 `fresh`；
3. 答错出现 reflect / re-plan；
4. 完成退出票并写入 evidence；
5. 刷新恢复相同 completed session；
6. “重新演示”创建不同 session；
7. 学生完成页切换教师账号；
8. 教师看到相同 session 的证据；
9. 默认非 Demo 页面不显示 Demo Journey；
10. content blocked 保持安全阻断。

### 12.4 发布前命令

```bash
PYTHONPATH=backend .venv/bin/python eval/run_core_evals.py \
  --suite demo_contract_smoke \
  --suite demo_trace_projection_smoke \
  --suite demo_trace_authorization_smoke \
  --suite demo_evidence_authorization_smoke \
  --suite auto_tutor_trajectory_eval \
  --suite autotutor_false_mastery_smoke \
  --suite autotutor_content_blocked_api_smoke

npm run test:unit --prefix frontend
npm run lint --prefix frontend
npm run build --prefix frontend
npm run test:e2e --prefix frontend
```

---

## 13. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| fresh 刷新重复创建 | 产生多余会话 | start 成功立即 replace 为 session_id |
| URL session_id 越权 | 读取他人状态 | 后端所有权/班级关系授权，不信任前端 |
| 教师看到答案 | 形成敏感泄露 | evidence 独立 allowlist projector |
| 角色切换 open redirect | 跳转外站 | safeNextForRole 严格路径白名单 |
| Demo 导航隐藏功能 | 被误解为删除 | 只对 demoMode 生效，更多能力仍可达 |
| 重演累积聚合数据 | 班级比例变化 | 会话详情以 session_id 为准，聚合仅作补充 |
| 旧链接失效 | 收藏地址不可用 | 保留 redirect，只改内部链接 |

---

## 14. 回滚策略

- 移除首页 `fresh=1` 即回到最近会话恢复模式；
- 移除 `session_id` replace 不影响后端会话数据；
- evidence API 和页面均为新增只读能力，可独立回滚；
- Demo 导航按 `demoMode` 条件启用，可切回完整 manifest；
- 不涉及数据库 schema migration。

---

## 15. 完成定义

Development Complete 必须全部满足：

- [x] 首页新 Demo 使用 `fresh=1`；
- [x] start 后 URL 绑定 `session_id`；
- [x] 刷新恢复同一会话；
- [x] 新一轮 Demo 不恢复旧 completed session；
- [x] 完成页可明确重新演示；
- [x] evidence API 使用独立 allowlist；
- [x] 学生、教师、管理员授权测试通过；
- [x] 无关教师和其他学生 403；
- [x] 教师页面可查看同一 session 的证据；
- [x] 首页主叙事聚焦 AutoTutor；
- [x] Demo 导航主要入口不超过 5 个；
- [x] 普通账号完整导航不变；
- [x] 内部核心链接使用标准路径；
- [x] README 与实际技术栈一致；
- [x] 后端相关 eval 全部通过；
- [x] frontend unit、lint、build 全部通过；
- [x] 完整 E2E 通过。

Deployment Verified 仍需额外手工确认：

- [ ] 目标 commit 已由 Vercel / Render 部署；
- [ ] `/api/health` 返回 200；
- [ ] 线上首页新 Demo 不恢复旧 completed session；
- [ ] 线上刷新恢复同一 session；
- [ ] 线上教师证据页授权正确；
- [ ] 未发现 prompt、答案或其他学生信息泄露。

本地开发完成不等于线上部署验证完成。

---

## 16. 后续版本边界

完成 v1.47 后再根据真实使用决定：

- 若要公开分享：进入多人 Demo workspace + TTL 隔离；
- 若面试要求 Provider 实证：进入手动真实 LLM 证据包；
- 若页面仍显复杂：再删除确认无引用的旧 route 实现；
- 若 CI 成本成为问题：单独做默认/手动工作流分层。

LangSmith、全面 LangGraph、多租户和新 Agent 继续不自动进入优先队列。
