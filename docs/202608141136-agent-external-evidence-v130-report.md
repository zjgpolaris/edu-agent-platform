# EduAgent v1.30 真实外部证据尝试报告

**执行时间：** 2026-08-14 11:36–11:40 CST
**代码 revision：** `060c166dbc890c02f74423309f6779728c7d4be9`（dirty，包含尚未提交的 v1.30 工程改动）
**结论：** 已取得一项真实外部学生 OOD 安全证据；中文 in-domain blind、真实 LLM 和生产 canary 仍为 NOT_RUN，release seal 未通过。

## 1. 已取得的真实外部证据

| 项目 | 结果 |
| --- | --- |
| run_id | `eval_20260814T033641Z_be54af89c4b2` |
| 数据源 | [Eedi Question-Anchored-Tutoring-Dialogues-2k](https://huggingface.co/datasets/Eedi/Question-Anchored-Tutoring-Dialogues-2k) test split |
| 数据性质 | 真实学生与真人 tutor 的数学辅导对话；本次只读取 student message |
| 许可 | 页面元数据为 CC BY-NC 4.0，正文为 CC BY-NC-SA 4.0；本次按更严格的非商业、相同方式共享约束处理 |
| 原始测试文件 SHA-256 | `fcd2dd06ad87b1466a14e43f21c50edb5802cad8588cf60b75eb76b60c43d5a2` |
| 去重学生消息 | 3,453 |
| 安全 chat 路由 | 3,453 / 3,453 |
| 错误学习工具路由 | 0 |
| external OOD precision | 100%（门槛 95%） |

数据原文只下载到仓库外的 `/tmp`，未加入 Git；评测脚本不打印消息、用户 ID、干预 ID或本地路径。仓库仅保存来源、许可、数据哈希和聚合指标。

证据边界：该数据来自英文数学辅导场景，因此只证明当前规则路由对这一外部分布没有误触发历史、教材、出题、复习、游戏或高风险工具。它不能证明中文自然表达的 in-domain intent accuracy、macro-F1、slot accuracy，也不能证明语义路由模型质量。

## 2. 未取得的外部证据

| 证据链 | 状态 | 实测原因 |
| --- | --- | --- |
| 真实语义路由 LLM | NOT_RUN | 当前进程没有 Bailian/DashScope/Anthropic 凭证；当前 run 真实调用为 0 |
| 私有 blind >=200 | NOT_RUN | `EDU_AGENT_BLIND_EVAL_PATH` 未配置 |
| 外部 production RAG | NOT_RUN | `API_BASE` 未配置，health smoke 主动跳过 |
| 生产 canary | NOT_RUN | 没有部署版本、真实流量和 48 小时以上观察窗口 |
| 强制 release seal | FAIL | dirty revision、required suite incomplete、blind/real LLM 未证明、模型 provenance 缺失 |

缺少凭证或 blind 文件时，runner 现在统一输出 `SKIPPED`，报告中的 LLM 状态为 `not_run`，并以非零状态阻止误发布；不会再把基础设施缺失包装为质量 PASS。

## 3. 完整封印尝试

封印 run：`eval_20260814T033914Z_d206469de7af`

- CORE：35 / 35 suites、458 / 458 可执行 cases 通过；
- 外部必需套件：blind 与 semantic real-LLM 均 SKIPPED；
- release seal：FAIL；
- 原因：`working_tree_dirty`、`required_suite_incomplete`、`blind_profile_not_proven`、`real_llm_profile_not_proven`、`run_scoped_real_llm_not_observed`、`model_provenance_incomplete`。

## 4. 复现命令

```bash
EDU_AGENT_EXTERNAL_OOD_PATH=/secure/path/eedi-test.csv \
PYTHONPATH=backend python3 eval/run_core_evals.py \
  --suite learning_assistant_external_ood_eval \
  --profile production_canary

PYTHONPATH=backend python3 eval/run_core_evals.py \
  --profile real_llm \
  --require-real-llm \
  --require-clean-revision \
  --require-release-seal
```

## 5. 下一次可完成的证据

1. 配置可计费的 Bailian/DashScope 或 Anthropic 凭证，执行 6 条真实语义路由 smoke，并记录 provider、model、calls 和 p95。
2. 在仓库外提供至少 200 条双人复核中文 blind JSONL，执行 accuracy、macro-F1、high-risk recall 和 clarification 指标。
3. v1.30 改动提交后，在 clean revision 上重跑强制 release seal。
4. 部署 10% canary，累计至少 200 条有效样本和 48 小时观测，再评估是否扩大流量。
