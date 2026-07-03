"use client";
import { useState, useEffect } from "react";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Totals = {
  assignment_count: number;
  question_count: number;
  objective_count: number;
  quality_checked_count: number;
  semantic_checked_count: number;
};
type Distribution = { error: number; warn: number; ok: number; unchecked: number };
type Effectiveness = {
  proactive_flagged: number;
  suspected_false_alarm: number;
  blind_spots_total: number;
  blind_spots_open: number;
  blind_spots_confirmed_bad: number;
  blind_spots_not_mastered: number;
};
type HardestQuestion = {
  assignment_id: string;
  assignment_title: string;
  question_index: number;
  prompt: string;
  accuracy: number;
  attempts: number;
  predicted_level: string | null;
};
type Dashboard = {
  totals: Totals;
  quality_distribution: Distribution;
  effectiveness: Effectiveness;
  review_verdicts: { bad_question: number; not_mastered: number };
  top_issue_types: Array<{ issue: string; count: number }>;
  hardest_questions: HardestQuestion[];
  recent_bad_examples: Array<{ prompt: string; note: string | null }>;
};

const LEVEL_LABEL: Record<string, string> = { error: "错误", warn: "警告", ok: "合格", unchecked: "未检" };
const LEVEL_CLASS: Record<string, string> = { error: "err", warn: "warn", ok: "ok", unchecked: "muted" };

export default function TeacherQualityDashboardPage() {
  const { user } = useAuth();
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) return;
    if (user.role !== "teacher" && user.role !== "admin") {
      setError("仅教师可访问");
      setLoading(false);
      return;
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  async function load() {
    if (!user?.token) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API}/api/teacher/quality-dashboard`, { headers: authHeaders(user.token) });
      if (res.ok) setData(await res.json());
      else setError(`加载失败 HTTP ${res.status}`);
    } catch {
      setError("网络错误，请稍后重试");
    } finally {
      setLoading(false);
    }
  }

  const t = data?.totals;
  const dist = data?.quality_distribution;
  const eff = data?.effectiveness;
  const distTotal = dist ? dist.error + dist.warn + dist.ok + dist.unchecked : 0;

  // 有效性解读：把冷冰冰的数字翻译成一句结论
  function effectivenessNote(): string {
    if (!eff) return "";
    if (eff.blind_spots_confirmed_bad > 0)
      return `教师已确认 ${eff.blind_spots_confirmed_bad} 道 AI 漏检的问题题——这些题干已回流为语义质检的 few-shot 反例，后续同类题更可能被自动标出。`;
    if (eff.blind_spots_open > 0)
      return `有 ${eff.blind_spots_open} 处质检盲区待你复核（AI 判合格但真实正确率异常低）。复核结论会反哺 AI，越用越准。`;
    if (eff.suspected_false_alarm > 0)
      return `有 ${eff.suspected_false_alarm} 道题被 AI 预警但真实正确率很高，可能是误报——出题时可放心采用。`;
    return "暂无明显盲区或误报，AI 质检与真实作答基本吻合。";
  }

  return (
    <div className="qd">
      <style>{CSS}</style>
      <div className="qd-inner">
        <header className="qd-head">
          <p className="qd-eyebrow">QUALITY · 命题质量看板</p>
          <h1 className="qd-title">命题质量看板</h1>
          <p className="qd-sub">跨作业聚合 AI 出题质检的分布与有效性，看清 AI 漏检、误报与高频问题——数据来自你已布置的作业。</p>
        </header>

        {loading && <p className="qd-empty">加载中…</p>}
        {error && <p className="qd-error">{error}</p>}

        {data && !loading && !error && (
          t && t.assignment_count === 0 ? (
            <div className="qd-empty-box">
              <p className="qd-empty-title">还没有可分析的作业</p>
              <p className="qd-empty-hint">先去<Link href="/teacher/assignments" className="qd-link">布置作业</Link>并让学生作答，这里会自动汇总命题质量画像。</p>
            </div>
          ) : (
            <>
              {/* 命题概览 */}
              <section className="qd-section">
                <h2 className="qd-h2">命题概览</h2>
                <div className="qd-metrics">
                  <div className="qd-metric"><b>{t?.assignment_count}</b><span>作业数</span></div>
                  <div className="qd-metric"><b>{t?.question_count}</b><span>题目总数</span></div>
                  <div className="qd-metric"><b>{t?.quality_checked_count}</b><span>已质检</span></div>
                  <div className="qd-metric"><b>{t?.semantic_checked_count}</b><span>含语义质检</span></div>
                </div>
              </section>

              {/* AI 质检有效性——核心 */}
              <section className="qd-section">
                <h2 className="qd-h2">AI 质检有效性</h2>
                <div className="qd-eff-grid">
                  <div className="qd-eff-card">
                    <b>{eff?.proactive_flagged}</b>
                    <span>主动预警</span>
                    <em>AI 判为 error/warn 的题</em>
                  </div>
                  <div className={`qd-eff-card${(eff?.suspected_false_alarm ?? 0) > 0 ? " amber" : ""}`}>
                    <b>{eff?.suspected_false_alarm}</b>
                    <span>疑似误报</span>
                    <em>预警但正确率≥{80}%</em>
                  </div>
                  <div className={`qd-eff-card${(eff?.blind_spots_open ?? 0) > 0 ? " danger" : ""}`}>
                    <b>{eff?.blind_spots_open}</b>
                    <span>待复核盲区</span>
                    <em>判合格但正确率异常低</em>
                  </div>
                  <div className="qd-eff-card">
                    <b>{eff?.blind_spots_confirmed_bad}</b>
                    <span>已确认漏检</span>
                    <em>教师判定题目有问题</em>
                  </div>
                </div>
                <p className="qd-note">{effectivenessNote()}</p>
                {(eff?.blind_spots_open ?? 0) > 0 && (
                  <Link href="/teacher/assignments" className="qd-cta">去复核盲区 →</Link>
                )}
              </section>

              {/* 质检分布 */}
              <section className="qd-section">
                <h2 className="qd-h2">质检结论分布</h2>
                {distTotal === 0 ? (
                  <p className="qd-empty compact">暂无带质检结论的题目。</p>
                ) : (
                  <>
                    <div className="qd-bar">
                      {(["error", "warn", "ok", "unchecked"] as const).map((k) =>
                        dist![k] > 0 ? (
                          <div
                            key={k}
                            className={`qd-bar-seg ${LEVEL_CLASS[k]}`}
                            style={{ width: `${(dist![k] / distTotal) * 100}%` }}
                            title={`${LEVEL_LABEL[k]} ${dist![k]}`}
                          />
                        ) : null
                      )}
                    </div>
                    <div className="qd-legend">
                      {(["error", "warn", "ok", "unchecked"] as const).map((k) => (
                        <span key={k} className="qd-legend-item">
                          <i className={`qd-dot ${LEVEL_CLASS[k]}`} />
                          {LEVEL_LABEL[k]} {dist![k]}
                        </span>
                      ))}
                    </div>
                  </>
                )}
              </section>

              {/* 高频问题类型 */}
              {data.top_issue_types.length > 0 && (
                <section className="qd-section">
                  <h2 className="qd-h2">高频问题类型</h2>
                  <ul className="qd-issues">
                    {data.top_issue_types.map((it, i) => (
                      <li key={i} className="qd-issue">
                        <span className="qd-issue-text">{it.issue}</span>
                        <span className="qd-issue-count">{it.count} 次</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {/* 最难题 Top */}
              {data.hardest_questions.length > 0 && (
                <section className="qd-section">
                  <h2 className="qd-h2">最难题 Top（真实正确率最低）</h2>
                  <div className="qd-hardest">
                    {data.hardest_questions.map((q) => (
                      <Link
                        key={`${q.assignment_id}-${q.question_index}`}
                        href="/teacher/assignments"
                        className="qd-hard-row"
                      >
                        <span className={`qd-acc ${q.accuracy < 40 ? "low" : q.accuracy < 60 ? "mid" : "ok"}`}>{q.accuracy}%</span>
                        <span className="qd-hard-main">
                          <span className="qd-hard-prompt">{q.prompt || `第 ${q.question_index + 1} 题`}</span>
                          <span className="qd-hard-meta">
                            {q.assignment_title} · {q.attempts} 人作答
                            {q.predicted_level && q.predicted_level !== "ok" && (
                              <em className={`qd-tag ${LEVEL_CLASS[q.predicted_level] || "muted"}`}>AI:{LEVEL_LABEL[q.predicted_level] || q.predicted_level}</em>
                            )}
                            {(q.predicted_level === null || q.predicted_level === "ok") && q.accuracy < 40 && (
                              <em className="qd-tag danger">盲区</em>
                            )}
                          </span>
                        </span>
                      </Link>
                    ))}
                  </div>
                </section>
              )}

              {/* 复核结论 + 近期反例 */}
              <section className="qd-section">
                <h2 className="qd-h2">教师复核结论</h2>
                <div className="qd-verdicts">
                  <span className="qd-verdict bad">题目有问题 {data.review_verdicts.bad_question}</span>
                  <span className="qd-verdict nm">学生没掌握 {data.review_verdicts.not_mastered}</span>
                </div>
                {data.recent_bad_examples.length > 0 && (
                  <div className="qd-examples">
                    <p className="qd-examples-title">近期回流的 few-shot 反例（已注入语义质检）</p>
                    {data.recent_bad_examples.map((ex, i) => (
                      <div key={i} className="qd-example">
                        <span className="qd-example-prompt">{ex.prompt}</span>
                        {ex.note && <span className="qd-example-note">备注：{ex.note}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </>
          )
        )}
      </div>
    </div>
  );
}

const CSS = `
.qd { min-height:100vh; color:var(--ink,#1a1612); }
.qd-inner { max-width:760px; margin:0 auto; padding:36px 22px 100px; }
.qd-eyebrow { font-size:10px; letter-spacing:.24em; color:var(--cinnabar,#b7422b); margin:0 0 6px; }
.qd-title { font-size:26px; font-weight:700; margin:0 0 6px; }
.qd-sub { font-size:13px; color:var(--muted,#7a7068); margin:0 0 22px; line-height:1.6; }
.qd-error { font-size:13px; color:#c0392b; margin:8px 0; }
.qd-empty { font-size:13px; color:var(--muted,#7a7068); padding:20px 0; }
.qd-empty.compact { padding:6px 0; }
.qd-empty-box { background:#fffaf3; border:1px solid #e5d4b8; border-radius:12px; padding:24px; text-align:center; }
.qd-empty-title { font-size:15px; font-weight:700; margin:0 0 6px; }
.qd-empty-hint { font-size:13px; color:var(--muted,#7a7068); margin:0; }
.qd-link { color:var(--cinnabar,#b7422b); font-weight:600; }
.qd-section { margin-bottom:26px; }
.qd-h2 { font-size:15px; font-weight:700; margin:0 0 12px; padding-bottom:6px; border-bottom:1px solid #e5e0d5; }
.qd-metrics { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
.qd-metric { background:#fff; border:1px solid #efe4d2; border-radius:10px; padding:14px 8px; display:flex; flex-direction:column; align-items:center; gap:3px; }
.qd-metric b { font-size:22px; font-weight:700; }
.qd-metric span { font-size:11px; color:var(--muted,#7a7068); }
.qd-eff-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
.qd-eff-card { background:#fff; border:1px solid #efe4d2; border-radius:10px; padding:14px 10px; display:flex; flex-direction:column; align-items:center; gap:3px; text-align:center; }
.qd-eff-card.amber { background:#fdf6e3; border-color:#efdca6; }
.qd-eff-card.danger { background:#fdf1ee; border-color:#f5c2bc; }
.qd-eff-card b { font-size:24px; font-weight:700; }
.qd-eff-card span { font-size:12px; font-weight:600; }
.qd-eff-card em { font-size:10px; color:var(--muted,#7a7068); font-style:normal; line-height:1.4; }
.qd-note { font-size:13px; line-height:1.65; color:var(--ink,#4a4038); background:#f8f4ef; border-radius:8px; padding:12px 14px; margin:14px 0 0; }
.qd-cta { display:inline-block; margin-top:12px; background:var(--cinnabar,#b7422b); color:#fff; border-radius:8px; padding:9px 18px; font-size:13px; font-weight:600; }
.qd-bar { display:flex; height:22px; border-radius:6px; overflow:hidden; border:1px solid #e5e0d5; }
.qd-bar-seg { height:100%; }
.qd-bar-seg.err, .qd-dot.err { background:#c0392b; }
.qd-bar-seg.warn, .qd-dot.warn { background:#e0a52b; }
.qd-bar-seg.ok, .qd-dot.ok { background:#2d6a4f; }
.qd-bar-seg.muted, .qd-dot.muted { background:#c8bfb2; }
.qd-legend { display:flex; flex-wrap:wrap; gap:14px; margin-top:10px; }
.qd-legend-item { font-size:12px; color:var(--muted,#7a7068); display:flex; align-items:center; gap:5px; }
.qd-dot { width:10px; height:10px; border-radius:3px; display:inline-block; }
.qd-issues { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:6px; }
.qd-issue { display:flex; justify-content:space-between; align-items:center; gap:12px; background:#fff; border:1px solid #efe4d2; border-radius:8px; padding:9px 13px; }
.qd-issue-text { font-size:13px; }
.qd-issue-count { font-size:11px; color:var(--cinnabar,#b7422b); font-weight:600; white-space:nowrap; }
.qd-hardest { display:flex; flex-direction:column; gap:8px; }
.qd-hard-row { display:flex; align-items:center; gap:12px; background:#fff; border:1px solid #efe4d2; border-radius:9px; padding:10px 13px; transition:border-color .15s, transform .1s; }
.qd-hard-row:hover { border-color:var(--cinnabar,#b7422b); transform:translateX(2px); }
.qd-acc { font-size:15px; font-weight:700; width:48px; flex:none; text-align:center; }
.qd-acc.low { color:#c0392b; }
.qd-acc.mid { color:#b0862b; }
.qd-acc.ok { color:#2d6a4f; }
.qd-hard-main { display:flex; flex-direction:column; gap:3px; min-width:0; }
.qd-hard-prompt { font-size:13px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.qd-hard-meta { font-size:11px; color:var(--muted,#7a7068); display:flex; align-items:center; gap:6px; }
.qd-tag { font-size:10px; font-weight:700; font-style:normal; border-radius:6px; padding:1px 6px; color:#fff; }
.qd-tag.err { background:#c0392b; }
.qd-tag.warn { background:#e0a52b; }
.qd-tag.danger { background:var(--cinnabar,#b7422b); }
.qd-tag.muted { background:#c8bfb2; }
.qd-verdicts { display:flex; gap:10px; }
.qd-verdict { font-size:13px; font-weight:600; border-radius:8px; padding:8px 14px; }
.qd-verdict.bad { background:#fdf1ee; color:var(--cinnabar,#b7422b); }
.qd-verdict.nm { background:#f0ebe0; color:var(--muted,#7a7068); }
.qd-examples { margin-top:14px; background:#fffaf3; border:1px solid #e5d4b8; border-radius:10px; padding:14px 16px; }
.qd-examples-title { font-size:12px; font-weight:700; color:var(--cinnabar,#b7422b); margin:0 0 10px; }
.qd-example { padding:7px 0; border-top:1px dashed #e5d4b8; }
.qd-example:first-of-type { border-top:none; }
.qd-example-prompt { font-size:13px; display:block; }
.qd-example-note { font-size:11px; color:var(--muted,#7a7068); }
@media (max-width:640px) {
  .qd-metrics, .qd-eff-grid { grid-template-columns:repeat(2,1fr); }
}
`;
