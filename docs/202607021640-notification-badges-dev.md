# 轻量通知系统（角色徽标）开发文档

**创建日期：** 2026-07-02 16:40
**目标：** 在共享侧边栏为学生/教师显示未处理事项红点，把"要用户主动进页面才发现"变成"系统主动提示"。无 WebSocket、纯轮询、复用已有数据、不建新表。

---

## 一、背景

平台待办此前全靠用户主动刷新页面：教师不知道多少主观题待评阅，学生不知道作业到期或有未完成复习。本轮加轻量徽标。

---

## 二、后端

### `services/assignment_service.py`（复用现有 list 函数，确定性）

- `get_teacher_badges(teacher_id) -> {pending_review, below_threshold}`：聚合 `list_teacher_assignments` 每份的 `pending_review_count` / `below_threshold_count`。
- `get_student_badges(student_id, today) -> {pending_assignments, due_soon}`：遍历 `list_student_assignments`，未提交计入 pending；`due_date<=today` 计入 due_soon。

### `api/main.py`

- `GET /api/teacher/badges` → `get_teacher_badges`。
- `GET /api/student/{student_id}/badges` → `_student_badges_sync`：在 `get_student_badges` 基础上合入今日复习待完成数（`review_service.get_today_session`，无 session 记 0，不误创建）。返回 `{pending_assignments, due_soon, pending_review}`。

---

## 三、前端 `components/AppSidebar.tsx`

- `NavItem` 加 `badgeKey?`；教师「布置作业」→`pending_review`，学生「我的作业」→`pending_assignments`、「今日复习」→`pending_review`。
- `AppSidebar` 新增 badges state + `useEffect`：按 role 拉 `/api/teacher/badges` 或 `/api/student/{id}/badges`，60s `setInterval` 轮询，卸载清理。
- `navBadgeCount()` 递归求和（父组显示子项徽标之和）。`<Badge>`：展开态红底数字，折叠态 icon 右上角小红点（`.sidebar-badge` / `.sidebar-badge-dot`）。父组折叠时也显示合计红点。
- `MobileBottomNav` 独立拉同源徽标，学生「复习」、教师「更多」（聚合 more 项）显示小红点。
- CSS 加在 `globals.css`：`.sidebar-badge`、`.sidebar-badge-dot`，并给 `.sidebar-icon` / `.mbn-icon` 加 `position:relative` 供圆点定位。

---

## 四、测试

`eval/notification_badges_smoke.py`（新建 6 例，离线）：教师初始 0、三份 partial 提交 pending_review=3、评阅低分后 pending-1 且 below_threshold+1、教师隔离、学生 pending/due_soon（逾期计入）、提交后归零。已注册 `run_core_evals.py`（p1/teacher）。

回归：`assignment_smoke` 12/12、前端 build 52/52。

---

## 五、后续

1. 徽标可下钻为"通知中心"列表（点开看具体哪份作业/哪个学生）。
2. 学生作业到期用更细粒度（今日/3 天内不同颜色）。
3. 教师端"新提交待批改"与"低分需关注"分色区分。
4. 轮询可升级为 SSE/visibility 感知（页面隐藏时暂停）。
