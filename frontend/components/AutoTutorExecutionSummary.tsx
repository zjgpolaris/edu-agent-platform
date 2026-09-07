export type ExecutionSummary = {
  schema_version: 1;
  profile: "local_demo_graph";
  revision: number;
  assigned_executor: "legacy" | "graph_active" | null;
  selected_executor: "legacy" | "graph_active" | null;
  graph_attempt_status: "completed" | "failed" | "mismatch" | "not_run";
  visited_nodes: string[];
  fallback_reason: string | null;
  input_mode: "deterministic_fixture";
  production_evidence: false;
};

export function AutoTutorExecutionSummary({ execution }: { execution?: ExecutionSummary | null }) {
  if (!execution) return <p>执行来源未记录</p>;
  return <section aria-label="实际执行摘要">
    <strong>{execution.selected_executor === "graph_active" ? "本地 Graph" : "Legacy"} · 确定性演示</strong>
    <p>分配：{execution.assigned_executor === "graph_active" ? "Graph" : "Legacy"} · 版本 {execution.revision} · 非生产验证证据</p>
    {execution.fallback_reason ? <p role="status">已降级：{execution.fallback_reason}</p> : null}
    <p>{execution.graph_attempt_status === "completed" ? "实际 Graph 节点" : "Graph 尝试轨迹"}：{execution.visited_nodes.join(" → ") || "没有可展示的节点记录"}</p>
  </section>;
}
