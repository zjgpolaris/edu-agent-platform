# 学习路径页补齐开发文档

**创建时间：** 2026-07-02
**迭代目标：** 补齐学生「学习路径」前端页，修复移动端死链，把已有后端能力接入 UI，形成个性化学习闭环的聚合视图
**类型：** 纯前端补齐（后端零改动）

---

## 一、背景

排查移动端导航时发现：`AppSidebar.tsx` 的移动端「更多」抽屉（`STUDENT_MORE_NAV`）挂着 `/student/learning-path` 入口，但对应页面目录 `frontend/app/(student)/student/learning-path/` **从未创建** —— 学生点进去直接 404。

进一步排查发现后端 **`GET /api/students/{student_id}/learning-path` 端点早已实现**（`backend/api/main.py:895-938`），返回完整的学习路径数据，只是前端页面一直缺席。因此本轮是一次高 ROI 的纯前端补齐：把已有 API 渲染成页，顺带修死链。

## 二、后端返回（已存在，未改动）

`student_learning_path` 返回字段：

| 字段 | 说明 |
| --- | --- |
| `weak_topics` / `strong_topics` | 画像中的薄弱 / 优势主题 |
| `weakpoints` | 错题本条目（含 `knowledge_tag` / `wrong_count` / `correct_streak` 掌握度） |
| `priority_topics` | 按错题本掌握度排序的优先知识点 |
| `recommended_actions` | 复习计划建议行动 |
| `progress` | `{tag: 0~1}` 进度（错得多 → 进度低；优势点 0.8） |
| `milestones` | `[{title, completed}]` 里程碑（由 recommended_actions 生成） |
| `updated_at` | 画像更新时间 |

## 三、实现

### 新增 `frontend/app/(student)/student/learning-path/page.tsx`

`"use client"` 页，风格对齐 `review/page.tsx`（内联 CSS 常量 + `InjectStyles()` 注入 + `Noto Serif SC` / `Ma Shan Zheng` + cinnabar/gold/paper 全局变量），前缀 `.lp-*`。

- **数据获取**：`useAuth()` 取 `studentId`/`token`，`fetch(${API}/api/students/${studentId}/learning-path, {headers: authHeaders(token)})`；`user?.actorId` 未就绪不请求；加载态脉冲字「径」。
- **掌握度概览**：优势 / 薄弱 / 待攻克三个计数卡。
- **优先攻克（竖向时间线，页面主体）**：按 `priority_topics` 顺序（回落 `weakpoints`）逐条渲染 —— 知识点 + `progress[tag]` 进度条 + `correct_streak` 连对进度（`连对 N/2`，达阈标「已掌握」并切金色节点）。掌握阈值 `MASTERY_THRESHOLD=2`，与后端 `record_correct_evidence` 一致。
- **推荐行动**：优先用 `milestones`，回落 `recommended_actions`，未完成圆点列表。
- **联动 CTA**：「去今日复习」→ `/student/review`；「针对性辅导」→ `/student/auto-tutor?focus=` + `priority_topics[0]`（单个最高优先知识点，与 assignments 页 CTA 一致；AutoTutor 页 `?focus=` 按单 tag 解析）。
- **空态**：`weakpoints` 与 `weak_topics` 均空 → 引导去 `/student/assignments`。

### 改 `frontend/app/components/AppSidebar.tsx`

桌面 `studentNav`「我的学情」分组新增 `{ label: "学习路径", href: "/student/learning-path", icon: "路" }`（置于「学情分析」后）。移动端入口本就存在，页面补齐后即生效。

## 四、验证

1. `npm run build --prefix frontend` → 页数 52 → 53，无类型错误
2. 手动：学生登录 → 桌面「我的学情」/ 移动端「更多」→ 学习路径，正常渲染（不再 404）；有错题时时间线 / 进度条 / 连对进度 / CTA 正常；空态正常
3. `python3 eval/run_core_evals.py` 回归全绿（后端未改，预期不受影响）

## 五、关联

- 掌握度模型 `correct_streak`：见 `weakpoint_service.record_correct_evidence`
- AutoTutor `?focus=` 透传：见 `auto-tutor/page.tsx`
- 复习闭环：`/student/review`
