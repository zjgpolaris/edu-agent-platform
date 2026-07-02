# 未复核盲区接入教师通知徽标开发文档

**创建时间：** 2026-07-02
**迭代目标：** 让"未复核的质检盲区"主动出现在教师侧边栏徽标，无需进详情页即可被提醒去复核
**类型：** 后端聚合 + 前端徽标 + 测试

---

## 一、背景

上一轮做了质检盲区教师复核（`question_review_flags` + review-flag 端点 + 详情页按钮）。但盲区与复核入口都藏在**作业详情页**里——教师不主动点进去就看不到，复核能力形同虚设。

本轮把「未复核盲区数」接入已有的教师通知徽标（60s 轮询），在侧边栏「布置作业」入口直接提示。

## 二、实现

### 后端（`assignment_service.py`）
- `list_teacher_assignments` 每份作业加 `open_blind_spot_count`：在既有连接内查 `question_review_flags`，`quality_blind_spots` 中 `question_index` 未被复核的计数。
- `get_teacher_badges` 加 `blind_spots_to_review` = 各作业 `open_blind_spot_count` 之和。

### 前端（`AppSidebar.tsx`）
- `NavItem` / `MobileNavItem` 加 `badgeKeys?: string[]`；`navBadgeCount` / `badgeOf` 支持多键求和（单键 `badgeKey` 保留兼容）。
- 教师「布置作业」入口（桌面 + 移动）改用 `badgeKeys: ["pending_review", "blind_spots_to_review"]`，徽标显示两者之和＝作业相关待办总数。

### 测试（`eval/notification_badges_smoke.py`）
- 更新两处精确 dict 断言含新 key。
- 新增 `teacher_badge_counts_open_blind_spots_then_review_clears`：独立教师，quality=ok 客观题 + 3 人多数答错 → `blind_spots_to_review==1`；复核后 → `0`。
- 6 → 7 例。

## 三、验证

1. `python3 eval/notification_badges_smoke.py` → 7/7
2. `python3 eval/assignment_smoke.py` → 16/16（get_teacher_badges 变更回归）
3. `npm run build --prefix frontend` → 53/53
4. `python3 -c "import ast; ast.parse(open('backend/services/assignment_service.py').read())"`

## 四、后续

至此质量反馈链完整：AI 质检 → 持久化 → 盲区检出 → 徽标提醒 → 教师复核。剩余延伸：`bad_question` 样本作为 `check_question_semantic` few-shot 反例（自改进闭环）。
