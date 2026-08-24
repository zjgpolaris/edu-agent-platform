# EduAgent 自适应复习题内容质量闭环 v1.37 Spec

**创建时间：** 2026-08-24
**分析基线：** `main@856ffb5`
**状态：** Development Complete（local deterministic）· 教研与发布验证 Pending
**生产状态：** NOT_RUN；尚无教师盲审、真实学生效果、staging 或 production canary 证据

## 0. 决策与证据边界

本轮根据学生端 `/student/review` 的真实坏题，优先修复自适应复习质量，暂缓 v1.36 文档中建议的 Runtime Product Contract Closure backlog。

本地已确认并复现：

- `pilot-student / 2026-08-24 / 戊戌变法失败原因` 的缓存变式题把“思想启蒙”这一历史影响当成失败原因；
- 正确项明显长于三个干扰项，学生不理解知识也能按长度猜答案；
- 干扰项包含“完全由单一人物”“与时代背景无关”“教材没有提供任何”等送分表述；
- 题目仅增加“换一个角度思考”前缀，没有材料、情境或认知动作变化；
- GET 接口提前下发 `answer`，前端自行计算 `is_correct`，服务端信任客户端布尔值；
- 既有质量检查只验证题干和四个选项是否非空，无法拦截上述问题。

本 Spec 的本地确定性通过只能证明代码合同和五个 pilot 知识目标的题包质量门禁，不等于“已经达到全部初中历史命题标准”，更不等于学习效果或生产发布证明。

## 1. 学生标准映射

产品质量方向参考教育部发布的《义务教育课程方案和课程标准（2022年版）》及官方解读：义务教育课程应强化素养导向，在真实情境中解决问题；初中历史学习应能理解可信史料、说明历史事件并认识因果与联系。

- 课程标准发布页：<https://www.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html>
- 义务教育历史课程标准 PDF：<https://www.moe.gov.cn/srcsite/A26/s8001/202204/W020220420582345700037.pdf>
- 教育部课程方案解读：<https://hudong.moe.gov.cn/jyb_xwfb/s271/202204/t20220421_620066.html>

本轮把上述方向转成可执行的产品合同：

1. **史实正确：** 题目目标、正确答案和解析来自同一审定知识目标，不能把原因、影响、意义和目的混用；
2. **干扰有效：** 三个错误项来自同一知识范围的真实易混点，不使用绝对化或荒谬表述送分；
3. **先答后证：** 题干必须脱离反馈材料仍可独立作答；学生提交后才展示对照材料和解析，再进入下一题；
4. **难度可解释：** 学生看到的“基础辨析/先答后证”必须与实际 assessment difficulty 一致；
5. **判分可信：** 作答前不下发答案、反馈材料或解析，服务端根据 `selected_answer` 判分；
6. **证据安全：** 未审定或未通过门禁的题不发布、不判分、不改变薄弱点掌握证据。

## 2. 范围

### 2.1 本轮包含

- 复用 `knowledge_base/history/autotutor_content.json` 作为 AutoTutor 与自适应复习的单一审定 assessment 来源；
- 覆盖首批五个 pilot 知识目标：
  - 戊戌变法失败原因；
  - 洋务运动目的；
  - 赤壁之战的影响；
  - 辛亥革命历史意义；
  - 鸦片战争的影响；
- 题目质量合同 v3、旧缓存自动升级、未审定内容 fail closed；
- 按错误次数/连续答对证据进行基础辨析与“先答后证”选题；
- GET 答案与反馈材料脱敏、POST 服务端判分后再返回材料、事务化幂等证据回写；
- 学生端材料、难度和自适应原因的教学化呈现；
- 后端 deterministic eval、前端单测和生产构建。

### 2.2 本轮不包含

- 全册、全年级或其他学科题库覆盖；
- 把一次 LLM 生成直接认定为教研审定题；
- 主观题、综合材料题自动评分；
- 教师审题工作台和题包发布审批流；
- 真实 PostgreSQL 并发、真实学生学习增益或生产 canary。

## 3. 实现架构

```text
weakpoints(wrong_count, correct_streak)
  -> review_service._pick_question
      -> build_curated_review_question
          -> autotutor_content.json 审定 assessment
          -> quality contract v3
      -> 无审定 assessment: blocked（不出题）
  -> review_sessions（内部保存答案）
  -> GET public_review_session（答案/反馈材料/解析/option feedback 脱敏）
  -> 学生提交 selected_answer
  -> 服务端判分
  -> 同一事务
      |- CAS 更新 review_sessions
      |- 幂等写 weakpoint_evidence
      `- 幂等写 learning_events
  -> 仅本题提交后返回对照材料、答案与解析
  -> 学生查看反馈后进入下一题
```

AutoTutor 内容包是本轮唯一审定题源；自适应复习不再维护第二套通用历史选择题真相源。

## 4. 题目质量合同 v3

每道可发布题必须包含：

```json
{
  "question_id": "wuxu-cause-exit-1",
  "tag": "戊戌变法失败原因",
  "material": "作答后展示的对照材料",
  "material_timing": "after_answer",
  "question": "不依赖隐藏材料也能理解的明确设问",
  "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
  "answer": "A",
  "explanation": "审定解析",
  "difficulty": "medium",
  "cognitive_action": "apply",
  "quality_contract_version": 3,
  "quality_status": "verified"
}
```

确定性门禁至少拒绝：

- 题干/选项/答案结构错误；
- 空选项、重复选项、占位文案；
- 已知绝对化/荒谬送分干扰项；
- 正确项长度显著泄露答案；
- 巩固题没有作答后反馈材料，或错误配置成作答前显示；
- 题干含“该材料/根据材料/由此/这些变化”等对隐藏材料的引用；
- 缺少 difficulty/cognitive action；
- 旧版或非 `verified` 题目。

门禁不是通用语义判定器。因此未进入审定内容包的 LLM 草稿即使结构通过，也不能自动升级为 `verified`。

## 5. 自适应选题策略

| 学习证据 | 学生任务 | 目标 |
|---|---|---|
| `wrong_count = 1`, `correct_streak = 0` | easy 基础辨析 | 核对核心史实或概念边界 |
| `wrong_count = 2~3` | medium 先答后证 | 先独立检索记忆，再用对照材料纠偏 |
| `correct_streak = 1` | medium 先答后证 | 先独立作答，再确认理解后形成掌握证据 |
| `wrong_count >= 4`, streak 未建立 | easy 基础辨析 | 降低额外认知负担，先稳住关键史实 |
| 无审定 assessment | blocked | 不计分、不改变掌握结果 |

截图中的 `wrong_count=2` 因此升级为 `wuxu-cause-exit-1`：学生先回答“从政治力量基础看，戊戌变法失败说明什么问题”；提交后再看到“只依靠少数上层人物、没有可靠军队和广泛支持”的对照材料与解析，然后进入下一题。

## 6. API 与安全合同

### 6.1 GET 今日复习

`GET /api/students/{student_id}/review/today`

公开响应禁止包含：

- `answer`；
- `material`（当 `material_timing=after_answer`）；
- `explanation`；
- `option_feedback`；
- 内容包内部 `source_ids`。

### 6.2 POST 作答

```json
{
  "task_index": 0,
  "selected_answer": "A"
}
```

客户端不再提交 `is_correct`。服务端读取内部题目答案并判分，随后在本题响应中返回 `material + answer + explanation`；同一题同一答案重放返回原结果，同一题改答案返回 `409`。

业务副作用使用稳定 effect key：

```text
review:{student_id}:{date}:{task_index}:{question_id}
```

session CAS、`weakpoint_evidence` 和 `learning_events` 在同一事务内提交，防止重复点击产生两次掌握证据。

## 7. 旧数据升级与失败策略

- 打开复习页时，未完成且不满足 v3 合同的旧题会重新从审定内容包选择；
- 截图中的本地缓存已自动升级为 `wuxu-cause-exit-1`；
- 作答前的公开 payload 已确认不包含答案和作答后反馈材料；
- 无审定题时返回学生可理解的阻断信息；
- blocked 题不能提交，因此不会污染 weakpoint/mastery evidence。

## 8. 验收证据

### 8.1 已通过（local deterministic）

- `adaptive_review_question_quality_eval`：8/8；
- `review_system_smoke`：7/7；
- `variant_question_smoke`：6/6；
- `weakpoints_smoke`：8/8；
- `learning_closure_smoke`：4/4；
- `assignment_review_loop_smoke`：6/6；
- full quick gate：62/63 suites、286/287 cases；唯一 skip 为缺少外部模型凭证的既有 `history_character_smoke`；
- 前端专项：ReviewTab 1/1；
- 前端全量：lint、8 files / 22 tests、Next.js production build；
- 当前本地 `pilot-student`：medium、variant、quality verified，作答前答案和对照材料均未公开、质量原因 0。

### 8.2 尚未运行

- 历史教师对题干、答案、干扰项和难度的盲审；
- 真实初中生可理解性、猜测率、完成时长与学习保持效果；
- 五个 pilot 目标之外的审定题包；
- 真实 PostgreSQL 并发；
- staging / production canary。

## 9. 完成定义

本地开发切片只有在以下条件满足时标记 Development Complete：

1. 截图旧题被质量门禁拒绝并自动替换；
2. 五个 pilot 知识目标的基础题和先答后证题均通过 v3；
3. 原因/影响不再错位，正确项长度不泄题；
4. 作答前公开响应答案和反馈材料字段均为 0；
5. 服务端判分且证据写入幂等；
6. 未审定内容 fail closed；
7. 专项后端、前端 lint/unit/build 无回归；
8. 未运行证据被明确保留为 `NOT_RUN`。

截至 2026-08-24，第 1–7 项已获得本地确定性证据，第 8 项已如实记录；因此本切片为 **Development Complete（local deterministic）**，但尚不能标记为生产发布完成或“已证明符合全部初中生练习题标准”。
