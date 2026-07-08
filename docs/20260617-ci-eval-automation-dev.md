# CI/CD + 自动 Eval 开发说明

## 背景

本阶段将 EduAgent 已有的本地验证、Eval Dashboard、Trace-to-Eval 回归样本能力固化为自动化 CI 流程。当前主目标是把发布前统一闸门 `scripts/release_gate.py` 接入 GitHub Actions，让 PR / push 默认验证核心工程质量，并继续产出可下载的 eval report artifact。

## CI 覆盖范围

GitHub Actions workflow: `.github/workflows/ci.yml`

默认触发：

- `pull_request`
- push 到 `main` / `master`

手动触发：

- `workflow_dispatch`，可选填写已部署后端 `ready_url`，用于发布后 production readiness 验收。

Jobs：

1. `frontend-lint`
   - `npm ci --prefix frontend`
   - `npm run lint --prefix frontend`
   - 只做快速前端静态检查；前端 build 由 `release-gate` 统一执行。
2. `release-gate`
   - 安装 `backend/requirements.txt`
   - 安装 `frontend/package-lock.json` 对应依赖
   - `npm run release:gate`
   - 作为默认 PR / push 的主发布门禁，覆盖 Python 语法检查、后端 smoke 与前端 build。
3. `quick-eval`
   - 安装 `backend/requirements.txt`
   - `PYTHONPATH=backend python3 eval/run_core_evals.py --quick --json`
   - 上传 `eval/reports/latest.json` 和 `eval/reports/latest.md`
   - 对 PR 发布 quick eval 摘要评论；它是补充观测信号，不是 production readiness gate。
4. `docker-build`
   - `docker build -f backend/Dockerfile -t eduagent-backend:ci .`
   - `docker build -f frontend/Dockerfile -t eduagent-frontend:ci frontend`
   - 仅在 push 到主分支或手动触发时运行，不占默认 PR 关键路径。
5. `production-readiness`
   - 仅在手动触发且填写 `ready_url` 时运行。
   - `npm run release:gate:prod -- --skip-frontend --ready-url <ready_url>`
   - 需要 GitHub Secrets 提供 `API_TOKEN` / `AUTH_TOKEN` 或 `SMOKE_USERNAME` / `SMOKE_PASSWORD` 等生产 smoke 认证信息。

## 本地复现命令

轻量后端 smoke：

```bash
make verify-core
# 或
PYTHONPATH=backend python3 scripts/verify_core.py --smoke
```

本地完整发布前检查（Python 语法检查 + 后端 smoke + 前端 build）：

```bash
npm run release:gate
# 或
make verify-core-full
# 或
make release-gate
```

本地快速关键路径发布闸门：

```bash
npm run release:gate:fast
# 或
make release-gate-fast
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

生产 readiness / RAG strict gate（不属于默认 PR CI）：

```bash
API_BASE=https://<后端> \
SMOKE_USERNAME=<user> \
SMOKE_PASSWORD=<password> \
npm run release:gate:prod -- --skip-frontend --ready-url https://<后端>/api/ready
```

## Eval artifacts

`eval/run_core_evals.py` 默认写入：

- `eval/reports/latest.json`
- `eval/reports/latest.md`

CI 的 `quick-eval` job 会将两者上传为 `quick-eval-report` artifact，保留 14 天。

## Secret-free 策略

默认 CI 不要求配置 LLM API secrets，也不依赖生产 API / RAG / embedding 服务。

- `release-gate` 默认执行本地 smoke 与前端 build，不调用 production RAG strict gate。
- `/api/ready` 的 smoke 只验证 shallow readiness 结构，不触发外部 LLM / Embedding。
- `history_character_smoke.py` 在缺少 `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY` 时会输出 `SKIP ...` 并成功退出。
- `ragas_eval.py` 不在默认 CI 中运行；它依赖 LLM-as-judge，会消耗真实 token，适合后续做 manual / scheduled workflow。
- `rag_retrieval_eval.py` 在缺少可用 `EMBED_MODEL_PATH` 时会输出 `SKIP ...`，避免 CI 依赖开发者本机模型路径。
- `production_rag_health_smoke.py` 只由 `npm run release:gate:prod`、`npm run test:prod-rag` 或手动 `production-readiness` job 显式运行，要求 `API_BASE` 与认证信息。

## Embedding model 策略

本地开发仍可使用：

```bash
export EMBED_MODEL_PATH=/path/to/BAAI/bge-large-zh-v1.5
```

`eval/run_core_evals.py` 和相关 smoke 脚本只会在默认本机模型路径实际存在时自动设置 `EMBED_MODEL_PATH`；CI 不再隐含 `/Users/cengjiguang/...` 这类开发者本机路径。

## 注意事项

- CI 默认不跑 Ragas。
- CI 默认不做部署发布，只做 verification；Render / Vercel 仍由平台配置负责实际部署。
- production readiness 是手动验收层，不进入默认 PR CI。
- Trace-to-Eval 保存进 `eval/datasets/*.json` 的回归样本会自然进入对应 smoke / quick eval 流程。
- 如果未来希望 CI 跑完整 core suites，应为 LLM credentials、embedding model 和向量库数据提供稳定的 CI provisioning。
