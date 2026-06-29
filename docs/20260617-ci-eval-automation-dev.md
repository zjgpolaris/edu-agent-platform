# CI/CD + 自动 Eval 开发说明

## 背景

本阶段将 EduAgent 已有的本地验证、Eval Dashboard、Trace-to-Eval 回归样本能力固化为自动化 CI 流程。目标是在 PR / push 时自动验证核心工程质量，并产出可下载的 eval report artifact。

## CI 覆盖范围

GitHub Actions workflow: `.github/workflows/ci.yml`

默认触发：

- `pull_request`
- push 到 `main` / `master`

Jobs：

1. `frontend`
   - `npm ci --prefix frontend`
   - `npm run lint --prefix frontend`
   - `npm run build --prefix frontend`
2. `backend-verify`
   - 安装 `backend/requirements.txt`
   - `PYTHONPATH=backend python3 scripts/verify_core.py --smoke`
3. `quick-eval`
   - 安装 `backend/requirements.txt`
   - `PYTHONPATH=backend python3 eval/run_core_evals.py --quick --json`
   - 上传 `eval/reports/latest.json` 和 `eval/reports/latest.md`
4. `docker-build`
   - `docker build -f backend/Dockerfile -t eduagent-backend:ci .`
   - `docker build -f frontend/Dockerfile -t eduagent-frontend:ci frontend`

## 本地复现命令

核心 smoke：

```bash
npm run verify:core
# 或
make verify-core
```

本地完整核心检查（quick eval + frontend lint/build）：

```bash
npm run verify:core:full
# 或
make verify-core-full
```

只跑 quick eval：

```bash
PYTHONPATH=backend python3 eval/run_core_evals.py --quick --json
# 或
make eval-quick
```

前端：

```bash
npm run lint --prefix frontend
npm run build --prefix frontend
```

Docker：

```bash
docker build -f backend/Dockerfile -t eduagent-backend:ci .
docker build -f frontend/Dockerfile -t eduagent-frontend:ci frontend
```

## Eval artifacts

`eval/run_core_evals.py` 默认写入：

- `eval/reports/latest.json`
- `eval/reports/latest.md`

CI 的 `quick-eval` job 会将两者上传为 `quick-eval-report` artifact，保留 14 天。

## Secret-free 策略

默认 CI 不要求配置 LLM API secrets。

- `history_character_smoke.py` 在缺少 `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY` 时会输出 `SKIP ...` 并成功退出。
- `ragas_eval.py` 不在默认 CI 中运行；它依赖 LLM-as-judge，会消耗真实 token，适合后续做 manual / scheduled workflow。
- `rag_retrieval_eval.py` 在缺少可用 `EMBED_MODEL_PATH` 时会输出 `SKIP ...`，避免 CI 依赖开发者本机模型路径。

## Embedding model 策略

本地开发仍可使用：

```bash
export EMBED_MODEL_PATH=/path/to/BAAI/bge-large-zh-v1.5
```

`eval/run_core_evals.py` 和相关 smoke 脚本只会在默认本机模型路径实际存在时自动设置 `EMBED_MODEL_PATH`；CI 不再隐含 `/Users/cengjiguang/...` 这类开发者本机路径。

## 注意事项

- CI 默认不跑 Ragas。
- CI 默认不做部署发布，只做 verification。
- Trace-to-Eval 保存进 `eval/datasets/*.json` 的回归样本会自然进入对应 smoke / quick eval 流程。
- 如果未来希望 CI 跑完整 core suites，应为 LLM credentials、embedding model 和向量库数据提供稳定的 CI provisioning。