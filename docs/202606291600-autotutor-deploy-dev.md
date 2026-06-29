# AutoTutor 上线部署（Vercel 前端 + Render 后端）

**创建日期：** 2026-06-29
**对应迭代：** [`202606291030-autotutor-autonomous-loop-dev.md`](202606291030-autotutor-autonomous-loop-dev.md) 第五节 W2.5
**目标：** 把 AutoTutor 自主辅导 agent 部署成一个「简历上可点的活链接」。

---

## 一、架构

```
浏览器 ──> Vercel(前端 Next.js) ──fetch──> Render(后端 FastAPI/Docker) ──> Supabase(Postgres)
                                                          └──> LLM(Anthropic 兼容)
```

- **前端**：Vercel，Next.js 原生支持，免费档够用。
- **后端**：Render，跑 `backend/Dockerfile`（已就绪），免费档够 demo。
- **数据库**：复用现有 Supabase Postgres（`DATABASE_URL`）。
- **RAG 取材**：云端无本地 BGE 模型 → 自动走 `auto_tutor` 的 **degraded 降级**（用模型自有知识出题），闭环仍完整可演示。

---

## 二、仓库内已就绪的配置

| 文件 | 作用 |
|------|------|
| `render.yaml` | Render Blueprint：后端 web service + env 清单 |
| `backend/Dockerfile` | 后端镜像（uvicorn） |
| `frontend/vercel.json` | Vercel 框架/构建声明 |
| `frontend/Dockerfile` | 前端多阶段 standalone 镜像（自托管备用） |
| `frontend/next.config.js` | `output:"standalone"` + 路由 redirects |
| `.dockerignore` / `frontend/.dockerignore` | 瘦身构建上下文 |
| `backend/api/main.py` CORS | `*.vercel.app` 正则放行 + `FRONTEND_ORIGIN` 可配自定义域名 |

---

## 三、后端上线（Render）

1. Render Dashboard → **New → Blueprint** → 连接本仓库，自动读取 `render.yaml`。
2. 在服务的 **Environment** 填以下 secret（`render.yaml` 里标了 `sync: false` 的项）：
   - `DATABASE_URL` —— Supabase 连接串
   - `BAILIAN_API_KEY` —— 百炼 API key
   - `BAILIAN_BASE_URL` —— 百炼公网地址（如 `https://dashscope.aliyuncs.com/compatible-mode/v1`）
   - `LLM_MODEL_FAST` / `LLM_MODEL_QUALITY` / `LLM_MODEL_FALLBACK` —— 与本地 `.env.local` 一致
   - `LLM_PROVIDER` 已在 `render.yaml` 设为 `bailian`
   > 注：本地 LLM 网关是 qima-inc 内网，Render 公网访问不到；线上必须用百炼/阿里云**公网**地址。
3. 部署完成后记下后端公网 URL，例如 `https://edu-agent-backend.onrender.com`。
4. 健康检查：访问 `https://<后端>/api/debug/llm/health`，确认 LLM 连通。

> 免费档冷启动有几十秒延迟，演示前先打开一次预热。

---

## 四、前端上线（Vercel）

1. Vercel → **New Project** → 导入本仓库。
2. **Root Directory 必须设为 `frontend`**（否则 Vercel 找不到 Next.js）。
3. 环境变量：
   - `NEXT_PUBLIC_API_BASE_URL` = 上一步的 Render 后端 URL（**不带结尾斜杠**）
4. Deploy。Vercel 给出 `https://<项目>.vercel.app`。
5. 若用了**自定义域名**，回到 Render 把该域名填进 `FRONTEND_ORIGIN`（逗号分隔可多个），重启后端使 CORS 放行。

---

## 五、灌 demo 种子数据

后端环境（本地或一次性容器内）执行，向 Supabase 写入 demo 学生 + 预置错题本：

```bash
PYTHONPATH=backend python3 scripts/seed_demo_student.py
```

- 账号：**demo-student / demo123**，年级八年级上册。
- 预置错题本：鸦片战争 ×3、洋务运动 ×2、戊戌变法 ×2、辛亥革命 ×1 —— AutoTutor 一进去就有薄弱点可规划。

---

## 六、30 秒演示脚本

1. 打开 `https://<前端>/student/auto-tutor`，用 **demo-student / demo123** 登录。
2. 点「开始本节课」→ agent 现场读画像+错题本规划本节课（左栏出现计划，右栏 trace 出现 `plan` step）。
3. 当前题**故意答错** → 右栏出现 `reflect` + `re_plan` step（带诊断结论），中栏弹「agent 反思并调整了计划」，难度被降级、题目变化。
4. 点右栏某条 trace / 底部 TraceTimeline，看 `Act·取材` 的工具调用与状态（线上为琥珀「降级」）。
5. 答对推进至课程结束 → 打开 `/student/memory` 看本节课写入的 `review_goal` 记忆；`/student/review` 看排入的复习。
6. 打开 `/eval` 看该 agent 的 trajectory 通过率。

> 一句话：「会自己规划、答错会反思重规划、全程可观测可评测、课后写记忆排复习的自主辅导 agent。」

---

## 七、上线检查清单

- [ ] Render 后端 `/api/debug/llm/health` 返回正常
- [ ] Vercel `NEXT_PUBLIC_API_BASE_URL` 指向后端、无结尾斜杠
- [ ] 浏览器 Network 无 CORS 报错（看前端域名是否被后端放行）
- [ ] `scripts/seed_demo_student.py` 已对线上 DB 跑过一次
- [ ] `/student/auto-tutor` 能完整跑完一节课（规划→答错→反思→结束）
- [ ] `eval/auto_tutor_trajectory_eval.py` 在 CI 通过

---

## 八、已知降级与取舍（demo 范围内可接受）

| 项 | 现状 | 影响 |
|----|------|------|
| RAG 取材 | 云端无 BGE 模型，走 degraded | 取材状态显示琥珀「降级」，用模型知识出题，闭环不断 |
| 会话存储 | 进程内存兜底（TTL 1h），未接云 Redis | 后端重启/多实例会丢进行中的会话；单实例 demo 无感 |
| Render 免费档 | 闲置休眠 | 首次访问冷启动慢，演示前预热即可 |
