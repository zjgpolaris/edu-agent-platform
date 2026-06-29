# 自适应智能复习系统 开发文档

**创建时间**：2026-06-24  
**状态**：规划中  
**优先级**：P0  
**预估工期**：3–4 天

---

## 一、背景与目标

### 现状

平台已积累了完整的学习数据基础：

| 数据 | 表/模块 | 现状 |
|------|---------|------|
| 错题标签 | `weakpoints` | ✅ 已有，带 tag/count |
| 记忆强度 | `memory_entries` | ✅ 已有，带 strength/last_reviewed |
| 学习事件 | `learning_events` | ✅ 已有，带 event_type/payload |
| 题目生成 | `quiz / timeline_question_generator` | ✅ 已有 |

### 问题

当前学习闭环是**被动**的：学生完成作业 → 老师批改 → 学生查看结果。  
没有机制**主动推动**学生在遗忘前复习薄弱知识点。

### 目标

构建基于艾宾浩斯遗忘曲线的**自适应复习调度引擎**，每天为学生生成个性化的「今日复习」任务，将已有数据转化为持续学习动力。

---

## 二、核心功能模块

```
┌──────────────────────────────────────────────────────┐
│                自适应复习系统                          │
│                                                      │
│  ① 复习调度引擎      计算每个知识点的复习优先级          │
│  ② 个性化练习生成    按优先级生成多种形式的练习题        │
│  ③ 今日复习页面      学生端入口，展示待复习任务          │
│  ④ 掌握度可视化      知识点热力图 + 学习趋势图           │
└──────────────────────────────────────────────────────┘
```

---

## 三、技术设计

### 3.1 复习调度算法

基于 SM-2 简化版，结合现有 `memory_entries.strength` 字段：

```
复习优先级得分 = (1 - strength) × 遗忘衰减系数

遗忘衰减系数：
  - 距上次复习 < 1天:  0.1
  - 1–3 天:            0.4
  - 3–7 天:            0.7
  - > 7 天:            1.0

每日推送：优先级得分 TOP 8 条，按学科均衡分配
```

### 3.2 数据流

```
memory_entries + weakpoints
        │
        ▼
  调度引擎 (schedule_review)
        │
        ▼
  生成任务列表 (review_tasks)
        │
        ├── 选择题   → quiz API
        ├── 时间线题 → timeline_question_generator
        └── 卡片配对 → card_game API
        │
        ▼
  学生完成 → 更新 memory_entries.strength
```

### 3.3 Strength 更新规则

| 答题结果 | strength 变化 |
|----------|---------------|
| 答对      | `min(strength + 0.15, 1.0)` |
| 答错      | `max(strength - 0.2, 0.1)` |
| 跳过      | `max(strength - 0.05, 0.1)` |

---

## 四、数据模型

### 新增表：`review_sessions`

```sql
CREATE TABLE review_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id  TEXT NOT NULL,
    date        DATE NOT NULL,
    tasks       JSONB NOT NULL,   -- [{tag, type, question, answer}]
    completed   INTEGER DEFAULT 0,
    total       INTEGER NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(student_id, date)
);
```

`tasks` 字段结构：
```json
[
  {
    "tag": "秦朝统一",
    "source": "weakpoint",        
    "type": "quiz | timeline | card",
    "question": "...",
    "options": ["A", "B", "C", "D"],
    "answer": "A",
    "memory_entry_id": "uuid"
  }
]
```

---

## 五、API 设计

### 5.1 获取今日复习任务

```
GET /api/students/{student_id}/review/today
```

**逻辑：**
1. 查询当天是否已有 `review_sessions` 记录，有则直接返回
2. 无则调度引擎生成，写入 `review_sessions`，返回

**Response：**
```json
{
  "date": "2026-06-24",
  "completed": 2,
  "total": 8,
  "tasks": [...]
}
```

### 5.2 提交复习结果

```
POST /api/students/{student_id}/review/submit
```

**Body：**
```json
{
  "task_index": 0,
  "is_correct": true
}
```

**逻辑：**
1. 更新 `review_sessions.tasks[task_index]` 的完成状态
2. 更新对应 `memory_entries.strength`
3. 记录 `learning_events`（type: `review_complete`）

### 5.3 掌握度概览

```
GET /api/students/{student_id}/mastery-overview
```

**Response：**
```json
{
  "total_tags": 32,
  "mastered": 12,       
  "learning": 14,       
  "weak": 6,            
  "heatmap": [
    { "tag": "秦朝统一", "strength": 0.85, "last_reviewed": "2026-06-22" }
  ],
  "streak_days": 5
}
```

---

## 六、前端设计

### 6.1 今日复习页（`/student/review`）

```
┌─────────────────────────────────────┐
│  📚 今日复习                          │
│  2026年6月24日  已完成 2/8            │
│  连续打卡 5 天 🔥                    │
├─────────────────────────────────────┤
│  知识点：秦朝统一                     │
│                                     │
│  秦朝统一六国的时间是？               │
│  ○ A. 公元前230年                    │
│  ● B. 公元前221年  ← 选中            │
│  ○ C. 公元前206年                    │
│  ○ D. 公元前256年                    │
│                                     │
│         [提交答案]                   │
├─────────────────────────────────────┤
│  进度：■■■□□□□□  2/8                 │
└─────────────────────────────────────┘
```

**交互：**
- 逐题展示，答完立即显示对错 + 简短解析
- 全部完成后显示本次复习总结（正确率、strength 变化）
- 支持「明天再看」跳过当前题

### 6.2 掌握度热力图（嵌入 `/student/dashboard`）

```
知识点掌握度
─────────────────────────────────
秦朝  ████████░░  85%  ↑
汉朝  ██████░░░░  62%  →
唐朝  ████░░░░░░  41%  ↓ 需复习
宋朝  ██░░░░░░░░  23%  ↓ 待加强
─────────────────────────────────
```

### 6.3 入口位置

- 学生主页 (`/student`) 顶部 Banner：**「今日有 N 个知识点待复习」**
- 侧边导航新增「今日复习」菜单项（带红点数量提示）

---

## 七、实施计划

### Day 1：后端核心

- [ ] 实现复习调度引擎 `backend/services/review_scheduler.py`
- [ ] 实现题目生成适配器（复用 quiz + timeline_question_generator）
- [ ] 创建 `review_sessions` 表（Alembic migration）
- [ ] 实现 3 个 API 端点

### Day 2：前端今日复习页

- [ ] 创建 `/student/review/page.tsx`
- [ ] 实现题目卡片组件（支持选择题/问答/卡片三种形式）
- [ ] 答题 → 提交 → 反馈交互流程
- [ ] 完成后的总结弹窗

### Day 3：可视化 + 集成

- [ ] 掌握度热力图组件
- [ ] 嵌入学生 Dashboard
- [ ] 主页 Banner 和导航入口
- [ ] 连续打卡 streak 计算

### Day 4：测试与收尾

- [ ] 编写 `eval/review_system_smoke.py`
- [ ] 前端 lint + build 验证
- [ ] 更新 `SCHEMA.md`

---

## 八、验收标准

| 验收项 | 标准 |
|--------|------|
| 调度准确性 | strength < 0.5 且 > 3 天未复习的知识点必须出现在今日任务中 |
| 题目质量 | 生成题目与知识点标签相关，无明显错误 |
| Strength 更新 | 答对后 strength 可见增长，答错后降低 |
| 性能 | 生成今日任务 < 2s |
| 前端体验 | 完整答完 8 题流程无报错，显示总结 |
| 数据持久化 | 刷新页面后复习进度不丢失 |

---

## 九、依赖与风险

**依赖：**
- `memory_entries` 表需要有数据（用户至少完成过一次学习/批改）
- 新用户 `weakpoints` 为空时，降级为推荐「本周教材知识点」练习

**风险：**
- 生成题目质量依赖 LLM，需加 fallback（使用预生成题目缓存）
- `review_sessions` 每日重建逻辑需处理跨时区边界

---

*文档遵循项目 `docs/` 命名规范。修改功能后同步更新 `SCHEMA.md`。*
