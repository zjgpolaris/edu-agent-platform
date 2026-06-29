# 拍照批改闭环开发文档

**创建时间：** 2026-06-23
**迭代目标：** 完善拍照批改功能的前端体验，形成学生批改→错题本→复习的完整学习闭环
**预计工期：** 1-2 周

---

## 一、功能概述

### 1.1 背景

当前拍照批改功能的后端逻辑已基本完整：
- 支持选择题、简答题、材料题的 OCR 识别和结构化抽取
- 支持作业批改和评分
- 已自动记录学习事件和错题本（`weakpoint_service.py`）
- 已支持教师审核流（`review_store.py`）

但前端体验存在以下缺口：
1. 批改结果页展示不完整，缺少分数、知识点标签、解析等关键信息
2. 错题本前端页面不完整，学生无法查看自己的薄弱点
3. 教师审核流前端不完整，教师无法进行 accept/reject 操作

### 1.2 目标

1. **批改结果页体验完善**：清晰展示分数、各题详情、知识点标签、解析
2. **错题本前端页面**：标签云 + 列表视图，支持点击跳转学习
3. **教师审核流前端**：待审核列表、accept/reject 操作、"加入回归测试"

---

## 二、技术方案

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        前端层                                │
├─────────────────────────────────────────────────────────────┤
│  /homework-grading          批改结果页（完善）              │
│  /student/weakpoints         错题本页面（新建）              │
│  /teacher/grading            教师审核页（完善）              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        后端层                                │
├─────────────────────────────────────────────────────────────┤
│  POST /api/homework/grade          批改接口（已有）          │
│  GET  /api/students/{id}/weakpoints 错题本接口（已有）       │
│  POST /api/students/{id}/weakpoints/{tag}/delete 删除错题   │
│  GET  /api/homework/reviews         审核列表（已有）          │
│  POST /api/homework/reviews/{id}/decision 审核决策（已有）   │
│  POST /api/eval/save-case          加入回归测试（新增）       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        数据层                                │
├─────────────────────────────────────────────────────────────┤
│  SQLite: weakpoints, homework_reviews, learning_events       │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
学生上传作业
  → OCR 识别
  → 结构化抽取
  → 人工校对（如需要）
  → AI 批改
  → 自动写入 learning_events
  → 自动写入 weakpoints
  → 前端展示批改结果
  → 学生查看错题本
  → 点击知识点 → 跳转学习
  → 答对 → 删除 weakpoint
```

---

## 三、后端改动

### 3.1 新增接口：加入回归测试

**文件：** `backend/api/main.py`

```python
@app.post("/api/eval/save-case")
async def save_eval_case(
    request: Request,
    case_data: dict[str, Any],
):
    """教师 reject 后，将案例保存到 eval/datasets/ 用于回归测试"""
    case_id = case_data.get("case_id") or str(uuid4())
    dataset_name = case_data.get("dataset", "homework_grading_smoke_cases")
    filepath = f"eval/datasets/{dataset_name}.json"

    # 读取现有数据
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {"cases": []}

    # 查找并更新或追加
    existing_idx = next((i for i, c in enumerate(data["cases"]) if c.get("case_id") == case_id), None)
    if existing_idx is not None:
        data["cases"][existing_idx] = case_data
    else:
        data["cases"].append(case_data)

    # 保存
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return {"case_id": case_id, "saved": True}
```

### 3.2 错题本删除接口确认

**文件：** `backend/api/main.py`

确认以下接口已存在：

```python
@app.delete("/api/students/{student_id}/weakpoints/{knowledge_tag}")
async def delete_weakpoint(
    student_id: str,
    knowledge_tag: str,
):
    """删除错题本中的某个知识点"""
    from services.weakpoint_service import delete_weakpoint
    delete_weakpoint(student_id, knowledge_tag)
    return {"deleted": True}
```

---

## 四、前端改动

### 4.1 批改结果页完善

**文件：** `frontend/app/homework-grading/page.tsx`

#### 改动点

1. **分数展示区**
   - 大字显示总分和等级
   - 进度条可视化得分率

2. **各题批改详情**
   - 题号、题目、学生答案
   - 正误标识（✅/❌）
   - 得分/满分
   - 知识点标签（可点击）
   - 解析和修改建议

3. **薄弱点汇总**
   - 列出本次批改发现的薄弱点
   - 每个薄弱点显示来源（批改/游戏/测验）

4. **追问题**
   - 展示 follow_up_quiz
   - 支持点击展开答案

#### 组件结构

```tsx
// 批改结果页组件结构
<HomeworkGradingResult>
  <ScoreHeader>
    <TotalScore>85</TotalScore>
    <GradeLevel>良好</GradeLevel>
    <ScoreBar>85%</ScoreBar>
  </ScoreHeader>

  <QuestionList>
    {items.map(item => (
      <QuestionItem key={item.item_id}>
        <QuestionHeader>
          <QuestionNumber>第 {item.item_id} 题</QuestionNumber>
          <CorrectBadge isCorrect={item.is_correct} />
        </QuestionHeader>
        <QuestionText>{item.question}</QuestionText>
        <StudentAnswer>{item.student_answer}</StudentAnswer>
        <ScoreDisplay>{item.score}/{item.max_score}</ScoreDisplay>
        <KnowledgeTags>
          {item.knowledge_tags.map(tag => (
            <Tag key={tag} onClick={() => jumpToLearning(tag)}>
              {tag}
            </Tag>
          ))}
        </KnowledgeTags>
        <Explanation>{item.explanation}</Explanation>
        <RevisionSuggestion>{item.revision_suggestion}</RevisionSuggestion>
      </QuestionItem>
    ))}
  </QuestionList>

  <WeakPointsSection>
    <SectionTitle>本次发现的薄弱点</SectionTitle>
    <WeakPointList>
      {weak_points.map(wp => (
        <WeakPointItem key={wp}>{wp}</WeakPointItem>
      ))}
    </WeakPointList>
  </WeakPointsSection>

  <FollowUpQuiz>
    <SectionTitle>巩固练习</SectionTitle>
    {follow_up_quiz.map((quiz, idx) => (
      <QuizItem key={idx}>
        <QuizQuestion>{quiz.question}</QuizQuestion>
        <QuizAnswer>{quiz.answer}</QuizAnswer>
      </QuizItem>
    ))}
  </FollowUpQuiz>
</HomeworkGradingResult>
```

### 4.2 错题本页面（新建）

**文件：** `frontend/app/student/weakpoints/page.tsx`

#### 功能

1. **标签云视图**
   - 按错误频率调整标签大小
   - 点击标签跳转到相关学习内容

2. **列表视图**
   - 知识点、错误次数、最近出错时间、来源图标
   - 支持删除单个错题
   - 支持清空错题本

3. **跳转逻辑**
   - 点击知识点 → 跳转到教材相关章节
   - 或发起历史人物对话

#### 组件结构

```tsx
// 错题本页面组件结构
<WeakpointsPage>
  <PageHeader>
    <Title>错题本</Title>
    <ClearButton onClick={clearAll}>清空错题本</ClearButton>
  </PageHeader>

  <ViewToggle>
    <Tab active={view === 'cloud'} onClick={() => setView('cloud')}>标签云</Tab>
    <Tab active={view === 'list'} onClick={() => setView('list')}>列表</Tab>
  </ViewToggle>

  {view === 'cloud' && (
    <TagCloud>
      {weakpoints.map(wp => (
        <Tag
          key={wp.knowledge_tag}
          size={getSizeByCount(wp.wrong_count)}
          onClick={() => jumpToLearning(wp.knowledge_tag)}
        >
          {wp.knowledge_tag}
        </Tag>
      ))}
    </TagCloud>
  )}

  {view === 'list' && (
    <WeakpointList>
      {weakpoints.map(wp => (
        <WeakpointRow key={wp.knowledge_tag}>
          <KnowledgeTag>{wp.knowledge_tag}</KnowledgeTag>
          <WrongCount>{wp.wrong_count} 次</WrongCount>
          <LastWrong>{formatDate(wp.last_wrong_at)}</LastWrong>
          <SourceIcon source={wp.source} />
          <DeleteButton onClick={() => deleteWeakpoint(wp.knowledge_tag)}>
            删除
          </DeleteButton>
        </WeakpointRow>
      ))}
    </WeakpointList>
  )}
</WeakpointsPage>
```

### 4.3 教师审核流完善

**文件：** `frontend/app/teacher/grading/page.tsx`

#### 功能

1. **待审核列表**
   - 显示 pending 状态的批改记录
   - 每条记录显示：学生、提交时间、分数、知识点

2. **审核详情**
   - 点击记录展开详情
   - 显示原始题目和学生答案
   - 显示 AI 批改结果

3. **审核操作**
   - Accept：确认 AI 批改结果
   - Edit：修改分数和评语
   - Reject：拒绝并填写原因
   - "加入回归测试"：保存案例到 eval/datasets/

#### 组件结构

```tsx
// 教师审核页组件结构
<TeacherGradingPage>
  <Tabs>
    <Tab active={tab === 'pending'} onClick={() => setTab('pending')}>
      待审核 ({pendingCount})
    </Tab>
    <Tab active={tab === 'history'} onClick={() => setTab('history')}>
      历史记录
    </Tab>
  </Tabs>

  {tab === 'pending' && (
    <ReviewList>
      {reviews.map(review => (
        <ReviewCard key={review.id}>
          <ReviewHeader>
            <StudentName>{review.student_id}</StudentName>
            <SubmitTime>{formatDate(review.created_at)}</SubmitTime>
            <AIScore>AI 评分: {review.grade_result.total_score}</AIScore>
          </ReviewHeader>

          <ReviewContent>
            <OriginalQuestions>
              {review.grade_request.items.map(item => (
                <QuestionItem key={item.item_id}>
                  <Question>{item.question}</Question>
                  <Answer>{item.student_answer}</Answer>
                </QuestionItem>
              ))}
            </OriginalQuestions>

            <AIGrading>
              <Score>{review.grade_result.total_score}</Score>
              <Feedback>{review.grade_result.overall_feedback}</Feedback>
            </AIGrading>
          </ReviewContent>

          <ReviewActions>
            <Button variant="accept" onClick={() => accept(review.id)}>
              确认
            </Button>
            <Button variant="edit" onClick={() => openEditModal(review)}>
              修改
            </Button>
            <Button variant="reject" onClick={() => openRejectModal(review)}>
              拒绝
            </Button>
          </ReviewActions>
        </ReviewCard>
      ))}
    </ReviewList>
  )}

  {/* 拒绝弹窗 */}
  <RejectModal>
    <ReasonInput placeholder="请填写拒绝原因" />
    <Checkbox label="加入回归测试" />
    <Button onClick={submitReject}>提交</Button>
  </RejectModal>
</TeacherGradingPage>
```

---

## 五、测试计划

### 5.1 单元测试

| 测试项 | 文件 | 说明 |
|--------|------|------|
| 错题本删除 | `eval/weakpoints_smoke.py` | 确认删除功能正常 |
| 审核流决策 | `eval/homework_grading_smoke.py` | 确认 accept/reject 正常 |
| 回归测试保存 | `eval/eval_case_smoke.py`（新建） | 确认案例保存到 datasets |

### 5.2 集成测试

1. **完整批改流程**
   - 上传作业 → OCR → 抽取 → 批改 → 查看结果 → 查看错题本

2. **教师审核流程**
   - 学生提交 → 教师待审核列表 → accept/reject → 回归测试

3. **错题本闭环**
   - 查看错题本 → 点击知识点 → 学习 → 答对 → 删除错题

### 5.3 E2E 测试

使用 Playwright 或 Cypress 编写端到端测试：

```typescript
// homework-grading.e2e.ts
test('complete homework grading flow', async ({ page }) => {
  // 1. 上传作业
  await page.goto('/homework-grading');
  await page.setInputFiles('input[type="file"]', 'test-homework.png');
  await page.click('button[type="submit"]');

  // 2. 等待批改完成
  await page.waitForSelector('[data-testid="grading-result"]');

  // 3. 验证分数显示
  const score = await page.textContent('[data-testid="total-score"]');
  expect(score).toBeTruthy();

  // 4. 验证知识点标签
  const tags = await page.$$('[data-testid="knowledge-tag"]');
  expect(tags.length).toBeGreaterThan(0);

  // 5. 跳转到错题本
  await page.click('[data-testid="view-weakpoints"]');
  await page.waitForURL('/student/weakpoints');

  // 6. 验证错题本显示
  const weakpoints = await page.$$('[data-testid="weakpoint-item"]');
  expect(weakpoints.length).toBeGreaterThan(0);
});
```

---

## 六、验收标准

### 6.1 批改结果页

- [ ] 分数大字显示，等级清晰
- [ ] 各题详情完整（题目、答案、得分、解析）
- [ ] 知识点标签可点击跳转
- [ ] 薄弱点汇总展示
- [ ] 追问题可展开查看答案

### 6.2 错题本页面

- [ ] 标签云视图按频率调整大小
- [ ] 列表视图显示完整信息
- [ ] 支持删除单个错题
- [ ] 支持清空错题本
- [ ] 点击知识点可跳转学习

### 6.3 教师审核流

- [ ] 待审核列表正确显示 pending 记录
- [ ] accept 操作正确更新状态
- [ ] reject 操作正确记录原因
- [ ] "加入回归测试"正确保存案例
- [ ] edit 操作可修改分数和评语

### 6.4 性能

- [ ] 批改结果页加载时间 < 2s
- [ ] 错题本列表加载时间 < 1s
- [ ] 审核列表加载时间 < 1s

---

## 七、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 前端组件复杂度高 | 开发周期延长 | 复用现有组件，分阶段实现 |
| 错题本跳转逻辑复杂 | 用户体验不佳 | 先实现简单跳转，后续优化推荐算法 |
| 教师审核流权限控制 | 安全风险 | 确认前端权限校验，后端二次验证 |

---

## 八、相关文档

- [`202606221438-iteration-plan-dev.md`](202606221438-iteration-plan-dev.md) — 迭代计划
- [`202606221500-portfolio-overview-dev.md`](202606221500-portfolio-overview-dev.md) — 作品集概览
- [`backend/homework_grading/service.py`](../backend/homework_grading/service.py) — 批改服务
- [`backend/services/weakpoint_service.py`](../backend/services/weakpoint_service.py) — 错题本服务
- [`backend/homework_grading/review_store.py`](../backend/homework_grading/review_store.py) — 审核存储

---

## 九、文件改动汇总

```
backend/
  api/main.py                    - 错题本接口已完备（无需改动）

frontend/app/
  homework-grading/page.tsx      - 批改结果页已完善（无需改动）
  (student)/student/weakpoints/page.tsx - 错题本页面已存在，添加删除功能 ✅
  teacher/grading/page.tsx       - 新建教师审核页 ✅

eval/
  run_smoke_tests.py            - 新建统一 smoke test runner ✅
```

## 十、完成状态

| 任务 | 状态 | 说明 |
|------|------|------|
| 后端 /api/eval/save-case 接口 | ✅ 已存在 | main.py 中已有 eval_save_case 接口 |
| 错题本删除接口 | ✅ 已存在 | main.py 中已有 delete_student_weakpoint 接口 |
| 批改结果页完善 | ✅ 已完成 | page.tsx 已包含分数、详情、知识点、解析 |
| 错题本前端页面 | ✅ 已完成 | 使用现有页面，添加删除单个错题功能 |
| 教师审核流前端 | ✅ 已完成 | /teacher/grading/page.tsx |
| 统一 smoke test | ✅ 已完成 | eval/run_smoke_tests.py，7/7 测试通过 |
