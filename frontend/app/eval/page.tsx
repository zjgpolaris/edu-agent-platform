"use client";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const FALLBACK_SUITES: SuiteOption[] = [
  { id: "quick", label: "快速（smoke + RAG）", category: "preset", kind: "quick" },
  { id: "all", label: "完整（核心 suite）", category: "preset", kind: "core" },
  { id: "history_character_smoke", label: "历史人物 Smoke", category: "agent", kind: "smoke" },
  { id: "history_character_eval", label: "历史人物对话", category: "agent", kind: "quality" },
  { id: "rag_retrieval_eval", label: "RAG 检索质量", category: "rag", kind: "quality" },
  { id: "textbook_qa_eval", label: "教材问答", category: "rag", kind: "quality" },
  { id: "game_generation_eval", label: "游戏生成", category: "agent", kind: "quality" },
  { id: "learning_assistant_smoke", label: "学习助手工具 Smoke", category: "tools", kind: "smoke" },
  { id: "material_rag_smoke", label: "材料 RAG Smoke", category: "rag", kind: "smoke" },
  { id: "student_profile_smoke", label: "学生画像 Smoke", category: "memory", kind: "smoke" },
  { id: "homework_grading_smoke", label: "作业批改 Smoke", category: "agent", kind: "smoke" },
  { id: "guardrails_smoke", label: "Guardrails Smoke", category: "safety", kind: "smoke" },
  { id: "ragas_eval", label: "Ragas 质量评估", category: "rag", kind: "quality" },
];

type CountMetric = { passed: number; total: number };
type ScalarMetric = { value: number };
type MetricEntry = CountMetric | ScalarMetric;
type SuiteOption = { id: string; label: string; category?: string; kind?: string; priority?: string };
type FailedCase = {
  name: string;
  reason?: string;
  query?: string;
  expected?: unknown;
  actual?: unknown;
  category?: string;
  trace_id?: string;
};
type SuiteResult = {
  name: string;
  label?: string;
  category?: string;
  kind?: string;
  status?: string;
  ok: boolean;
  duration_sec?: number;
  passed_cases?: number;
  total_cases?: number;
  metrics?: Record<string, MetricEntry>;
  failed_cases?: Array<string | FailedCase>;
  stdout?: string;
  stderr?: string;
  error?: string;
};
type AgentOpsSummary = {
  status: string;
  trace_correlation?: {
    audit_total: number;
    audit_with_trace: number;
    learning_total: number;
    learning_with_trace: number;
    coverage_rate: number;
    unique_trace_ids: number;
  };
  audit?: { total: number; failure: number; by_action?: Record<string, number> };
  learning?: { total: number; failure: number; by_feature?: Record<string, number> };
  tools?: { by_tool_name?: Record<string, number> };
  traces?: { recent?: Array<{ trace_id: string; latest_at?: string; actions?: string[]; features?: string[]; tools?: string[] }> };
  error?: string;
};

type EvalSummary = { total: number; passed: number; failed: number; skipped: number; pass_rate: number };
type EvalTopLevelMetrics = {
  task_success_rate?: number;
  retrieval_hit_rate?: number;
  source_correctness?: number;
  tool_schema_validity?: number;
  guardrail_pass_rate?: number;
  format_validity?: number;
  avg_latency_ms?: number;
};
type CategorySummary = Record<string, { passed: number; failed: number; skipped: number }>;
type EvalCandidate = {
  id: string;
  action: string;
  actor_id: string;
  actor_role?: string;
  created_at: string;
  trace_id?: string;
  tool_name?: string;
  error_code?: string;
  query?: string;
  payload?: Record<string, unknown>;
  expected_error?: string;
  expected_ok?: boolean;
  suggested_suite: string;
  save_ready?: boolean;
  missing_fields?: string[];
  draft_kind?: string;
};
type RunResult = {
  ok: boolean;
  generated_at?: string;
  summary?: EvalSummary;
  metrics?: EvalTopLevelMetrics;
  category_summary?: CategorySummary;
  report_paths?: { json?: string; markdown?: string };
  passed?: number;
  total?: number;
  passed_suites?: number;
  total_suites?: number;
  passed_cases?: number;
  total_cases?: number;
  duration_sec?: number;
  suites: SuiteResult[];
  agent_ops?: AgentOpsSummary;
  detail?: string;
};

function isCountMetric(metric: MetricEntry): metric is CountMetric {
  return "passed" in metric && "total" in metric;
}

function normalizeFailedCase(value: string | FailedCase): FailedCase {
  if (typeof value === "string") return { name: value };
  return { ...value, name: value.name || "unknown_case" };
}

function formatUnknown(value: unknown): string {
  if (value == null || value === "") return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  const encoded = JSON.stringify(value);
  return (encoded || String(value)).slice(0, 220);
}

type HistorySnapshot = {
  generated_at?: string;
  ok?: boolean;
  passed_cases?: number;
  total_cases?: number;
  passed_suites?: number;
  total_suites?: number;
  duration_sec?: number;
  summary?: { pass_rate?: number };
  metrics?: EvalTopLevelMetrics;
};

export default function EvalPage() {
  const { user } = useAuth();
  const [selected, setSelected] = useState("quick");
  const [suiteOptions, setSuiteOptions] = useState<SuiteOption[]>(FALLBACK_SUITES);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [latestStatus, setLatestStatus] = useState("正在读取 latest report…");
  const [agentOps, setAgentOps] = useState<AgentOpsSummary | null>(null);
  const [agentOpsError, setAgentOpsError] = useState<string | null>(null);
  const [expandedSuite, setExpandedSuite] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<EvalCandidate[]>([]);
  const [history, setHistory] = useState<HistorySnapshot[]>([]);
  const [savedCases, setSavedCases] = useState<Set<string>>(new Set());
  const [dedupedCases, setDedupedCases] = useState<Set<string>>(new Set());
  const [savingCaseId, setSavingCaseId] = useState<string | null>(null);
  const [caseSaveMessages, setCaseSaveMessages] = useState<Record<string, string>>({});

  useEffect(() => {
    async function loadSuites() {
      if (!user?.token) return;
      try {
        const res = await fetch(`${API}/api/eval/suites`, { headers: authHeaders(user.token) });
        if (!res.ok) return;
        const data = await res.json();
        const dynamicSuites: SuiteOption[] = Array.isArray(data.suites) ? data.suites : [];
        setSuiteOptions([
          { id: "quick", label: "快速（smoke + RAG）", category: "preset", kind: "quick" },
          { id: "all", label: "完整（核心 suite）", category: "preset", kind: "core" },
          ...dynamicSuites,
        ]);
      } catch {
        setSuiteOptions(FALLBACK_SUITES);
      }
    }
    async function loadAgentOps() {
      try {
        const headers = user?.token ? authHeaders(user.token) : undefined;
        const res = await fetch(`${API}/api/agent-ops/summary?limit=100`, { headers });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          setAgentOpsError(data.detail || `AgentOps 请求失败：${res.status}`);
          return;
        }
        setAgentOps(data);
        setAgentOpsError(null);
      } catch (e) {
        setAgentOpsError(String(e));
      }
    }
    async function loadLatest() {
      try {
        const headers = user?.token ? authHeaders(user.token) : undefined;
        const res = await fetch(`${API}/api/eval/latest`, { headers });
        const data = await res.json().catch(() => ({}));
        if (res.status === 404) {
          setLatestStatus("暂无 latest report，可运行 quick eval 生成。");
          return;
        }
        if (!res.ok) {
          setLatestStatus(data.detail || `latest report 请求失败：${res.status}`);
          return;
        }
        setResult({ ...data, suites: Array.isArray(data.suites) ? data.suites : [] });
        setLatestStatus("已加载 latest report");
        if (data.agent_ops) setAgentOps(data.agent_ops);
      } catch (e) {
        setLatestStatus(String(e));
      }
    }
    async function loadHistory() {
      try {
        const headers = user?.token ? authHeaders(user.token) : undefined;
        const res = await fetch(`${API}/api/eval/history?limit=20`, { headers });
        if (!res.ok) return;
        const data = await res.json();
        if (Array.isArray(data.snapshots)) setHistory(data.snapshots as HistorySnapshot[]);
      } catch { /* ignore */ }
    }
    loadSuites();
    loadAgentOps();
    loadLatest();
    loadHistory();
    if (user?.token) {
      fetch(`${API}/api/eval/candidate-cases?limit=15`, { headers: authHeaders(user.token) })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d?.candidates) setCandidates(d.candidates as EvalCandidate[]); })
        .catch(() => null);
    }
  }, [user?.token]);

  const selectedOption = useMemo(
    () => suiteOptions.find(option => option.id === selected),
    [selected, suiteOptions],
  );

  async function run() {
    setRunning(true);
    setExpandedSuite(null);
    try {
      const headers = { "Content-Type": "application/json", ...(user?.token ? authHeaders(user.token) : {}) };
      const res = await fetch(`${API}/api/eval/run`, {
        method: "POST",
        headers,
        body: JSON.stringify({ suite: selected }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = data.detail || `请求失败：${res.status}`;
        setResult({ ok: false, passed: 0, total: 1, suites: [{ name: "api", ok: false, metrics: {}, failed_cases: [], error: message }] });
        return;
      }
      setResult({ ...data, suites: Array.isArray(data.suites) ? data.suites : [] });
      setLatestStatus("刚刚生成新的 eval report");
      if (data.agent_ops) setAgentOps(data.agent_ops);
      // refresh history
      fetch(`${API}/api/eval/history?limit=20`, { headers: { "Content-Type": "application/json", ...(user?.token ? authHeaders(user.token) : {}) } })
        .then(r => r.ok ? r.json() : null).then(d => { if (d?.snapshots) setHistory(d.snapshots as HistorySnapshot[]); }).catch(() => null);
    } catch (e) {
      setResult({ ok: false, passed: 0, total: 1, suites: [{ name: "network", ok: false, metrics: {}, failed_cases: [], error: String(e) }] });
    } finally {
      setRunning(false);
    }
  }

  const passedSuites = result?.passed_suites ?? result?.passed ?? 0;
  const totalSuites = result?.total_suites ?? result?.total ?? 0;

  async function saveCase(candidate: EvalCandidate) {
    if (!user?.token) return;
    if (candidate.save_ready === false) {
      setCaseSaveMessages(prev => ({ ...prev, [candidate.id]: `缺少字段：${(candidate.missing_fields || []).join("、") || "未知"}` }));
      return;
    }
    const name = `trace_${candidate.action}_${candidate.id.slice(0, 8)}`;
    const caseObj = {
      action: candidate.action,
      tool_name: candidate.tool_name,
      error_code: candidate.error_code,
      actor_role: candidate.actor_role,
      expected_error: candidate.expected_error,
      expected_ok: candidate.expected_ok,
      query: candidate.query,
      payload: candidate.payload,
      trace_id: candidate.trace_id,
    };
    setSavingCaseId(candidate.id);
    setCaseSaveMessages(prev => ({ ...prev, [candidate.id]: "正在保存…" }));
    try {
      const res = await fetch(`${API}/api/eval/save-case`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(user.token) },
        body: JSON.stringify({ suite: candidate.suggested_suite, name, case: caseObj }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setCaseSaveMessages(prev => ({ ...prev, [candidate.id]: data.detail || `保存失败：${res.status}` }));
        return;
      }
      if (data.deduplicated) {
        setDedupedCases(prev => {
          const next = new Set(prev);
          next.add(candidate.id);
          return next;
        });
        setCaseSaveMessages(prev => ({ ...prev, [candidate.id]: `已存在于 ${data.file}` }));
      } else {
        setSavedCases(prev => {
          const next = new Set(prev);
          next.add(candidate.id);
          return next;
        });
        setCaseSaveMessages(prev => ({ ...prev, [candidate.id]: `已保存到 ${data.file}` }));
      }
    } finally {
      setSavingCaseId(null);
    }
  }

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: "2rem 1.5rem", fontFamily: "inherit" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "0.25rem", color: "var(--ink)" }}>
        Eval 评估中心
      </h1>
      <p style={{ color: "var(--ink-soft)", fontSize: "0.875rem", marginBottom: "2rem" }}>
        运行后端 eval suite，查看 RAG 检索、历史对话、教材 QA、工具调用和材料 RAG 等模块的指标通过率。
      </p>

      <AgentOpsPanel summary={agentOps} error={agentOpsError} />
      <TrendBar snapshots={history} />

      <div style={{ marginBottom: "1rem", color: "var(--ink-soft)", fontSize: "0.82rem" }}>{latestStatus}</div>

      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "1.5rem", alignItems: "center" }}>
        <select
          value={selected}
          onChange={e => setSelected(e.target.value)}
          disabled={running}
          style={{
            padding: "0.5rem 0.875rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-strong)",
            background: "var(--paper-soft)", color: "var(--ink)", fontSize: "0.875rem", cursor: "pointer",
          }}
        >
          {suiteOptions.map(s => <option key={s.id} value={s.id}>{s.label || s.id}</option>)}
        </select>
        {selectedOption && (
          <span style={{ fontSize: "0.75rem", color: "var(--ink-soft)", display: "flex", gap: "0.35rem" }}>
            {selectedOption.category && <Badge>{selectedOption.category}</Badge>}
            {selectedOption.kind && <Badge>{selectedOption.kind}</Badge>}
          </span>
        )}
        <button
          onClick={run}
          disabled={running}
          style={{
            padding: "0.5rem 1.5rem", borderRadius: "var(--radius-sm)",
            background: running ? "var(--muted)" : "var(--jade)", color: "#fff",
            border: "none", fontSize: "0.875rem", fontWeight: 600,
            cursor: running ? "not-allowed" : "pointer", transition: "background var(--ease)",
          }}
        >
          {running ? "运行中…" : "运行"}
        </button>
      </div>

      {result && (
        <div>
          <div style={{
            display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1.25rem",
            padding: "0.875rem 1.25rem", borderRadius: "var(--radius-sm)",
            background: result.ok ? "var(--jade-soft)" : "#fdecea",
            border: `1px solid ${result.ok ? "var(--jade)" : "var(--cinnabar)"}`,
          }}>
            <span style={{ fontSize: "1.25rem" }}>{result.ok ? "✓" : "✗"}</span>
            <span style={{ fontWeight: 600, color: result.ok ? "var(--jade-dark)" : "var(--cinnabar-dark)" }}>
              {result.ok ? "全部通过" : "存在失败"}
            </span>
            <span style={{ color: "var(--ink-soft)", fontSize: "0.875rem" }}>
              {passedSuites}/{totalSuites} suite 通过
              {result.total_cases ? ` · ${result.passed_cases || 0}/${result.total_cases} cases` : ""}
              {result.duration_sec != null ? ` · ${result.duration_sec.toFixed(1)}s` : ""}
            </span>
          </div>

          <ReportOverview result={result} token={user?.token} />

          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {result.suites.map(suite => {
              const failedCases = (suite.failed_cases || []).map(normalizeFailedCase);
              const metrics = suite.metrics || {};
              const totalCases = suite.total_cases || 0;
              const passedCases = suite.passed_cases || 0;
              return (
                <div key={suite.name} style={{
                  borderRadius: "var(--radius-sm)", border: "1px solid var(--border)",
                  background: "var(--paper-soft)", overflow: "hidden",
                }}>
                  <div
                    onClick={() => setExpandedSuite(expandedSuite === suite.name ? null : suite.name)}
                    style={{
                      display: "flex", alignItems: "center", gap: "0.875rem",
                      padding: "0.75rem 1rem", cursor: "pointer",
                      background: suite.ok ? "transparent" : "rgba(183,66,43,0.04)",
                    }}
                  >
                    <span style={{
                      fontWeight: 700, fontSize: "0.75rem", padding: "0.15rem 0.5rem",
                      borderRadius: 4, background: suite.ok ? "var(--jade)" : "var(--cinnabar)", color: "#fff",
                    }}>
                      {suite.status ? suite.status.toUpperCase() : suite.ok ? "PASS" : "FAIL"}
                    </span>
                    <span style={{ fontWeight: 600, flex: 1 }}>{suite.label || suite.name}</span>
                    {suite.category && <Badge>{suite.category}</Badge>}
                    {suite.kind && <Badge>{suite.kind}</Badge>}
                    {totalCases > 0 && (
                      <span style={{ fontSize: "0.8rem", color: "var(--ink-soft)" }}>
                        {passedCases}/{totalCases} cases
                      </span>
                    )}
                    {suite.duration_sec != null && (
                      <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>{suite.duration_sec.toFixed(1)}s</span>
                    )}
                    <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}>{expandedSuite === suite.name ? "▲" : "▼"}</span>
                  </div>

                  {expandedSuite === suite.name && (
                    <div style={{ borderTop: "1px solid var(--border)", padding: "0.875rem 1rem" }}>
                      {suite.error && (
                        <pre style={{ margin: 0, color: "var(--cinnabar)", fontSize: "0.8rem", whiteSpace: "pre-wrap" }}>
                          {suite.error}
                        </pre>
                      )}

                      {Object.keys(metrics).length > 0 && (
                        <div style={{ marginBottom: "0.75rem" }}>
                          <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--ink-soft)", marginBottom: "0.5rem", textTransform: "uppercase" }}>
                            指标
                          </div>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
                            {Object.entries(metrics).map(([name, m]) => {
                              const pct = isCountMetric(m) && m.total ? Math.round((m.passed / m.total) * 100) : null;
                              return (
                                <div key={name} style={{
                                  padding: "0.35rem 0.75rem", borderRadius: 6,
                                  background: pct == null || pct === 100 ? "var(--jade-soft)" : pct >= 60 ? "#fff8e1" : "#fdecea",
                                  border: `1px solid ${pct == null || pct === 100 ? "var(--jade)" : pct >= 60 ? "var(--gold)" : "var(--cinnabar)"}`,
                                  fontSize: "0.8rem",
                                }}>
                                  <span style={{ color: "var(--ink-soft)" }}>{name.replace(/_rate$/, "").replace(/_/g, " ")}</span>
                                  {isCountMetric(m) ? (
                                    <>
                                      {" "}
                                      <span style={{ fontWeight: 700 }}>{m.passed}/{m.total}</span>
                                      {" "}
                                      <span style={{ color: "var(--muted)" }}>({pct || 0}%)</span>
                                    </>
                                  ) : (
                                    <>
                                      {" "}
                                      <span style={{ fontWeight: 700 }}>{m.value.toFixed(3)}</span>
                                    </>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {failedCases.length > 0 && (
                        <div style={{ marginBottom: "0.75rem" }}>
                          <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--cinnabar)", marginBottom: "0.4rem" }}>
                            失败用例
                          </div>
                          <div style={{ display: "grid", gap: "0.5rem" }}>
                            {failedCases.map((c) => (
                              <div key={`${suite.name}-${c.name}`} style={{
                                padding: "0.6rem 0.75rem", borderRadius: 8, fontSize: "0.8rem",
                                background: "#fdecea", border: "1px solid var(--cinnabar)", color: "var(--cinnabar-dark)",
                              }}>
                                <strong>{c.name}</strong>
                                {c.reason && <div style={{ marginTop: 3 }}>{c.reason}</div>}
                                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", marginTop: 6 }}>
                                  {c.category && <Badge>{c.category}</Badge>}
                                  {c.trace_id && <Badge>trace {c.trace_id.slice(0, 10)}</Badge>}
                                  {c.query && <Badge>query: {c.query.slice(0, 40)}</Badge>}
                                </div>
                                {(c.expected != null || c.actual != null) && (
                                  <div style={{ marginTop: 6, color: "var(--ink-soft)" }}>
                                    {c.expected != null && <div><strong>Expected:</strong> {formatUnknown(c.expected)}</div>}
                                    {c.actual != null && <div><strong>Actual:</strong> {formatUnknown(c.actual)}</div>}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {suite.stdout && (
                        <details>
                          <summary style={{ fontSize: "0.8rem", color: "var(--ink-soft)", cursor: "pointer", marginBottom: "0.4rem" }}>
                            原始输出
                          </summary>
                          <pre style={{
                            margin: 0, fontSize: "0.75rem", lineHeight: 1.5,
                            background: "var(--paper-strong)", padding: "0.75rem",
                            borderRadius: 6, overflowX: "auto", whiteSpace: "pre-wrap",
                            maxHeight: 320, overflowY: "auto", color: "var(--ink)",
                          }}>
                            {suite.stdout}
                            {suite.stderr ? "\n--- stderr ---\n" + suite.stderr : ""}
                          </pre>
                        </details>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {candidates.length > 0 && (
        <div style={{ marginTop: "2rem", borderTop: "1px solid var(--border)", paddingTop: "1.5rem" }}>
          <div style={{ fontWeight: 700, color: "var(--ink)", marginBottom: "0.25rem" }}>Trace-to-Eval 失败样本回流</div>
          <p style={{ fontSize: "0.82rem", color: "var(--ink-soft)", margin: "0 0 1rem" }}>从审计日志中提取工具失败/权限拒绝事件，可一键存为 eval dataset 供回归测试。</p>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {candidates.map((c) => {
              const saved = savedCases.has(c.id);
              const deduped = dedupedCases.has(c.id);
              const disabled = saved || deduped || savingCaseId === c.id || c.save_ready === false;
              const missing = c.missing_fields || [];
              return (
                <div key={c.id} style={{ display: "grid", gap: "0.45rem", padding: "0.6rem 0.875rem", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: c.save_ready === false ? "rgba(253,236,234,0.45)" : "var(--paper-soft)", fontSize: "0.8rem" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                    <Badge>{c.action}</Badge>
                    {c.draft_kind && <Badge>{c.draft_kind}</Badge>}
                    {c.tool_name && <Badge>{c.tool_name}</Badge>}
                    {c.error_code && <Badge>{c.error_code}</Badge>}
                    {c.expected_error && <Badge>expect: {c.expected_error}</Badge>}
                    {c.actor_role && <Badge>role: {c.actor_role}</Badge>}
                    <span style={{ flex: 1, color: "var(--ink-soft)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.query || c.trace_id || c.id}</span>
                    <span style={{ color: "var(--muted)", fontSize: "0.72rem" }}>{c.suggested_suite}</span>
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => void saveCase(c)}
                      title={c.save_ready === false ? `缺少字段：${missing.join("、")}` : undefined}
                      style={{ border: `1px solid ${c.save_ready === false ? "var(--muted)" : "var(--jade)"}`, borderRadius: 6, background: saved || deduped ? "var(--jade-soft)" : "transparent", color: c.save_ready === false ? "var(--muted)" : "var(--jade-dark)", fontSize: "0.72rem", fontWeight: 700, padding: "0.2rem 0.6rem", cursor: disabled ? "default" : "pointer", whiteSpace: "nowrap" }}
                    >
                      {savingCaseId === c.id ? "保存中…" : saved ? "已保存" : deduped ? "已存在" : c.save_ready === false ? "不可保存" : "存为 Case"}
                    </button>
                  </div>
                  {(caseSaveMessages[c.id] || c.save_ready === false) && (
                    <div style={{ color: c.save_ready === false ? "var(--cinnabar-dark)" : "var(--ink-soft)", fontSize: "0.74rem" }}>
                      {caseSaveMessages[c.id] || `缺少字段：${missing.join("、")}`}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function formatRate(value?: number) {
  if (value == null) return "--";
  return `${Math.round(value * 100)}%`;
}

function ReportOverview({ result, token }: { result: RunResult; token?: string }) {
  const metrics = result.metrics || {};
  const categorySummary = result.category_summary || {};
  const failedCases = result.suites.flatMap((suite) => (suite.failed_cases || []).map((item) => ({ suite: suite.name, category: suite.category || "other", item: normalizeFailedCase(item) })));
  const [downloadStatus, setDownloadStatus] = useState("");
  async function downloadReport(kind: "json" | "markdown") {
    setDownloadStatus(`正在下载 latest.${kind === "json" ? "json" : "md"}…`);
    const res = await fetch(`${API}/api/eval/report/${kind}`, { headers: token ? authHeaders(token) : undefined });
    if (!res.ok) {
      setDownloadStatus(`latest.${kind === "json" ? "json" : "md"} 暂不可下载`);
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = kind === "json" ? "eduagent-eval-latest.json" : "eduagent-eval-latest.md";
    link.click();
    URL.revokeObjectURL(url);
    setDownloadStatus(`已下载 latest.${kind === "json" ? "json" : "md"}`);
  }
  return (
    <div style={{ display: "grid", gap: "1rem", marginBottom: "1.25rem" }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center", color: "var(--ink-soft)", fontSize: "0.82rem" }}>
        {result.generated_at && <span>Report: {new Date(result.generated_at).toLocaleString()}</span>}
        <button type="button" onClick={() => void downloadReport("json")} style={{ border: "none", background: "transparent", color: "var(--jade-dark)", fontWeight: 700, cursor: "pointer", padding: 0 }}>下载 latest.json</button>
        <button type="button" onClick={() => void downloadReport("markdown")} style={{ border: "none", background: "transparent", color: "var(--jade-dark)", fontWeight: 700, cursor: "pointer", padding: 0 }}>下载 latest.md</button>
        {downloadStatus && <span>{downloadStatus}</span>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "0.75rem" }}>
        <OpsCard label="Task success" value={formatRate(metrics.task_success_rate ?? result.summary?.pass_rate)} hint={`${result.summary?.passed ?? result.passed_cases ?? 0}/${result.summary?.total ?? result.total_cases ?? 0} cases`} />
        <OpsCard label="Retrieval hit" value={formatRate(metrics.retrieval_hit_rate)} hint="rag grounding" />
        <OpsCard label="Tool schema" value={formatRate(metrics.tool_schema_validity)} hint="tool governance" />
        <OpsCard label="Guardrail pass" value={formatRate(metrics.guardrail_pass_rate)} hint="safety cases" />
        <OpsCard label="Avg latency" value={metrics.avg_latency_ms != null ? `${Math.round(metrics.avg_latency_ms)}ms` : "--"} hint="per case" />
      </div>

      <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "0.85rem 1rem", background: "var(--paper-soft)" }}>
        <div style={{ fontWeight: 700, color: "var(--ink)", marginBottom: "0.6rem" }}>Category summary</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
          {Object.keys(categorySummary).length ? Object.entries(categorySummary).map(([category, counts]) => (
            <Badge key={category}>{category} · {counts.passed} pass / {counts.failed} fail / {counts.skipped} skip</Badge>
          )) : <span style={{ color: "var(--muted)", fontSize: "0.82rem" }}>No category summary.</span>}
        </div>
      </div>

      <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "0.85rem 1rem", background: failedCases.length ? "#fdecea" : "var(--paper-soft)" }}>
        <div style={{ fontWeight: 700, color: failedCases.length ? "var(--cinnabar-dark)" : "var(--ink)", marginBottom: "0.6rem" }}>Failed cases</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
          {failedCases.length ? failedCases.map((failed) => <Badge key={`${failed.suite}-${failed.item.name}`}>{failed.category} · {failed.suite}: {failed.item.name}{failed.item.reason ? ` — ${failed.item.reason}` : ""}</Badge>) : <span style={{ color: "var(--muted)", fontSize: "0.82rem" }}>None</span>}
        </div>
      </div>
    </div>
  );
}

function AgentOpsPanel({ summary, error }: { summary: AgentOpsSummary | null; error: string | null }) {
  const trace = summary?.trace_correlation;
  const traced = (trace?.audit_with_trace || 0) + (trace?.learning_with_trace || 0);
  const total = (trace?.audit_total || 0) + (trace?.learning_total || 0);
  const coverage = trace ? Math.round((trace.coverage_rate || 0) * 100) : 0;
  const coverageHealth = !trace ? "waiting" : coverage >= 80 ? "healthy" : coverage >= 30 ? "partial" : "needs attention";
  const coverageHint = trace ? `${traced}/${total} events · ${coverageHealth}` : "等待数据";
  return (
    <div style={{
      border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
      background: "var(--paper-soft)", padding: "1rem 1.125rem", marginBottom: "1.5rem",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.85rem" }}>
        <h2 style={{ margin: 0, fontSize: "1rem", color: "var(--ink)", flex: 1 }}>AgentOps 运行状态</h2>
        <Badge>{summary?.status || (error ? "unavailable" : "loading")}</Badge>
      </div>
      {error ? (
        <div style={{ color: "var(--cinnabar)", fontSize: "0.82rem" }}>{error}</div>
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "0.75rem", marginBottom: "0.85rem" }}>
            <OpsCard label="Trace 覆盖率" value={trace ? `${coverage}%` : "--"} hint={coverageHint} />
            <OpsCard label="Audit Events" value={String(summary?.audit?.total ?? "--")} hint={`${summary?.audit?.failure ?? 0} failed`} />
            <OpsCard label="Learning Events" value={String(summary?.learning?.total ?? "--")} hint={`${summary?.learning?.failure ?? 0} failed`} />
            <OpsCard label="Trace IDs" value={String(trace?.unique_trace_ids ?? "--")} hint="recent window" />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: "0.75rem" }}>
            <Rollup title="Top actions" items={summary?.audit?.by_action} />
            <Rollup title="Top features" items={summary?.learning?.by_feature} />
            <Rollup title="Top tools" items={summary?.tools?.by_tool_name} />
          </div>
          <div style={{ marginTop: "0.75rem", fontSize: "0.78rem", color: coverage >= 80 ? "var(--jade-dark)" : coverage >= 30 ? "#7a5524" : "var(--cinnabar-dark)" }}>
            Trace coverage 是 Agent 工程质量信号：{coverageHealth}。
          </div>
          {summary?.traces?.recent?.length ? (
            <div style={{ marginTop: "0.85rem", fontSize: "0.78rem", color: "var(--ink-soft)" }}>
              最近 trace：{summary.traces.recent.slice(0, 3).map(item => item.trace_id.slice(0, 10)).join("、")}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

function OpsCard({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.65rem 0.75rem", background: "var(--paper-strong)" }}>
      <div style={{ fontSize: "0.72rem", color: "var(--ink-soft)", marginBottom: "0.25rem" }}>{label}</div>
      <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--ink)" }}>{value}</div>
      <div style={{ fontSize: "0.72rem", color: "var(--muted)" }}>{hint}</div>
    </div>
  );
}

function Rollup({ title, items }: { title: string; items?: Record<string, number> }) {
  const entries = Object.entries(items || {}).slice(0, 5);
  return (
    <div style={{ fontSize: "0.78rem" }}>
      <div style={{ fontWeight: 600, color: "var(--ink-soft)", marginBottom: "0.35rem" }}>{title}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
        {entries.length ? entries.map(([name, count]) => <Badge key={name}>{name} · {count}</Badge>) : <span style={{ color: "var(--muted)" }}>None</span>}
      </div>
    </div>
  );
}

function Badge({ children }: { children: ReactNode }) {
  return (
    <span style={{
      padding: "0.15rem 0.45rem",
      borderRadius: 999,
      background: "var(--paper-strong)",
      border: "1px solid var(--border)",
      color: "var(--ink-soft)",
      fontSize: "0.72rem",
      lineHeight: 1.4,
    }}>
      {children}
    </span>
  );
}

function TrendBar({ snapshots }: { snapshots: HistorySnapshot[] }) {
  if (snapshots.length === 0) return null;
  const MAX_BARS = 20;
  const items = snapshots.slice(-MAX_BARS);
  const maxH = 48;
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "0.85rem 1rem", background: "var(--paper-soft)", marginBottom: "1.5rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.6rem" }}>
        <span style={{ fontWeight: 700, fontSize: "0.875rem", color: "var(--ink)" }}>Eval 通过率趋势</span>
        <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>{items.length} 次运行</span>
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: maxH }}>
        {items.map((snap, i) => {
          const rate = snap.summary?.pass_rate ?? (snap.passed_cases != null && snap.total_cases ? snap.passed_cases / snap.total_cases : null);
          const pct = rate != null ? Math.round(rate * 100) : null;
          const h = pct != null ? Math.max(4, Math.round((pct / 100) * maxH)) : 4;
          const color = snap.ok ? "var(--jade)" : "var(--cinnabar)";
          const label = snap.generated_at ? new Date(snap.generated_at).toLocaleString() : `run ${i + 1}`;
          return (
            <div key={i} title={`${label}\n通过率 ${pct != null ? pct + "%" : "—"} · ${snap.passed_cases ?? "?"}/${snap.total_cases ?? "?"} cases`}
              style={{ flex: 1, height: h, background: color, borderRadius: 3, opacity: 0.85, transition: "height 0.3s", cursor: "default" }} />
          );
        })}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontSize: "0.68rem", color: "var(--muted)" }}>
        <span>{items[0]?.generated_at ? new Date(items[0].generated_at).toLocaleDateString() : "earliest"}</span>
        <span>{items[items.length - 1]?.generated_at ? new Date(items[items.length - 1]!.generated_at!).toLocaleDateString() : "latest"}</span>
      </div>
    </div>
  );
}
