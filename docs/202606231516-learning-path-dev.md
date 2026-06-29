# 学习路径优化开发文档

**创建时间：** 2026-06-23
**迭代目标：** 实现学习路径可视化，基于错题本智能推荐，形成个性化学习闭环
**预计工期：** 1 周

---

## 一、功能概述

### 1.1 背景

当前项目已有：
- 后端 `student_profile.py` 的 `suggest_review_plan` 函数
- API `GET /api/students/{student_id}/review-plan` 已实现
- 前端学习助手会展示复习建议（通过 `profile_context.review_plan.recommended_actions`）
- 错题本功能已完成（`/student/weakpoints`）

但缺少：
- 独立的学习路径可视化页面
- 学习进度可视化
- 错题本与学习路径的联动

### 1.2 目标

创建独立的学习路径页面，展示：
- 基于错题本的智能推荐
- 个性化学习计划
- 学习进度可视化
- 答对题目后自动移除错题

### 1.3 展示内容

- 学习路径时间线（按知识点/主题组织）
- 每个知识点的掌握度
- 错题本与学习路径联动
- 学习进度追踪
- 复习建议

---

## 二、技术方案

### 2.1 学习路径数据结构

**后端 API 扩展**

```python
class LearningPath(BaseModel):
    student_id: str
    created_at: str
    updated_at: str
    weak_topics: list[str]  # 薄弱点列表
    strong_topics: list[str]  # 优势点列表
    recommended_actions: list[str]  # 推荐学习动作
    progress: dict[str, float]  # 各知识点进度
    milestones: list[dict]  # 学习里程碑
```

### 2.2 API 接口

**文件：** `backend/api/main.py`（新增）

```python
class LearningPathRequest(BaseModel):
    student_id: str
    include_completed: bool = False  # 是否包含已完成的知识点

@app.get("/api/students/{student_id}/learning-path")
async def get_learning_path(student_id: str, include_completed: bool = False, actor: Actor = Depends(require_auth)):
    """获取学生学习路径。"""
    from student_profile import suggest_review_plan, get_student_profile, get_weakpoints

    profile = get_student_profile(student_id)
    weakpoints = get_weakpoints(student_id)
    review_plan = suggest_review_plan(student_id, limit=10)

    # 构建学习路径
    weak_topics = profile.weak_topics or []
    strong_topics = profile.strong_topics or []
    recommended_actions = review_plan.get("recommended_actions", [])

    # 计算进度（简化版）
    progress = {}
    for topic in weak_topics:
        progress[topic] = 0.5  # 默认中等进度

    return {
        "student_id": student_id,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
        "weak_topics": weak_topics,
        "strong_topics": strong_topics,
        "recommended_actions": recommended_actions,
        "progress": progress,
        "milestones": [
            {"title": action, "completed": False} for action in recommended_actions
        ],
    }
```

---

## 三、前端改动

### 3.1 学习路径页面

**文件：** `frontend/app/student/learning-path/page.tsx`（新建）

```tsx
"use client"

import { useState, useEffect } from "react"
import { useAuth } from "@/contexts/AuthContext"
import { authHeaders } from "@/const apiBaseUrl || "http://localhost:8000"

interface LearningPath {
  student_id: string
  created_at: string
  updated_at: string
  weak_topics: string[]
  strong_topics: string[]
  recommended_actions: string[]
  progress: Record<string, number>
  milestones: Array<{ title: string; completed: boolean }>
}

export default function LearningPathPage() {
  const { user } = useAuth()
  const [path, setPath] = useState<LearningPath | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (user?.actorId) {
      fetchLearningPath()
    }
  }, [user?.actorId])

  const fetchLearningPath = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${apiBaseUrl}/api/students/${user.actorId}/learning-path`, {
        headers: authHeaders(user.token),
      })
      const data = await res.json()
      setPath(data)
    } catch (err) {
      console.error("Failed to fetch learning path", err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="learning-path-page">
      <h1>学习路径</h1>
      {loading && <p>加载中...</p>}
      {path && (
        <div className="path-container">
          <div className="weakness-section">
            <h2>薄弱知识点</h2>
            {path.weak_topics.length > 0 ? (
              <div className="topic-list">
                {path.weak_topics.map((topic, i) => (
                  <div key={i} className="topic-item">
                    <span className="topic-name">{topic}</span>
                    <span className="topic-progress">{(path.progress[topic] * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            ) : (
              <p>暂无薄弱知识点</p>
            )}
          </div>

          <div className="strength-section">
            <h2>优势知识点</h2>
            {path.strong_topics.length > 0 ? (
              <div className="topic-list">
                {path.strong_topics.map((topic, i) => (
                  <div key={i} className="topic-item strong">
                    <span className="topic-name">{topic}</span>
                    <span className="topic-progress">掌握</span>
                  </div>
                ))}
              </div>
            ) : (
              <p>暂无优势知识点</p>
            )}
          </div>

          <div className="recommendations-section">
            <h2>学习建议</h2>
            <ul>
              {path.recommended_actions.map((action, i) => (
                <li key={i}>
                  <input type="checkbox" id={`action-${i}`} />
                  <label htmlFor={`action-${i}`}>{action}</label>
                </li>
              ))}
            </ul>
          </div>

          <div className="milestones-section">
            <h2>学习里程碑</h2>
            <div className="milestone-list">
              {path.milestones.map((m, i) => (
                <div key={i} className={`milestone ${m.completed ? "completed" : ""}`}>
                  <div className="milestone-marker">{i + 1}</div>
                  <span>{m.title}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
```

### 3.2 错题本联动

**文件：** `frontend/app/student/weakpoints/page.tsx`（扩展）

在错题本页面添加"加入学习路径"按钮，点击后将知识点加入学习路径。

---

## 四、样式

**文件：** `frontend/app/globals.css`（添加）

```css
.learning-path-page {
  padding: 24px;
  max-width: 800px;
  margin: 0 auto;
}

.learning-path-page h1 {
  margin-bottom: 24px;
}

.path-container {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.weakness-section,
.strength-section,
.recommendations-section,
.milestones-section {
  background: #f5f5f5;
  padding: 16px;
  border-radius: 8px;
}

.weakness-section h2,
.strength-section h2,
.recommendations-section h2,
.milestones-section h2 {
  margin: 0 0 16px 0;
  font-size: 1.1rem;
  color: #333;
}

.topic-list {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.topic-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: white;
  border-radius: 4px;
}

.topic-item.strong {
  border-left: 4px solid #10b981;
}

.topic-name {
  font-weight: 600;
}

.topic-progress {
  font-size: 0.875rem;
  color: #666;
}

.recommendations-section ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.recommendations-section li {
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.milestone-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.milestone {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: white;
  border-radius: 4px;
}

.milestone.completed {
  background: #d1fae5;
}

.milestone-marker {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #10b981;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}
```

---

## 五、测试计划

### 5.1 单元测试

| 测试项 | 文件 | 说明 |
|--------|------|------|
| 学习路径 API | `eval/learning_path_smoke.py` | 确认 API 返回正确数据结构 |

### 5.2 集成测试

1. **学习路径流程**
   - 学生登录 → 查看学习路径 → 验证数据正确性

2. **错题本联动**
   - 学生答对题目 → 错题本自动移除 → 学习路径更新

---

## 六、验收标准

- [x] GET /api/students/{student_id}/learning-path 接口
- [ ] 学习路径页面
- [] 样式完成
- [ ] 错题本联动
- [ ] smoke tests 通过

---

## 七、相关文档

- [`202606231148-next-product-direction-analysis.md`](202606231148-next-product-direction-analysis.md) — 下一步产品方向分析
- [`202606221438-iteration-plan-dev.md`](202606221438-iteration-plan-dev.md) — 迭代计划

---

## 八、文件改动汇总

```
backend/
  api/main.py                   - 新增 GET /api/students/{student_id}/learning-path 接口
  student_profile.py              - 扩展 suggest_review_plan 返回进度信息

frontend/
  app/student/learning-path/page.tsx  - 新建学习路径页面
  app/student/weakpoints/page.tsx      - 扩展错题本联动

eval/
  learning_path_smoke.py           - 新建学习路径测试

docs/
  202606231516-learning-path-dev.md  - 本文档
```

---

## 九、完成状态

| 任务 | 状态 | 说明 |
|------|------|------|
| GET /api/learning-path API | ⏳ 待开始 | |
| 学习路径页面 | ⏳ 待开始 | |
| 样式 | ⏳ 待开始 | |
| 错题本联动 | ⏳ 待开始 | |
| smoke tests | ⏳ 待开始 | |
