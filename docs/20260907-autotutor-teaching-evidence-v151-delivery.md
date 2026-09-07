# v1.51 教学质量实证与可复现展示交付

日期：2026-09-07。范围：本地确定性 Agent 作品集验收，不是生产发布。

## 实现结果

- 教材案例实际传入 `target_difficulty`，污染案例将带哨兵的 retrieval_data 传到真实 evidence 边界；缺内容时验证阻断。原有史实、来源绑定、可读性与占位题检查保留。
- 保留 `xinhai_hard` 的稳定案例 ID，按实际题库合同验证 hard 无题时 `no_fresh_assessment_for_target_difficulty`；新增 medium 史实案例保留原事实覆盖。没有为通过测试修改审核题库。
- 将旧的“重教变化”反馈单测准确命名为 `misconception_feedback_specificity`。新增 `autotutor_teaching_graph_eval`，复用 v1.50 隔离 DB/ASGI fixture、真实 Graph 和现有领域事务。
- Graph 专项检验误区反馈、定向纠正前后内容、实际节点、连续答错、独立退出票、教师结论与复习目标。每次答题重放比较事件、薄弱点、证据、记忆与掌握记录，确认没有重复副作用。
- 增加三项负控：去掉纠正、把退出票失败伪造为 verified、绕过污染输入准备，均必须使对应 oracle 拒绝。
- 新增 `scripts/build_autotutor_demo_review.py`：默认后端 + Legacy + Graph；支持明确标注 partial 的后端模式、单浏览器模式和 CI 产物汇总。现有 runner/Playwright 负责执行与统计，没有新增评测平台。
- 验收目录包含 manifest、suite/case 计数、摘要和本轮实际生成的成功/失败教学案例。只输出允许展示的合成事实；不复制数据库、鉴权状态、原始 trace 或错误日志。
- 缺依赖、缺报告、格式错误、非零退出、超时、跳过、flaky、来源变化不会成为完整 PASS。进程组在结束/超时后清理；测试还确认超时后子进程不会继续写文件。
- CI 在现有 quick-eval/browser job 内生成分项材料，新增只做汇总的 `autotutor-review-index`。按 commit、源码内容指纹、workflow run/attempt 校验来源，并保留上游 job 失败状态。

没有发现需要修改业务教学或持久化逻辑的问题。此次实现改动集中于评测、验收编排、CI 和文档。

## 八类覆盖映射

| 场景 | 直接覆盖 |
|---|---|
| 可信内容 | `opium_war_easy`、`xinhai_reviewed_facts` 及原有事实检查 |
| 显式难度 | `westernization_medium`、`xinhai_hard` 等 |
| 污染来源 | `injection_source_filtered` + boundary bypass 负控 |
| 无可信内容 | `unsupported_objective_blocked` |
| 因果/影响混淆 | Graph `misconception_reteach_and_exit_correct` 前半段 |
| 连续答错 | Graph `repeated_wrong_targeted_reteach` |
| 退出票答对 | Graph `misconception_reteach_and_exit_correct` 后半段 |
| 退出票答错 | Graph `exit_wrong_teacher_review_consistency` |

`teaching_groundedness_rate` 仍是审核内容案例合同的通过率；不代表真实 LLM 的 groundedness 或泛化能力。污染测试证明当前审核内容隔离，不声称模型抗注入能力。

## 验证记录与来源

基线 commit：`4a72173a16419847cf44c959680353f17b7fbe5c`。验收时工作区 **dirty**，包括本轮实现；不是该 commit 单独通过了新增测试。环境为 macOS、Python 3.13.4、Node 24.14.0、SQLite 临时库与 Chromium。

| 检查 | 结果 |
|---|---|
| review 后端 | 8/8 suite 通过，25/25 个可计数 case；0 失败/跳过 |
| 内容专项 | 8/8 case |
| 新增 Graph 专项 | 4/4 case，包含三个教学场景组合与污染负控 |
| review 编排专项 | 4/4 case 组，含失败路径、进程清理、源码变化、生成文件边界 |
| 附加回归 | parity、active routing/transaction、observation provider、comparator、trace authorization、demo contract 通过 |
| Legacy 浏览器 | 13/13，0 失败/跳过/flaky |
| Graph 浏览器 | 5/5，0 失败/跳过/flaky |
| 前端 lint / unit / build | 通过；unit 为 14 文件、42 测试 |
| 实际产物汇总 | 完整包汇总为 PASS；注入上游 failure 后汇总为 FAIL |

首次完整 PASS 包位于 `/tmp/edu-agent-v151-review-5`，manifest 记录 source_stable=true；源码开始/结束内容指纹一致。实际汇总验证位于 `/tmp/edu-agent-v151-collection-pass` 与 `/tmp/edu-agent-v151-collection-failure`。这些是本机临时目录，可能被系统清理；可按下方命令重建。生成该包后补充了本交付记录与 spec 状态，业务实现没有变化；每个新包仍独立记录完整来源。

首次试跑因并行旧测试改写历史报告而判为来源变化；并行 parity 与 trajectory 还共用了旧固定临时 DB，parity 单独重跑通过。另一次浏览器试跑有两条 Legacy 页面等待超时，保留 FAIL，之后完整复跑通过。没有提高断言时限、改预期结果或把失败计入通过。

为保证重复运行，预声明 Graph 生成的 TypeScript include，ESLint 排除 Playwright 生成报告。Next 自动修改的 `next-env.d.ts` 只在内容完全等于本轮已知路径替换时恢复；并发用户修改会保留并触发来源变化，测试已覆盖。

本轮未重跑全量 core/全部生产演练，也没有在线模型、线上性能或新 PostgreSQL 验收。业务持久化路径未修改，既有 PostgreSQL CI 保留。远端 GitHub Actions 尚未执行，不能据本地通过声称 CI/生产 GO。

## 复现与展示

在未设置外部数据库变量的终端、已安装依赖与 Chromium 的仓库根目录：

```bash
.venv/bin/python scripts/build_autotutor_demo_review.py --output /tmp/edu-agent-review-new-run
```

输出目录必须尚不存在且位于仓库外。每次换一个新目录，等上一轮完整结束再运行下一轮，避免与手动演示或旧 trajectory 测试争用构建/测试资源。`--backend-only` 是 partial；默认完整模式才可能是 PASS。使用当前 Python，不自动安装依赖。

五分钟讲解：

1. 打开 `summary.md`，核对 commit、dirty、来源稳定性与验证范围。
2. 打开 `cases/teaching-example.md`，说明目标是解释失败原因，误区是把历史影响当原因。
3. 对照重教前后文本与真实 Graph 节点，指出实际纠正内容。
4. 查看独立退出票成功后的教师 verified 结论。
5. 对照失败案例的 not_yet_verified 与 weakpoint_recorded，说明系统如何保留未掌握证据。

需要现场交互时继续使用 v1.50 的 `scripts/dev_autotutor_graph_demo.py`。对外分享仅使用 review 输出目录；Playwright HTML/trace 作为本机或 CI 内部诊断材料。

本轮未提交、push、部署、修改生产开关或迁移云资源。
