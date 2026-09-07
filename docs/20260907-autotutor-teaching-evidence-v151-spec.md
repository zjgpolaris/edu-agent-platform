# v1.51 AutoTutor 教学质量实证与可复现展示 Spec

日期：2026-09-07
状态：开发完成；本地验收与已知边界见 [v1.51 交付记录](20260907-autotutor-teaching-evidence-v151-delivery.md)。远端 CI 尚未执行。
分析基线：`4a72173a16419847cf44c959680353f17b7fbe5c`，分析及专项验证开始时工作区 clean。
定位：个人 AI Agent / 全栈作品集，复用免费、离线、本地 Graph 主线。

## 1. 下一轮决策

下一轮交付“可验证的教学纠错案例 + 同一版本的可复现验收包”。优先解决现有质量评测名称与实际断言不匹配的问题，再把已有 Graph、内容门禁、恢复和教师证据串成观看者能核对的演示材料。

v1.50 已完成真实 Graph、来源标注、请求恢复和隔离启动，不应再次立项实现这些能力。当前最有价值的增量是证明：答错后纠正了什么、重教是否针对该误区、独立退出票如何验证，以及这些结论分别由哪些测试支持。

本轮完成不依赖生产 Canary GO，也不以新增生产证明流程为目标。云端延迟跟踪保留为独立后续事项。

## 2. 项目实际与缺口

| 代码或记录 | 已有事实 | 本轮判断 |
|---|---|---|
| `scripts/dev_autotutor_graph_demo.py` | 独立 SQLite、离线网络阻断、manifest、目录复用 | 已实现，直接复用 |
| `backend/agents/autotutor_demo_execution.py` | 持久 execution 摘要，真实节点白名单，固定输入来源与生产证据隔离 | 已实现，不新增执行器 |
| `eval/autotutor_demo_graph_flow_smoke.py` | 真实 API/Graph/数据库、幂等、恢复、降级和原子性专项 | 纳入验收包，不复制测试逻辑 |
| `frontend/e2e/autotutor-graph-recovery.spec.ts` | 真实提交后丢响应，再同步进度；双击和登录 503 | 保留既有故障覆盖 |
| `eval/autotutor_teaching_quality_eval.py` | 四条教材案例和两条补充检查 | 是确定性内容检查，不是通用 LLM 教学质量评估 |
| 同文件 `evaluate_case()` | 始终向 `prepare_content()` 传 `{}`；只检查结果没有 forbidden_terms | `injection_source_filtered` 没有实际污染输入，不能证明注入过滤 |
| 同文件 `evaluate_reteach_change()` | 检查 misconception 与反馈文字，不运行重教转换 | `reteach_semantic_change` 不能单独证明重教内容变化 |
| `eval/datasets/autotutor_teaching_cases.json` | 含 easy/medium/hard，但上述调用未传 `target_difficulty` | 案例标签不能作为难度覆盖证据 |
| `backend/agents/autotutor_observations.py` | 已将 correction 加入重规划后的教学 explanation | 重教实现已有；应先测真实行为，再修复暴露的问题 |
| `eval/run_core_evals.py` | 已支持 source_revision、profile、跳过数、JSON、`--no-report` | 复用现有报告合同，避免另建评测平台 |
| `.github/workflows/ci.yml` | 已有 Legacy/Graph E2E、PostgreSQL pgvector 迁移检查 | 不重复增加同类 job；补充统一产物索引即可 |
| v1.50 交付记录 | 测试结果写 Markdown，部分日志位于临时目录 | 缺少统一、可携带的当前版本展示包 |

上述评测缺口是“断言覆盖不足”，并不直接证明运行时存在注入漏洞、重教失败或难度选择错误。

### 本次实际验证

在写入本 spec 前执行：

```bash
PYTHONPATH=backend .venv/bin/python eval/run_core_evals.py \
  --suite autotutor_teaching_quality_eval \
  --suite autotutor_demo_graph_flow_smoke \
  --no-report --json
```

两套 suite 均通过；runner 汇总为 6/6 个 case，Graph flow 的内部断言不单独计为这些 case。报告记录的 commit 为上述基线、dirty=false。临时结果位于 `/tmp/edu-agent-next-spec-check.json`，不作为永久交付物。

本次没有重跑全套 CI、浏览器或 PostgreSQL，也没有核查最新远端 CI/生产配置。v1.50 历史验收数字见原交付记录，不能冒充本次执行结果。

## 3. 目标与范围

### P0：教学质量断言与真实转换对应

1. 注入测试真正构造污染的 retrieval_data，并证明它经过被测边界。
2. 重教测试运行一次真实 Graph 答错转换，比对前后教学内容、误区与题目变化。
3. 难度案例显式传入选择参数，核对实际题目难度或已声明的降级原因。
4. 独立退出票验证题目独立性、正确/错误的掌握结论与教师证据一致性。

### P1：同版本验收与展示材料

复用现有 runner、Playwright 和 CI，产出一个带来源、测试结果、跳过项和材料索引的目录。阅读者不启动云端服务，也能理解“目标 → 答错 → 纠正 → 再检验”的完整案例。

### 范围外

- 不新增 Agent、学科、游戏、学校管理或全面框架迁移。
- 不默认接入真实模型，不把 curated/fixture 结果称为模型泛化能力。
- 不新增数据库、checkpointer、公开导出 API 或全站评测看板。
- 不迁移云资源、不切换连接、不扩 Canary、不调整性能门禁。
- 不建设新的签名、attestation 或生产 evidence pipeline。

## 4. 教学质量合同

### 4.1 数据集与断言

扩展现有数据集，保留稳定 case_id；为每个案例补充 scenario、objective_aspect、input、expected 和 assertion_scope。用独立的人工整理期望事实与误区标签作 oracle，不能从被测输出反向生成期望值。

最少覆盖以下 8 类场景；每类至少一个独立 case，可复用现有有效案例：

| 场景 | 输入与关键断言 |
|---|---|
| 正常可信内容 | 来源关联有效、关键事实和目标一致、无占位题 |
| 明确难度 | target_difficulty 实际传入；选择结果符合合同；无可选项时明确降级或阻断 |
| 污染来源 | retrieval_data 中包含可识别指令和唯一哨兵；证明参数进入实际边界；输出不执行或泄漏指令 |
| 无可信内容 | 不支持目标且无可用审核内容；明确 blocked，无虚构题目和掌握证据 |
| 因果/影响混淆 | 按误区选错项，经真实答题路径产生对应 correction、reflect/re_plan/reteach |
| 连续答错 | 保持原学习目标；策略或难度调整符合已有合同；不能仅换一个事件标签 |
| 退出票答对 | 练习后仍待独立验证；独立题通过后才产生对应 verified 结果 |
| 退出票答错 | 不误标 verified；薄弱点/复习和教师证据保留未掌握语义 |

污染用例须说明实际验证的是哪一层：当前 curated 内容隔离、来源过滤，或模型抗注入。若实现直接忽略不可信检索文本，应报告“污染输入未影响审核内容”，不能称为“LLM 抗注入通过”。其他已有安全测试仍保留。

### 4.2 重教真实路径

复用现有隔离 demo 环境与 `GraphActiveTransitionExecutor`，通过现有 start/answer 入口完成转换：

1. 保存答错前的安全教学内容、目标、题目标识和 revision。
2. 按指定 misconception_code 选择错项，避免以“第一个选项”代表固定误区。
3. 核对新 revision、实际 selected executor 与 Graph 节点，以及 reflection/re-plan 结果。
4. 检查新 explanation 包含与该误区对应的有效纠正，来源事实仍成立；仅字符串不相等不算通过。
5. 如果既有规则保留原解释并前置 correction，只要纠正准确即可通过，不强制随机改写整段文字。
6. 比对响应与持久恢复状态；确认学习事件/复习等副作用没有重复。

错误反馈、Graph 节点与最终教学内容分别断言；不能用某一个替代另两个。测试可以读取隔离 fixture 的答案键构造输入，但公开展示材料不得包含未作答题目的答案键或原始数据库快照。

### 4.3 退出票与失败定位

沿用现有独立检验语义，同时检查 assessment_id 和内容独立性，避免只换 id。退出票失败场景不要求教学成功，但要求正确记录失败与后续安排。

每个失败 case 至少输出 case_id、失败边界、期望与安全实际值。边界使用有限分类：content_gate、assessment_selection、misconception_feedback、reteach、exit_ticket、evidence_consistency、test_harness。

这些结果衡量规则合同和确定性案例覆盖，不宣称学生长期学习效果、统计显著提升或线上模型质量。

## 5. 可复现验收包合同

已新增薄编排脚本 `scripts/build_autotutor_demo_review.py`。复用 `run_core_evals.py --json --no-report` 和 Playwright 的机器可读 reporter，不解析自然语言日志来猜通过数。

产物仅写显式指定的新目录，至少包括：

```text
review-run/
  manifest.json
  summary.md
  eval-summary.json
  browser-summary.json
  cases/teaching-example.md
  artifacts/                 # 可选的成功演示截图
```

manifest 最少记录 schema_version、run_id、UTC 起止、完整 commit、dirty、Python/Node 版本、input_mode、production_evidence=false、验证范围、各步骤状态和产物相对路径。复用 runner 的既有来源字段，不能自填与实际执行不符的 revision。

状态分为 pass/fail/skipped/not_run；汇总分别显示 suite 和 case 数量。必需项未执行、跳过、报告缺失、子进程非零、超时或格式不合法均不能给完整 PASS。仅后端检查应显示 partial。可选视频缺失不阻塞。

流程要求：

- 先做本地依赖预检，显式定位 Python；不自动安装全局软件。
- 使用独立临时数据库与端口，遵循已有 runner 的外部数据库拒绝规则。
- 每步有超时、取消和进程清理；中途失败也输出可读摘要。
- 不覆盖 `eval/reports/latest.*`、历史 canary 报告或用户已有输出目录。
- 运行前后核对 revision/dirty；运行中源码发生变化则标记来源不稳定，不发布为同版本验收包。
- 未测量的网络调用数为 unknown；若引用 Graph flow 的计数，明确它只覆盖该测试进程，不能宣称整个 CI 零网络。
- 浏览器 trace/日志可能含鉴权信息，作为内部诊断产物；对外包只允许脱敏摘要与审阅过的合成账号截图，不整包复制 trace、storage、SQLite 或 JWT 文件。
- CI 直接复用已有任务产物；聚合依赖失败时仍记录失败，不混用其他 commit 或上次成功结果。

演示材料用一份成功案例说明目标、错项误区、重教纠正、独立检验与教师结论，附一份失败/降级案例。材料中的节点、来源与结果从本轮实际输出取得，不手绘一条不存在的成功轨迹。

## 6. 任务拆分与依赖

| 任务 | 优先级 | 修改位置 | 验收产物 |
|---|---|---|---|
| T1 修正质量评测输入与命名 | P0 | `eval/autotutor_teaching_quality_eval.py`、现有 dataset | 真正污染输入、显式难度、准确 scope；旧有效用例保留 |
| T2 补真实重教/退出票对照 | P0 | 复用 Graph flow；必要时增加专项并注册 runner | 8 类覆盖映射、目标纠正和跨端证据断言 |
| T3 修复测试暴露的实现问题 | P0，有失败才改 | `autotutor_content.py`、`autotutor_observations.py` 等实际责任边界 | 最小修复、对应回归；不预设重写 |
| T4 薄编排与机器可读结果 | P1 | 新增 review 脚本、现有 runner/Playwright 配置 | 独立输出目录、准确 partial/fail、来源和脱敏检查 |
| T5 演示材料与 CI 索引 | P1 | `.github/workflows/ci.yml`、README、交付文档 | 当前 commit 的产物入口、五分钟讲解、明确限制 |

依赖：T1 → T2 → 必要的 T3 → T4 → T5。可以先交付 P0 作为 v1.51 首个 PR，后续 PR 完成展示包；全部验收前状态保持进行中。预计 3–5 个开发日，仅作排期参考；真实失败修复和远端 CI 等待可能增加时间。

## 7. 验收与退出标准

1. 8 类教学场景覆盖齐全，P0 必需 case 无失败/跳过；报告能逐项定位断言。
2. 人为删除纠正、伪造验证通过或绕过污染输入准备后，对应测试确实失败；用少量定向负控验证测试有效性，不引入全项目 mutation 平台。
3. 既有 Graph policy/flow/projection、trajectory、content validity、授权、恢复与事务相关专项保持通过；实现修改涉及哪个边界，就执行其对应回归。
4. 默认 Legacy E2E 与 Graph E2E 都通过。前端配置/代码改动时执行 lint、unit、build；不以 Graph 替代 Legacy 验收。
5. 修改持久化路径时，必须通过现有 PostgreSQL pgvector CI 的迁移/schema/原子性检查；SQLite 通过不能替代它。
6. review 脚本验证成功、子进程失败、缺依赖、超时、缺报告、来源变更、重复输出目录等情况；失败不会生成 PASS。
7. 在两个新隔离目录连续运行，案例判断一致；run_id/时间/session id 可以不同，不要求产物字节相同。
8. 最终交付记录绑定实现后的完整 commit 和实际 dirty 状态，列出通过、失败、跳过、未执行及远端 CI 状态。未执行线上验证须明确写出。

## 8. 云端延迟后续与回退

仓库的[延迟诊断记录](20260907-autotutor-latency-hotpath-fix.md)记录了跨地区数据库路径、历史性能停止与剩余核验事项。这些是历史观测，本次未在线复核。它们支持“另立部署优化任务”，不支持宣称目前线上已恢复或迁移必然解决所有延迟。

如后续目标改为提升公开站点体验，单独评估部署位置、成本与数据库往返，获得具体资源路线后再形成迁移 spec；本轮不依赖该决策。

本轮回退以撤销新增编排入口和展示材料为主。保留 v1.50 本地启动、现有生产默认和已有报告合同。若修复教学实现，保持 state_json 向后兼容、唯一领域事务与原有掌握判定，不以删测试回退质量要求。

## 9. 参考基线

- [v1.50 Spec](20260907-autotutor-langgraph-demo-closure-v150-spec.md)
- [v1.50 交付与历史验收](20260907-autotutor-langgraph-demo-v150-delivery.md)
- [项目方向确认](20260709-ai-agent-engineering-direction-confirmation.md)，仅引用作品集定位，不沿用旧技术版本或覆盖率估计。

最初分析仅新增此 spec 并执行两项基线检查；随后按用户要求完成测试、编排、CI 与文档开发。没有修改业务教学/事务逻辑，没有提交、push、发布或变更云端配置。
