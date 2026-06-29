# 教师端功能增强开发文档

**创建时间：** 2026-06-23
**迭代目标：** 增强教师端功能，提升教师管理效率和教学效果
**预计工期：** 1-2 周

---

## 一、功能概述

### 1.1 背景

当前教师端已具备以下基础功能：
- 班级学生列表查看 (`/teacher/dashboard`)
- 学生学情档案查看 (`/teacher/students/[id]`)
- 作业批改审核流 (`/teacher/grading`)

但以下功能缺口影响教师使用体验：
1. **缺少班级学情概览**：无法快速了解班级整体学习情况
2. **缺少批量操作**：无法批量查看多个学生画像或批量审核
3. **缺少教师资料库管理**：教师无法查看和管理学生上传的资料
4. **缺少教学建议生成**：无法基于学生学情自动生成教学建议

### 1.2 目标

1. **班级学情概览**：班级整体得分、薄弱点分布、活跃度统计
2. **教师资料库管理**：查看学生上传资料、审核内容
3. **批量学生画像**：批量查看多个学生学情
4. **教学建议生成**：基于班级学情自动生成教学建议

---

## 二、技术方案

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        前端层                                │
├─────────────────────────────────────────────────────────────┤
│  /teacher/dashboard           班级总览（增强）              │
│  /teacher/class-analytics     班级学情分析（新建）          │
│  /teacher/materials           教师资料库（新建）            │
│  /teacher/batch-students      批量学生画像（新建）          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        后端层                                │
├─────────────────────────────────────────────────────────────┤
│  GET  /api/teacher/class-analytics    班级学情分析（新增）  │
│  GET  /api/teacher/materials          教师资料库（新增）      │
│  GET  /api/teacher/teaching-suggestions 教学建议（新增）    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        数据层                                │
├─────────────────────────────────────────────────────────────┤
│  SQLite: learning_events, student_profiles, materials       │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
教师登录
  → 查看班级总览（学生列表 + 整体统计）
  → 点击班级学情分析
  → 查看班级整体得分、薄弱点分布、活跃度
  → 点击教学建议
  → AI 基于班级学情生成教学建议
  → 查看学生资料库
  → 审核学生上传资料
```

---

## 三、后端改动

### 3.1 班级学情分析接口

**文件：** `backend/api/main.py`

```python
from pydantic import BaseModel, Field
from typing import Optional

class ClassAnalytics(BaseModel):
    total_students: int
    active_students: int  # 近7天有学习记录
    average_quiz_score: Optional[float]
    average_game_score: Optional[float]
    weak_topics_distribution: dict[str, int]  # 薄弱点及出现次数
    strong_topics_distribution: dict[str, int]  # 优势点及出现次数
    top_weak_topics: list[str]  # Top 5 薄弱点
    activity_by_day: dict[str, int]  # 每日活跃人数（近7天）

@app.get("/api/teacher/class-analytics")
async def teacher_class_analytics(actor: Actor = Depends(require_auth)):
    """获取班级整体学情分析"""
    require_teacher_actor(actor)

    from student_profile import init_db, _connect
    init_db()

    with _connect() as conn:
        # 获取所有学生
        students = conn.execute("SELECT DISTINCT student_id FROM student_profiles").fetchall()
        student_ids = [row["student_id"] for row in students]

        # 近7天活跃学生
        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        active_rows = conn.execute(
            "SELECT DISTINCT student_id FROM learning_events WHERE created_at >= ?",
            (seven_days_ago,)
        ).fetchall()
        active_ids = {row["student_id"] for row in active_rows}

        # 计算平均分
        profiles = conn.execute("SELECT * FROM student_profiles").fetchall()
        quiz_scores = [row["quiz_avg_score"] for row in profiles if row["quiz_avg_score"] is not None]
        game_scores = [row["game_avg_score"] for row in profiles if row["game_avg_score"] is not None]

        # 薄弱点分布
        weak_rows = conn.execute("SELECT weak_topics FROM student_profiles").fetchall()
        weak_dist: dict[str, int] = {}
        for row in weak_rows:
            topics = _json_load(row["weak_topics"], [])
            for topic in topics:
                weak_dist[topic] = weak_dist.get(topic, 0) + 1

        # 优势点分布
        strong_rows = conn.execute("SELECT strong_topics FROM student_profiles").fetchall()
        strong_dist: dict[str, int] = {}
        for row in strong_rows:
            topics = _json_load(row["strong_topics"], [])
            for topic in topics:
                strong_dist[topic] = strong_dist.get(topic, 0) + 1

        # 每日活跃度
        activity_rows = conn.execute(
            "SELECT DATE(created_at) as date, COUNT(DISTINCT student_id) as count "
            "FROM learning_events WHERE created_at >= ? GROUP BY DATE(created_at)",
            (seven_days_ago,)
        ).fetchall()
        activity_by_day = {row["date"]: row["count"] for row in activity_rows}

    return ClassAnalytics(
        total_students=len(student_ids),
        active_students=len(active_ids),
        average_quiz_score=sum(quiz_scores) / len(quiz_scores) if quiz_scores else None,
        average_game_score=sum(game_scores) / len(game_scores) if game_scores else None,
        weak_topics_distribution=weak_dist,
        strong_topics_distribution=strong_dist,
        top_weak_topics=sorted(weak_dist.items(), key=lambda x: x[1], reverse=True)[:5],
        activity_by_day=activity_by_day,
    ).model_dump()
```

### 3.2 教师资料库接口

**文件：** `backend/api/main.py`

```python
@app.get("/api/teacher/materials")
async def teacher_list_materials(actor: Actor = Depends(require_auth)):
    """教师查看所有学生上传的资料"""
    require_teacher_actor(actor)

    from materials.store import list_material_records, _connect, _json_load
    from student_profile import init_db

    init_db()
    with _connect() as conn:
        # 获取所有学生的 owner_key
        students = conn.execute("SELECT DISTINCT student_id FROM student_profiles").fetchall()
        student_ids = [f"actor:{row['student_id']}" for row in students]

    materials = []
    for owner_key in student_ids:
        materials.extend(list_material_records(owner_key))

    return {"materials": [m.model_dump() for m in materials]}
```

### 3.3 教学建议生成接口

**文件：** `backend/api/main.py`

```python
class TeachingSuggestionRequest(BaseModel):
    focus: str = Field(default="weak_topics", description="建议重点：weak_topics, strong_topics, activity")

@app.post("/api/teacher/teaching-suggestions")
async def teacher_teaching_suggestions(req: TeachingSuggestionRequest, actor: Actor = Depends(require_auth)):
    """基于班级学情生成教学建议"""
    require_teacher_actor(actor)

    # 获取班级学情
    analytics = await teacher_class_analytics(actor)

    # 构建提示词
    weak_topics = analytics.get("top_weak_topics", [])
    weak_text = "、".join([t[0] for t in weak_topics[:5]])

    prompt = f"""
请为以下班级学情生成教学建议：

班级概况：
- 学生总数：{analytics['total_students']}
- 活跃学生：{analytics['active_students']}
- 平均测验分：{analytics.get('average_quiz_score', '无数据')}
- 平均游戏分：{analytics.get('average_game_score', '无数据')}

主要薄弱点：{weak_text or '暂无'}

请生成：
1. 3-5 条教学建议
2. 推荐的课堂活动
3. 需要重点讲解的知识点
4. 课后作业建议

输出 JSON 格式：
{{
  "suggestions": ["建议1", "建议2", ...],
  "activities": ["活动1", "活动2", ...],
  "key_topics": ["知识点1", "知识点2", ...],
  "homework_suggestions": ["作业建议1", "作业建议2", ...]
}}
"""

    response = llm_material.invoke([{"role": "user", "content": prompt}]).content
    try:
        payload = parse_json_object(response)
    except StructuredOutputError:
        payload = {"suggestions": [], "activities": [], "key_topics": [], "homework_suggestions": []}

    return payload
```

---

## 四、前端改动

### 4.1 班级学情分析页（新建）

**文件：** `frontend/app/teacher/class-analytics/page.tsx`

#### 功能

1. **整体统计卡片**
   - 学生总数、活跃学生数
   - 平均测验分、平均游戏分
   - 活跃度趋势图（近7天）

2. **薄弱点分布**
   - 词云或柱状图展示薄弱点
   - Top 5 薄弱点列表

3. **优势点分布**
   - 词云或柱状图展示优势点

#### 组件结构

```tsx
<ClassAnalyticsPage>
  <PageHeader>
    <Title>班级学情分析</Title>
    <DateRangeSelector />
  </PageHeader>

  <StatsGrid>
    <StatCard label="学生总数" value={totalStudents} />
    <StatCard label="活跃学生" value={activeStudents} />
    <StatCard label="平均测验分" value={averageQuizScore} />
    <StatCard label="平均游戏分" value={averageGameScore} />
  </StatsGrid>

  <ActivityChart data={activityByDay} />

  <Section title="薄弱点分布">
    <WeakPointCloud data={weakTopicsDistribution} />
    <WeakPointList items={topWeakTopics} />
  </Section>

  <Section title="优势点分布">
    <StrongPointCloud data={strongTopicsDistribution} />
  </Section>

  <TeachingSuggestionsButton onClick={generateSuggestions} />
</ClassAnalyticsPage>
```

### 4.2 教师资料库页（新建）

**文件：** `frontend/app/teacher/materials/page.tsx`

#### 功能

1. **资料列表**
   - 显示所有学生上传的资料
   - 按学生、时间、类型筛选
   - 显示资料预览

2. **资料详情**
   - 查看资料内容
   - 查看学生标注
   - 添加教师批注

#### 组件结构

```tsx
<TeacherMaterialsPage>
  <PageHeader>
    <Title>学生资料库</Title>
    <FilterBar />
  </PageHeader>

  <MaterialList>
    {materials.map(material => (
      <MaterialCard key={material.material_id}>
        <StudentInfo>{material.student_id}</StudentInfo>
        <MaterialInfo>{material.title}</MaterialInfo>
        <Preview>{material.preview}</Preview>
        <Actions>
          <Button onClick={viewDetail}>查看</Button>
          <Button onClick={addNote}>批注</Button>
        </Actions>
      </MaterialCard>
    ))}
  </MaterialList>
</TeacherMaterialsPage>
```

### 4.3 教学建议弹窗

**文件：** 在班级学情分析页中集成

#### 功能

1. **生成教学建议**
   - 基于班级学情自动生成
   - 显示教学建议、课堂活动、重点知识点、作业建议

2. **保存建议**
   - 保存到本地或后端
   - 导出为文档

---

## 五、测试计划

### 5.1 单元测试

| 测试项 | 文件 | 说明 |
|--------|------|------|
| 班级学情分析 | `eval/class_analytics_smoke.py` | 确认统计计算正确 |
| 教师资料库 | `eval/teacher_materials_smoke.py` | 确认教师可查看学生资料 |
| 教学建议生成 | `eval/teaching_suggestions_smoke.py` | 确认建议生成正常 |

### 5.2 集成测试

1. **班级学情分析流程**
   - 教师登录 → 查看班级学情 → 验证数据正确性

2. **教师资料库流程**
   - 教师登录 → 查看学生资料 → 筛选资料 → 查看详情

3. **教学建议生成流程**
   - 教师登录 → 查看班级学情 → 生成教学建议 → 验证建议质量

---

## 六、验收标准

### 6.1 班级学情分析页

- [x] 整体统计卡片显示正确
- [x] 活跃度趋势图显示近7天数据
- [x] 薄弱点分布展示正确
- [x] 优势点分布展示正确

### 6.2 教师资料库页

- [x] 资料列表显示所有学生资料
- [x] 筛选功能正常
- [x] 资料详情可查看
- [ ] 教师批注可添加（后续迭代）

### 6.3 教学建议生成

- [x] 建议生成正常
- [x] 建议内容合理
- [ ] 可保存建议（后续迭代）

---

## 七、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 班级学情计算性能 | 页面加载慢 | 使用缓存、分页查询 |
| 教学建议质量 | 建议不准确 | 优化提示词、人工审核 |
| 教师资料库权限 | 安全风险 | 确认前端权限校验，后端二次验证 |

---

## 八、相关文档

- [`202606221438-iteration-plan-dev.md`](202606221438-iteration-plan-dev.md) — 迭代计划
- [`202606231110-homework-grading-closed-loop-dev.md`](202606231110-homework-grading-closed-loop-dev.md) — 拍照批改闭环

---

## 九、文件改动汇总

```
backend/
  api/main.py                    - 新增班级学情、教师资料库、教学建议接口 ✅

frontend/app/teacher/
  class-analytics/page.tsx       - 新建班级学情分析页 ✅
  materials/page.tsx             - 新建教师资料库页 ✅
  dashboard/page.tsx             - 添加导航链接 ✅

eval/
  teacher_features_smoke.py      - 新建教师功能 smoke test ✅
  run_smoke_tests.py             - 添加 teacher_features_smoke.py ✅
```

---

## 十、完成状态

| 任务 | 状态 | 说明 |
|------|------|------|
| 后端班级学情分析接口 | ✅ 已完成 | GET /api/teacher/class-analytics |
| 后端教师资料库接口 | ✅ 已完成 | GET /api/teacher/materials |
| 后端教学建议生成接口 | ✅ 已完成 | POST /api/teacher/teaching-suggestions |
| 前端班级学情分析页 | ✅ 已完成 | /teacher/class-analytics/page.tsx |
| 前端教师资料库页 | ✅ 已完成 | /teacher/materials/page.tsx |
| 教师导航栏 | ✅ 已完成 | /teacher/dashboard 添加导航链接 |
| smoke tests | ✅ 已完成 | eval/teacher_features_smoke.py |
