# AutoTutor 受控演练观测工具 v1.49.11

基线：`a8baa8933b9418592a0a06379dc6b2402592e93f`。
状态：工具代码实现；尚未部署、未执行生产演练，不代表 candidate/final GO。

## 本轮解决什么

1. Canary 采样不再强制立即生成 candidate。工作流新增 `build_candidate_evidence`，默认为 false。
   采样数量、一致性、延迟门禁和 `release_required` 含义保持不变；采样成功不是发布成功。
2. 新增默认关闭的 scoped rehearsal API，读取专用验证会话的持久化状态和 transition 观测，
   返回带签名的脱敏快照。不接收任意 SQL、不修改服务配置、不结束进程、不暴露学生内容。
3. 新增受保护、单实例、有界的人工辅助 runner，依次收集进程变化恢复、幂等重放、
   只读 writer 探针和实际 kill switch 降级观测。

## 安全边界

- `EDU_AGENT_AUTOTUTOR_REHEARSALS_ENABLED` 默认 false，只有明确设置 true 才开放。
- 仅接受现有 scoped machine 身份；普通学生或普通 admin JWT 不能调用。
- 每次检查验证账号 allowlist、数据库中的 active/student/verified 属性及持久化会话所有者。
- 会话必须存在相同 commit/config、runtime/release_verification/run 的真实 observation，
  不能把自然用户会话当演练对象。
- 账号/session/run 明文仅保留在 runner 内存及请求中，不进入输出 artifact。
- 快照签名采用现有 traffic secret + 独立域前缀 HMAC；它防止无密钥篡改，不隔离持有同一
  secret 的受信任 workflow/operator。绝不能把 artifact 的裸 hash 当独立的第三方证明。
- previous receipt 必须签名有效、未超过一小时、commit/config/cohort/session/run 全部一致。
- API 每机器主体每小时最多 180 次，writer probe 最多 6 次；数据库工作在线程池执行。
- PostgreSQL 状态读取使用一致的只读快照事务。writer probe 使用单独只读事务并始终 rollback；
  不修改数据库用户权限、schema、全局连接参数或全局 admission cache。

## 可观察事实与不能宣称的结论

### Restart

runner 创建专用 Graph 会话，提示人工重启同一提交/同一配置。服务端对比 process identity、
state/revision/effect fingerprint 和 observation 数量；之后提交一次答案，再以同一 key 重放，
要求 replay 确认、revision 和 observation 各只增加一次、无重复 effect/observation。

process identity 变化也可能来自多 worker/load-balancer 路由，**不能单独证明 Render 服务重启**。
正式 attestation 还必须绑定实际人工部署/重启事件。工具只输出已观测事实。

### Writer probe

实际调用 observation writer，但使用私有只读事务，且无论结果如何都会 rollback。
只有 PostgreSQL `25006` 或 SQLite `SQLITE_READONLY` 才计为预期故障；断网、认证错误、缺表
或其他数据库异常不能当作成功。之后调用同一 infrastructure admission 逻辑，传入请求局部的
unavailable health reader，核对重新评估的准入拒绝 Graph。

这不覆盖缓存仍有效时的请求，也不覆盖业务提交后的首次 writer failure。
当前代码在业务 commit 之后写 observation，原先“任何 writer 故障都不提交未经观测的 Graph effect”
并未由实现保证。要关闭这个缺口，需要独立评审并实现事务内 observation/outbox 等方案，
而不是把本探针填成完整 `writer_failure=pass`。

### Kill switch

runner 先创建另一专用 Graph 会话，提示人工开启实际 kill switch（保持 commit/config/BPS）。
读到开关开启后提交一次 transition，验证实际 selected executor 为 Legacy、fallback reason 为
kill_switch_enabled，且 revision/observation 各增加一次。之后提示人工恢复开关并检查 BPS 未变化。

开关本身是全局生产配置，启停必须由获授权操作员执行，可能影响自然用户；工具不会自动修改。
如果中途失败，停止 runner，人工检查并保持/恢复 Legacy+BPS0。

## 证据与发布合同

所有输出明确 `production_attestation=false`、`production_ready=false`。
runner 成功只表示观测完成，绝不自动写三项 pass、持久化 release evidence 或打开 v1.50。
已有 candidate/final 门禁未放宽，完整生产演练仍需正式审查与证据绑定。

演练的真实 transition 仍按 release_verification 写入，不偷偷从聚合中删除故障样本。
kill switch 演练可能导致 fallback，从而阻塞覆盖该演练时间段的性能采样窗口。
不能缩短既有失败窗口来伪造通过。后续需要明确独立的测量窗口与演练窗口绑定合同；
本工具不冒充已解决这项 release-evidence 设计问题。

## 运行步骤（本轮不自动执行）

1. 提交、CI（含 PostgreSQL）通过、部署新 SHA；原 SHA 的 control 不能充当新基线。
2. 操作员确认受控演练时段、账号、回退措施；显式启用 REHEARSALS_ENABLED。
3. 准备 active_canary/BPS100、kill switch false、同配置与可信 cohort。
4. 手动运行 `AutoTutor Scoped Rehearsal Observations`，批准 production-verification。
5. 日志提示 `manual_restart_required_keep_commit_and_config` 后，人工重启服务。
6. `manual_enable_kill_switch_required` 后，人工开启 kill switch 并等待部署成功。
7. `manual_restore_kill_switch_false_keep_bps_required` 后，人工恢复开关、保持 BPS。
8. 下载 artifact，复核观测事实和覆盖限制；最终关闭 rehearsal endpoint，并保持/恢复 Legacy/BPS0。

总预算 3000 秒、job 上限 60 分钟；只读 checkpoint 可在重启期间重试 502/503/504 或传输超时，
有副作用 POST 不自动重试。显式幂等重放是测试步骤，不是失败重试。
超时/失败保留脱敏 artifact；`transition_outcome_unknown=true` 表示请求可能已经提交，不得盲目再发新 key。
进程强杀可能只留下最后检查点，工具不能保证主机失联后的 artifact 上传。

## 测试

- `eval/autotutor_rehearsals_smoke.py`：allowlist/owner/run/commit、签名篡改/过期、未重启误判、
  状态恢复、单次续答、实际 SQLite 只读拒写、连接状态恢复、kill switch 事实、API 默认关闭/普通admin拒绝。
- `eval/autotutor_rehearsal_runner_smoke.py`：模拟全流程、同 key 重放、有界超时、脱敏和禁止产出 GO。
- `eval/postgres_schema_smoke.py`：在已有 CI PostgreSQL 上执行真实 25006 探针，核对无新增 observation。
- 两组本地测试注册到 fast/core release gate；原安全、准入、writer failure 测试继续运行。
