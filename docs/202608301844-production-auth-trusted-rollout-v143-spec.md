# 生产认证边界与可信 Rollout Cohort v1.43 Spec

**日期：** 2026-08-30
**状态：** Development Complete / Operational Security `NOT_RUN` / Rollout `unknown`
**优先级：** P0
**目标环境：** production
**目标 Agent：** `history_character`
**前置文档：**

- `docs/202608280000-agent-runtime-langgraph-boundary-adr.md`
- `docs/202608281554-agent-runtime-rollout-evidence-v139-spec.md`
- `docs/202608281900-agent-runtime-production-evidence-v140-spec.md`
- `docs/202608291701-agent-runtime-production-shadow-v141-spec.md`
- `docs/202608292100-agent-runtime-rollout-operations-v142-spec.md`

## 0. 执行摘要

v1.42 已完成 Runtime rollout 状态机、配置预检、AgentOps 操作面和只读 Preflight 工作流，但生产环境尚未具备进入 Shadow 的可信前提。

2026-08-30 对部署 `b95ad0dbc09546369819d35159eb839d3951a24e` 的线上检查显示：

| 检查 | 状态 |
| --- | --- |
| 应用与数据库 | 可用，PostgreSQL 正常 |
| Runtime schema | Alembic `011`，ready |
| Runtime config | `v1.41-history-control` |
| Runtime enabled | `false` |
| control observations | `0 / 100` |
| shadow terminal runs | `0 / 100` |
| rollout evidence | disabled / missing |
| rollout next action | `continue_collecting_control` |
| rollout observation writes | 近 15 分钟 0 failure |
| 匿名访问管理员 rollout-status | HTTP 200 |

匿名管理员访问的根因不是 rollout API 单点漏写依赖，而是生产没有启用 `EDU_AGENT_AUTH_REQUIRED=true`。当前 `auth_required()` 默认返回 false，`require_auth()` 因而退化为内置 `dev-teacher`；多个以 `if auth_required() and role != ...` 实现的角色检查也随之被跳过。

此外，当前公开 Pilot 账号、自助注册账号和真实试点账号没有服务端可信流量分类。即使后续积累到 100 个 control observations，也无法证明样本来自受控生产 cohort，公开演示流量可能污染 baseline。

v1.43 的目标是先建立生产认证与可信样本边界：生产认证 fail-closed、角色由数据库实时授权、管理员有安全初始化路径、Pilot/demo/unverified 流量不能贡献 rollout evidence、只有 verified cohort 才能进入 Shadow。完成后继续执行 v1.42 的 Control → Shadow 运营流程；本轮不进入 Active。

## 1. 问题定义

### 1.1 生产认证默认关闭

当前认证开关：

```python
os.getenv("EDU_AGENT_AUTH_REQUIRED", "false")
```

`render.yaml` 声明了 `JWT_SECRET`，但未声明 `EDU_AGENT_AUTH_REQUIRED=true`。这会产生以下行为：

- 匿名请求被视为 `dev-teacher`；
- 依赖 `require_auth` 的路由在生产仍可匿名调用；
- 管理员路由的条件式角色检查被绕过；
- 学生、教师、管理员数据边界不能作为生产安全保证；
- rollout preflight 的管理员 Token 合同没有实际被验证。

生产配置错误不能以“开发模式兼容”为理由继续运行。

### 1.2 JWT 声明不是可撤销的授权来源

当前 JWT 同时携带 actor ID 与 role，默认有效期 72 小时。接口只解码 Token，不回查账户。账号被禁用或角色被调整后，旧 Token 在过期前仍保留旧权限。

生产授权必须满足：

- JWT 证明会话由服务端签发；
- 账户是否存在、是否启用、当前角色与 cohort 由数据库决定；
- 管理员 Token 使用更短有效期；
- 禁用账户后，后续请求立即或在明确的短缓存窗口内失效。

### 1.3 Pilot 与公开注册流量会污染生产证据

当前 observation 使用进程环境的 `EDU_AGENT_DATA_SCOPE`，没有结合账户来源。公开的 Pilot 账号和自助注册账号可能被记录为 `runtime` scope。

Rollout baseline 必须回答：

- 请求是否来自经过审批的生产试点成员；
- 样本是否为 demo、eval、未验证或历史遗留流量；
- Shadow wrapper 是否只对可信 cohort 生效；
- 被排除样本有多少、为什么被排除。

任何由客户端 Header、Query 或 Body 自报的 cohort 都不可信。

### 1.4 管理员没有安全 bootstrap 闭环

自助注册只能创建 student；Pilot seed 只创建公开教师/学生账号。Preflight 工作流要求管理员权限，却依赖人工维护的长效 `API_TOKEN`，缺少可复现的管理员初始化和短期 Token 获取流程。

## 2. 目标

### 2.1 产品与安全目标

1. production 未显式开启认证时拒绝启动；
2. production 的 JWT Secret 缺失、默认或弱强度时拒绝启动；
3. 匿名访问受保护接口返回 401，角色不匹配返回 403；
4. 账户状态、角色和 traffic cohort 以数据库为授权事实源；
5. 管理员可通过一次性、无明文落盘的流程初始化；
6. Pilot、自助注册、eval 和 legacy observations 默认不计入 rollout；
7. 只有 `verified` cohort 可进入 Runtime Shadow 并贡献 gate/evidence；
8. AgentOps 能显示 eligible/excluded 聚合计数和排除原因；
9. 不泄露 actor ID、用户名、Token、密码或 cohort 成员名单；
10. 保持现有学生和教师登录体验可用。

### 2.2 工程目标

1. 用统一依赖替代分散的条件式角色判断；
2. 新增 Alembic `012`，升级/重复执行/失败边界可验证；
3. observation、baseline、gate、status 和 evidence 使用同一 eligibility 口径；
4. CI 对 production auth 配置做 fail-closed contract 验证；
5. GitHub Runtime Preflight 每次运行换取短期管理员 Token；
6. 所有负向认证测试不依赖真实外部服务。

## 3. 非目标

本轮不包含：

- Runtime Active Canary；
- 降低 control/shadow 的 100 样本门槛；
- 将 demo、eval 或自动化流量改名为 production 数据；
- 将 Runtime 扩展到 AutoTutor、Learning Assistant、Essay Grader 或 Debate；
- OAuth、SSO、组织/学校多租户系统；
- 完整管理员后台或用户生命周期 UI；
- 第二套认证框架或第二套 Agent Runtime；
- 用前端隐藏代替后端鉴权。

## 4. 不变量

### 4.1 认证不变量

- production 必须认证，不存在隐式开发降级；
- liveness 可公开，readiness 只公开脱敏配置状态；
- 密码只存 bcrypt hash；
- JWT Secret、密码和 Token 永不进入日志、artifact 或 API 错误；
- 角色变化后不能继续依赖旧 JWT role；
- 管理员 API 必须在路由依赖层拒绝匿名和非管理员。

### 4.2 Rollout 不变量

- eligibility 只能由服务端账户记录和请求上下文推导；
- existing observations 在 migration 后默认 `legacy_untrusted`，不得追认；
- `terminal_samples` 继续表示 eligible samples，避免 UI 将总流量误当成 baseline；
- excluded samples 只按 reason 聚合，不返回成员身份；
- production Shadow 只对 `verified` cohort 计算 rollout bucket；
- cohort 被撤销后，新请求立即停止进入 Shadow；
- control、shadow、active 数据仍按 agent/config/commit/environment/mode/scope 隔离。

## 5. 生产认证部署合同

### 5.1 新增配置校验

在 `backend/deployment.py` 增加：

```python
def auth_configuration_status() -> dict:
    ...

def auth_configuration_errors() -> list[str]:
    ...
```

production 必须满足：

- `EDU_AGENT_AUTH_REQUIRED=true`；
- `JWT_SECRET` 已配置；
- Secret 长度至少 32 bytes；
- Secret 不等于 `change-me-in-production` 或测试默认值；
- Secret 不能只由重复/低熵占位字符构成。

错误 code：

- `production_auth_not_enabled`
- `jwt_secret_missing`
- `jwt_secret_too_short`
- `jwt_secret_insecure_default`

响应只输出 code 和布尔状态，不输出 Secret 长度以外的可推断信息。

### 5.2 启动 fail-closed

`backend/start_backend.py` 在 migration 和 `uvicorn` 之前执行 auth preflight：

```json
{
  "status": "fail",
  "failure_stage": "auth_preflight",
  "reasons": ["production_auth_not_enabled"]
}
```

任一错误时非零退出。local/test 仍可显式使用无认证模式，但必须输出一次开发警告。

### 5.3 Readiness 合同

`GET /api/ready` 增加脱敏检查：

```json
{
  "auth_configuration": {
    "ok": true,
    "required": true,
    "jwt_secret_configured": true,
    "jwt_secret_strong": true
  }
}
```

production 将 `auth_configuration` 加入 `required_checks`。不得返回 Secret、hash、前后缀或环境变量原值。

### 5.4 Render 配置

`render.yaml` 增加：

```yaml
- key: EDU_AGENT_AUTH_REQUIRED
  value: "true"
```

`JWT_SECRET` 继续 `sync: false`，必须在 Render Dashboard 使用随机 Secret。Blueprint 同步前先确认 Secret 已存在，避免新实例因 auth preflight 拒绝启动。

## 6. 统一认证与 RBAC

### 6.1 Actor 合同

扩展服务端 Actor：

```python
class Actor(BaseModel):
    actor_id: str | None
    role: Literal["anonymous", "student", "teacher", "admin"]
    account_status: Literal["anonymous", "active", "disabled"]
    traffic_cohort: Literal["anonymous", "demo", "unverified", "verified", "operator"]
```

客户端不能直接构造这些字段。

### 6.2 数据库回查

`require_auth` 流程：

1. 读取 Bearer Token；
2. 验证签名、有效期和算法；
3. 使用 `sub` 查询 accounts；
4. 账户不存在或 disabled 返回 401；
5. 使用数据库中的 role/cohort 构建 Actor；
6. JWT 中的 role/cohort 仅作诊断声明，不作最终授权依据。

默认不缓存授权记录；若性能数据证明需要缓存，TTL 不得超过 60 秒并记录撤销延迟。

### 6.3 统一依赖

新增：

```python
require_authenticated_actor()
require_teacher()
require_admin()
```

语义：

| 请求 | 结果 |
| --- | --- |
| 无 Token / Token 无效 / 账户失效 | 401 |
| 已认证但角色不足 | 403 |
| teacher 访问 teacher/admin 允许路由 | 200 |
| admin 访问 admin 路由 | 200 |

所有 `/api/admin/*` 路由改为 `Depends(require_admin)`，不再在路由体内使用 `if auth_required()` 条件判断。教师专属写操作使用 `require_teacher`。

### 6.4 Token 生命周期

- student/teacher Token 默认保持 72 小时，避免破坏 Pilot 体验；
- admin Token 最长 1 小时；
- Token payload 增加 `iat`、`jti`；
- API 不在错误、trace metadata 或 audit metadata 中记录 Token；
- 本轮不实现 refresh token。

## 7. Alembic 012：账户与 Observation 信任字段

### 7.1 accounts

新增：

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `account_status` | text | `active` | `active/disabled` |
| `traffic_cohort` | text | `unverified` | `demo/unverified/verified/operator` |
| `updated_at` | text | migration time | 授权事实更新时间 |

迁移策略：

- 所有既有账户默认为 `unverified`；
- 不根据账号名称自动推断 verified；
- `seed_pilot_demo.py` 显式把 Pilot 账号设为 `demo`；
- 管理员 bootstrap 创建 `operator`；
- 自助注册创建 `unverified` student；
- 不自动创建 verified 账号。

### 7.2 agent_rollout_observations

新增：

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `traffic_cohort` | text | `legacy_untrusted` | 采样时的服务端 cohort 快照 |
| `rollout_eligible` | boolean | false | 是否可用于 baseline/gate/evidence |
| `eligibility_reason` | text | `legacy_untrusted` | 排除或纳入原因 code |

所有历史 observations 保持 `rollout_eligible=false`，不得回填为可信样本。

允许的 reason：

- `verified_runtime_actor`
- `demo_actor`
- `unverified_actor`
- `operator_actor`
- `eval_scope`
- `demo_scope`
- `anonymous_actor`
- `legacy_untrusted`

表中不新增 username、actor ID、student ID 或原始 Token。

### 7.3 迁移要求

- SQLite smoke 验证 upgrade 与重复执行；
- PostgreSQL CI 验证 revision `011 -> 012`；
- `backend/start_backend.py` 的 `REQUIRED_REVISION` 更新为 `012`；
- Runtime schema readiness 更新 required columns；
- downgrade 只删除本次新增字段，不删除账户或 observations；
- migration failure 必须阻止服务启动。

## 8. 可信流量与 Runtime 决策

### 8.1 服务端 eligibility

新增纯函数：

```python
def rollout_eligibility(actor: Actor, data_scope: str) -> tuple[bool, str]:
    ...
```

production 只有以下组合返回 true：

```text
actor.account_status == active
actor.traffic_cohort == verified
data_scope == runtime
```

local/test 可通过 fixture 构造 verified Actor，但不能用环境变量将 production 全局改为 eligible。

### 8.2 Shadow 选择

`RuntimeV2Settings.rollout_decision` 增加 eligibility 输入。顺序固定为：

1. kill switch；
2. Runtime enabled 与配置合法性；
3. actor rollout eligibility；
4. agent allowlist；
5. global/per-agent BPS；
6. stable subject bucket。

不符合 eligibility 时返回 inactive，业务仍走现有 control 执行源，不创建 Runtime run。

`10000 BPS` 的含义改为“覆盖 100% verified cohort”，不是覆盖所有公开访问者。

### 8.3 Observation 写入

`_record_history_rollout` 必须接收服务端 Actor 或已计算 eligibility，不得从请求 payload 读取 cohort。

写入规则：

| 请求 | runtime_mode | eligible |
| --- | --- | --- |
| verified，Runtime disabled | control | true |
| verified，Shadow selected | shadow | true |
| demo/unverified，Runtime disabled | control | false |
| demo/unverified，Shadow configured | control | false |
| eval/demo scope | 对应执行模式 | false |

失败、partial、completed 状态继续写入；是否计入 baseline 仍由既有 terminal status allowlist 决定。

## 9. Rollout 聚合与状态合同

### 9.1 Control progress

`control_observation_progress` 的 `terminal_samples` 只统计：

```text
agent_type/config_version/deployed_commit/environment/runtime_mode/control/data_scope
+ rollout_eligible=true
```

新增聚合字段：

```json
{
  "terminal_samples": 12,
  "minimum_samples": 100,
  "observed_total": 35,
  "excluded_samples": 23,
  "excluded_by_reason": {
    "demo_actor": 20,
    "unverified_actor": 3
  }
}
```

不得返回账号、trace ID 或逐条 observation。

### 9.2 Shadow gate

以下统计全部增加 `rollout_eligible=true` 过滤：

- terminal runs；
- provenance coverage；
- event coverage；
- terminal consistency；
- unexpected failure rate；
- p50/p95；
- evidence baseline/target sample count。

发现旧 evidence 不含 cohort eligibility hash 时返回：

```text
evidence_trust_contract_outdated
```

不得重用 v1.42 之前的 evidence 为 v1.43 盖章。

### 9.3 Status 与 AgentOps

rollout-status 和 Eval/AgentOps 增加：

- eligible 样本进度；
- excluded 样本总数；
- 按 reason 的排除计数；
- `trusted_cohort_ready`；
- auth configuration 状态；
- 下一步动作。

候选 next action：

- `fix_auth_configuration`
- `bootstrap_admin`
- `approve_verified_cohort`
- `continue_collecting_control`
- `run_shadow_preflight`

优先级：auth blocker > schema blocker > cohort blocker > sample blocker > rollout gate。

## 10. 管理员 Bootstrap 与 Cohort 管理

### 10.1 一次性管理员初始化

新增 `scripts/bootstrap_admin.py`：

```bash
ADMIN_USERNAME=<secret> ADMIN_PASSWORD=<secret> \
DATABASE_URL=<direct-or-session-url> PYTHONPATH=backend \
python3 scripts/bootstrap_admin.py
```

要求：

- username/password 只能通过环境变量或无回显 stdin；
- password 最少 12 字符；
- 不打印 password、hash 或连接串；
- 首次运行创建 admin/operator；
- 已存在时默认 no-op，不重置密码；
- 重置必须使用独立显式参数和二次确认；
- 输出只包含 `created/no_op/rotated` 和脱敏 actor fingerprint。

不在应用启动时自动创建管理员，避免长期保留 bootstrap password。

### 10.2 Cohort 审批 CLI

新增 `scripts/set_rollout_cohort.py`，只允许：

```text
unverified -> verified
verified -> unverified
* -> disabled（通过账户状态操作）
```

要求：

- 只能由受控数据库环境执行；
- 需要显式 actor ID 和 reason code；
- 写入 audit event；
- 输出 actor ID 的 hash fingerprint，不输出用户名；
- Pilot 账号不得升级为 verified；
- 禁止批量通配符升级。

本轮不提供公开 cohort 管理 HTTP API。

## 11. GitHub Runtime Preflight 更新

现有 `.github/workflows/runtime-rollout-preflight.yml` 不再依赖长期 `API_TOKEN`。

新增受保护 secrets：

- `RUNTIME_ADMIN_USERNAME`
- `RUNTIME_ADMIN_PASSWORD`

工作流步骤：

1. 调用 `/api/auth/login`；
2. 检查返回 role 必须为 admin；
3. 将 Token 加入 GitHub mask；
4. Token 只保存在当前 step/job environment；
5. 调用 rollout-status；
6. artifact 不包含登录响应、Token、username 或 password；
7. auth 401/403、cohort 不可信、control 不足均 fail-closed。

工作流权限继续保持 `contents: read`，不得拥有 Render 写权限。

## 12. 前端与 Pilot 兼容

### 12.1 登录体验

现有 `AuthContext` 和 Bearer Header 继续使用。需要覆盖所有 Pilot 主路径，找出之前因 auth disabled 被掩盖的漏传 Token：

- 学生登录、今日计划、错题、复习、AutoTutor、历史人物；
- 教师登录、作业、批改、班级分析、质量看板；
- Eval/AgentOps 页面；
- SSE/EventSource Token 传递。

不得把 Token 写入普通 URL。现有 EventSource query token 应单独整改为短期 stream ticket 或 fetch streaming；若无法在本轮完成，必须记录为 P0 blocker，不能将长期 Bearer Token留在 URL/访问日志中。

### 12.2 Pilot 标识

Pilot seed 账号固定 `traffic_cohort=demo`。页面可继续展示一键体验，但 demo 行为不能贡献 rollout baseline。UI 不展示内部 cohort 名单，只可在管理员聚合面板显示“演示流量已排除”。

## 13. API 错误合同

统一返回：

| 场景 | HTTP | detail/code |
| --- | --- | --- |
| Missing Bearer | 401 | `missing_authorization_token` |
| Invalid/expired Token | 401 | `invalid_or_expired_token` |
| Account missing/disabled | 401 | `account_inactive` |
| Role insufficient | 403 | `insufficient_role` |
| Auth config invalid | readiness/startup fail | 稳定 reason code |

不得返回“用户名是否存在”、JWT decode exception、数据库异常详情或密码校验细节。

## 14. 实施文件范围

预计修改：

| 文件 | 变更 |
| --- | --- |
| `backend/security/auth.py` | production fail-closed、DB authority、统一 role dependencies、Token TTL |
| `backend/security/accounts.py` | status/cohort 查询与安全更新 |
| `backend/deployment.py` | auth configuration contract |
| `backend/start_backend.py` | auth preflight、revision 012 |
| `backend/api/routers/debug.py` | readiness auth check |
| `backend/api/routers/agent_runtime.py` | `require_admin`、trusted rollout status |
| 其他 admin/teacher routers | 统一 RBAC 依赖 |
| `backend/agent_runtime/context.py` | eligibility-aware rollout decision |
| `backend/agent_runtime/product_runtime.py` | verified cohort Shadow gate |
| `backend/agent_runtime/rollout_observations.py` | eligibility persistence/aggregation |
| `backend/agent_runtime/rollout_gate.py` | trusted-only gate/evidence |
| `backend/agent_runtime/rollout_status.py` | auth/cohort blockers 与 excluded aggregate |
| `backend/db/schema.py` | 新字段模型 |
| `backend/alembic/versions/012_*.py` | 账户与 observation trust migration |
| `scripts/bootstrap_admin.py` | 一次性管理员初始化 |
| `scripts/set_rollout_cohort.py` | 单账号 cohort 审批/撤销 |
| `scripts/seed_pilot_demo.py` | Pilot 固定 demo cohort |
| `.github/workflows/runtime-rollout-preflight.yml` | 短期管理员登录 |
| `render.yaml` | production auth enabled |
| `frontend/*` | 补齐认证 Header、移除 URL Bearer Token |
| `eval/*` | 认证、迁移、scope、workflow contract smoke |

## 15. 测试计划

### 15.1 认证配置

- production + auth missing → startup fail；
- production + auth false → startup fail；
- production + JWT missing/default/too short → startup fail；
- production + strong secret + auth true → pass；
- local + auth false → pass with warning；
- readiness 不泄露 Secret。

### 15.2 API/RBAC

- anonymous admin status → 401；
- student admin status → 403；
- teacher admin status → 403；
- admin admin status → 200；
- disabled admin old Token → 401；
- teacher/student 主路径只访问授权资源；
- invalid、expired、wrong-signature Token → 401。

### 15.3 Cohort 与 Rollout

- demo control observation → persisted but excluded；
- unverified control observation → excluded；
- verified control observation → eligible；
- legacy row → excluded；
- eval/demo scope → excluded；
- demo/unverified 在 Shadow 配置下不创建 Runtime run；
- verified 在 Shadow 配置和 bucket 内创建 Runtime run；
- status 的 eligible/excluded 加总一致；
- baseline/gate 不统计 excluded rows；
- cohort 撤销后的新请求不再 eligible；
- API 输出不包含 actor/student/username/trace/token。

### 15.4 Migration

- SQLite `011 -> 012`；
- PostgreSQL `011 -> 012` CI；
- migration 重复执行 no-op；
- 旧账户默认 unverified；
- 旧 observation 默认 legacy_untrusted/false；
- migration 失败阻止启动；
- runtime schema readiness 要求 012。

### 15.5 Frontend/E2E

- 在 `EDU_AGENT_AUTH_REQUIRED=true` 下运行学生和教师核心流程；
- 页面刷新后恢复有效登录；
- 401 清理本地会话并返回登录页；
- SSE 不把长期 Bearer Token 放入 URL；
- Eval 页面仅管理员可查看 rollout 操作面；
- Pilot demo 登录可用但不计入 rollout。

### 15.6 Release Gate

必须通过：

- Python compile；
- auth/security/rollout/migration smoke；
- full backend smoke；
- frontend lint、unit、production build；
- Playwright authenticated core flows；
- Docker build；
- PostgreSQL migration/concurrency CI；
- Render container contract；
- workflow YAML 与 secret-negative contract。

## 16. 发布顺序

### Phase 0：代码与 CI

- 完成 migration、auth、RBAC、cohort、workflow 和 UI；
- deterministic/full gate 通过；
- 不修改生产 Runtime BPS。

### Phase 1：生产准备

1. 确认 Render 已有强 `JWT_SECRET`；
2. 使用一次性脚本创建 admin/operator；
3. 确认 Pilot 账户被标为 demo；
4. 选择少量真实试点账号并逐个审批为 verified；
5. 备份数据库；
6. 部署 revision 012 和 `EDU_AGENT_AUTH_REQUIRED=true`。

### Phase 2：认证验收

- anonymous admin → 401；
- teacher admin → 403；
- admin → 200；
- 学生/教师 Pilot 主路径通过；
- `/api/ready` auth/database/runtime schema 全部 PASS；
- 日志无 Token/密码。

### Phase 3：可信 Control

- Runtime 继续 disabled；
- verified 请求写入 eligible control；
- demo/unverified 请求只增加 excluded；
- 收集到 100 前保持 `collecting_control/unknown`；
- 达到 100 后运行现有 Shadow Preflight。

### Phase 4：继续 v1.42 Shadow 运营

本阶段复用 v1.42，不在 v1.43 自动修改 Render：

- 人工批准 history-only Shadow；
- 仅 verified cohort 可创建 Runtime run；
- 收集 100 个 eligible shadow terminal runs；
- 运行三类 evidence；
- strict gate PASS；
- 48 小时观察。

## 17. 回滚

### 17.1 认证发布失败

- 优先修复 Token 传递、账户数据或 Secret；
- 不允许长期把 production auth 改回 false；
- 若必须紧急恢复公开 Demo，只能切换到明确标识的 non-production/demo environment，且不得连接生产数据或贡献 rollout evidence。

### 17.2 Cohort/Observation 异常

- 开启 Runtime kill switch；
- verified cohort 批量扩张被禁止，只逐个撤销；
- evidence/gate 标记 stale/unknown；
- 不删除历史 observation，使用 eligibility reason 复盘；
- 修复后重新从新 commit/config 收集样本。

### 17.3 Migration 异常

- 启动入口保持失败，不跳过 revision 检查；
- 检查数据库快照、advisory lock 和 migration 日志；
- downgrade 前确认没有依赖 012 字段的新 evidence；
- 不通过手工改 Alembic revision 伪造升级成功。

## 18. 完成定义

### 18.1 Development Complete

必须同时满足：

1. production auth/JWT 配置 fail-closed；
2. 统一 admin/teacher dependencies 完成；
3. 账户状态、角色和 cohort 由数据库授权；
4. Alembic 012 与 schema readiness 完成；
5. Pilot/self-register/legacy 默认不具备 rollout eligibility；
6. Shadow 只对 verified cohort 生效；
7. baseline/gate/status/evidence 使用 trusted-only 口径；
8. 管理员 bootstrap 与 cohort CLI 完成；
9. Preflight 使用短期管理员登录，不保存长期 API Token；
10. URL 不携带长期 Bearer Token；
11. API、migration、frontend、workflow 和 release gates 通过；
12. 文档不把本地测试描述为生产认证或 rollout PASS。

### 18.2 Operational Security Complete

必须同时满足：

1. production `EDU_AGENT_AUTH_REQUIRED=true`；
2. production JWT Secret 强度检查 PASS；
3. anonymous/学生/教师/admin 权限矩阵线上验证通过；
4. Pilot 主路径在认证开启后可用；
5. 管理员账号已安全初始化；
6. Pilot 为 demo、公开注册为 unverified；
7. 至少一个受控试点 cohort 已审批；
8. readiness auth/database/schema 全部 PASS；
9. 24 小时无认证绕过、Token 泄露或 P0/P1 权限回归。

### 18.3 Rollout Operational 状态

v1.43 安全完成不等于 Runtime rollout 完成：

- eligible control <100：`collecting_control/unknown`；
- eligible control >=100：允许运行 Shadow Preflight；
- eligible shadow <100：`collecting_shadow/unknown`；
- evidence/48h 未完成：仍不是 Operational Complete；
- 任一 auth/cohort/gate failure：停止 rollout。

不得使用 demo、unverified、legacy 或 eval 数据补足门槛。

## 19. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 开启认证后前端漏传 Token | auth-enabled E2E 覆盖所有 Pilot 主路径，分阶段部署 |
| 没有管理员导致运维锁死 | 部署前先执行一次性 bootstrap 并验证登录 |
| 默认 Pilot 密码公开 | Pilot 固定 demo cohort，仅访问隔离演示数据；后续可轮换 |
| 自助注册刷样本 | 默认 unverified，不参与 rollout |
| JWT role/cohort 过期 | 每次受保护请求回查 accounts |
| Token 出现在 EventSource URL | 改用 stream ticket 或 authenticated fetch streaming |
| 迁移误把历史数据标为可信 | 全部旧 observation 默认 legacy_untrusted/false |
| 可信流量不足 | 保持 unknown，不降低阈值、不伪造请求 |
| Blueprint 配置变更触发额外部署 | 发布窗口内预期并观察两次部署，最终 commit/config 必须一致 |
| 认证关闭被当作紧急回滚 | production 启动合同拒绝；Demo 回退必须使用独立非生产环境 |

## 20. 后续迭代

只有在以下条件全部满足后，才生成 Active Canary Spec：

- v1.43 Operational Security Complete；
- verified control >=100；
- verified shadow terminal runs >=100；
- offline/real LLM/production RAG evidence PASS；
- provenance、event coverage、terminal consistency、安全与 p95 gate PASS；
- Shadow 稳定观察 >=48 小时。

满足后进入 **v1.44 `history_character` Active Canary**：verified allowlist → 1% → 10%，每阶段独立审批、evidence 和回滚点。未满足时继续执行生产认证修复或 v1.42 Shadow 运营，不增加新的 Agent 能力。

## 21. 实现记录（2026-08-30）

本地开发已完成：

- 生产认证/JWT 启动合同 fail-closed，账户状态、角色与 cohort 每次受保护请求均以数据库为准；
- 管理员路由统一使用 `require_admin`，生产 Eval/AgentOps 仅管理员可访问；
- Alembic `012`、Runtime schema readiness、旧账户 `unverified` 与旧 observation `legacy_untrusted/false` 迁移完成；
- verified-only Runtime 决策、observation 聚合、baseline、gate、status 和 evidence trust contract 完成；
- 管理员 bootstrap、单账号 cohort 审批/撤销、Pilot demo seed、Render auth 配置和短期管理员 Preflight 登录完成；
- EventSource URL Token 已替换为带 Authorization Header 的 authenticated fetch streaming；
- Eval 页面已增加认证、可信 cohort、eligible/excluded 与排除原因聚合展示。

本地验证结果：

- `scripts/release_gate.py --fast --skip-frontend`：44/44 suites、512/512 cases PASS；
- `scripts/release_gate.py`：93 suites PASS、1 个无凭证外部历史人物 smoke 按设计 SKIP，405/406 cases PASS；
- Frontend unit：8 files、22 tests PASS；
- Frontend lint：PASS；
- Frontend production build：PASS。

以上只证明 Development Complete。尚未执行生产部署、管理员初始化、线上 401/403 权限矩阵、受控学生审批、24 小时认证观察、verified control/shadow 各 100 样本、evidence gate 或 48 小时 Shadow 观察，因此 Operational Security 保持 `NOT_RUN`，Runtime rollout 保持 `unknown`，不得进入 Active。
