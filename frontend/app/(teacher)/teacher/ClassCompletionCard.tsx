"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type StudentRow = {
  student_id: string;
  assigned: number;
  submitted: number;
  pending: number;
  overdue: number;
  overdue_titles: string[];
};
type Overview = {
  date: string;
  summary: {
    student_count: number;
    assignment_count: number;
    students_with_overdue: number;
    students_all_done: number;
    overall_submission_rate: number;
  };
  students: StudentRow[];
};

/** 教师「作业完成情况 / 催办」：跨作业按学生聚合，掉队学生优先展示。 */
export default function ClassCompletionCard() {
  const { user } = useAuth();
  const [data, setData] = useState<Overview | null>(null);
  const [urging, setUrging] = useState(false);
  const [urgeMsg, setUrgeMsg] = useState("");
  const [urgeResult, setUrgeResult] = useState<string | null>(null);

  useEffect(() => {
    if (!user?.token) return;
    fetch(`${API}/api/teacher/completion-overview`, { headers: authHeaders(user.token) })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setData(d))
      .catch(() => {});
  }, [user?.token]);

  async function urgeAll(studentIds: string[]) {
    if (!user?.token || urging || studentIds.length === 0) return;
    setUrging(true); setUrgeResult(null);
    try {
      const res = await fetch(`${API}/api/teacher/urge-students`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(user.token) },
        body: JSON.stringify({ student_ids: studentIds, message: urgeMsg.trim() }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      setUrgeResult(`已向 ${d.sent} 名学生发送催办通知 ✓`);
      setTimeout(() => setUrgeResult(null), 4000);
    } catch {
      setUrgeResult("催办失败，请重试");
    } finally {
      setUrging(false);
    }
  }

  if (!data || data.summary.assignment_count === 0) return null;

  const { summary, students } = data;
  const behind = students.filter((s) => s.pending > 0);

  return (
    <section className="cc-card" aria-label="作业完成情况">
      <style>{CSS}</style>
      <div className="cc-head">
        <div>
          <p className="cc-eyebrow">COMPLETION · 作业完成情况</p>
          <h2 className="cc-title">谁还没交？</h2>
        </div>
        <Link href="/teacher/assignments" className="cc-link">去布置作业页 →</Link>
      </div>

      <div className="cc-metrics">
        <div className="cc-metric"><b>{summary.overall_submission_rate}%</b><span>总体提交率</span></div>
        <div className={`cc-metric${summary.students_with_overdue > 0 ? " danger" : ""}`}><b>{summary.students_with_overdue}</b><span>有逾期的学生</span></div>
        <div className="cc-metric"><b>{summary.students_all_done}</b><span>已全部完成</span></div>
        <div className="cc-metric"><b>{summary.assignment_count}</b><span>作业数</span></div>
      </div>

      {behind.length === 0 ? (
        <p className="cc-clear">✓ 所有学生都已交齐当前作业。</p>
      ) : (
        <>
          <ul className="cc-list">
            {behind.slice(0, 8).map((s) => (
              <li key={s.student_id}>
                <Link href={`/teacher/students/${s.student_id}`} className="cc-row">
                  <span className="cc-name">{s.student_id}</span>
                  <span className="cc-stats">
                    {s.overdue > 0 && <span className="cc-tag overdue">逾期 {s.overdue}</span>}
                    <span className="cc-tag pending">欠交 {s.pending}/{s.assigned}</span>
                  </span>
                  {s.overdue_titles.length > 0 && (
                    <span className="cc-titles">逾期：{s.overdue_titles.slice(0, 2).join("、")}{s.overdue_titles.length > 2 ? " 等" : ""}</span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
          {/* 催办区域 */}
          <div className="cc-urge-box">
            <input
              className="cc-urge-input"
              placeholder="催办消息（留空用默认文案）"
              value={urgeMsg}
              onChange={(e) => setUrgeMsg(e.target.value)}
              maxLength={100}
            />
            <button
              className="cc-urge-btn"
              disabled={urging}
              onClick={() => urgeAll(behind.map((s) => s.student_id))}
            >
              {urging ? "发送中…" : `一键催办 ${behind.length} 人`}
            </button>
          </div>
          {urgeResult && <p className="cc-urge-result">{urgeResult}</p>}
        </>
      )}
    </section>
  );
}

const CSS = `
.cc-card { background:#fff; border:1px solid #e5e0d5; border-radius:14px; padding:20px 22px; margin:0 0 24px; }
.cc-head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:14px; }
.cc-eyebrow { font-size:10px; letter-spacing:.24em; color:var(--cinnabar,#b7422b); margin:0 0 4px; }
.cc-title { font-size:18px; font-weight:700; margin:0; }
.cc-link { font-size:12px; color:var(--cinnabar,#b7422b); font-weight:600; white-space:nowrap; }
.cc-metrics { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:14px; }
.cc-metric { background:#fdfbf7; border:1px solid #eee6d8; border-radius:10px; padding:12px 8px; display:flex; flex-direction:column; align-items:center; gap:3px; }
.cc-metric.danger { background:#fdf1ee; border-color:#f5c2bc; }
.cc-metric b { font-size:20px; font-weight:700; }
.cc-metric span { font-size:11px; color:var(--muted,#7a7068); text-align:center; }
.cc-clear { font-size:13px; color:var(--jade,#2d6a4f); background:#f0faf5; border-radius:8px; padding:12px 14px; margin:0; }
.cc-list { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:8px; }
.cc-row { display:flex; align-items:center; flex-wrap:wrap; gap:8px 12px; padding:10px 14px; border:1px solid #eee6d8;
  border-radius:10px; background:#fdfbf7; transition:border-color .15s, transform .1s; }
.cc-row:hover { border-color:var(--cinnabar,#b7422b); transform:translateX(2px); }
.cc-name { font-size:14px; font-weight:600; }
.cc-stats { display:flex; gap:6px; margin-left:auto; }
.cc-tag { font-size:11px; font-weight:700; border-radius:8px; padding:2px 8px; white-space:nowrap; }
.cc-tag.overdue { background:#fdecea; color:#c0392b; }
.cc-tag.pending { background:#fdf6e3; color:#b0862b; }
.cc-titles { flex-basis:100%; font-size:11px; color:var(--muted,#7a7068); }
/* 催办区域 */
.cc-urge-box { display:flex; gap:8px; margin-top:12px; flex-wrap:wrap; }
.cc-urge-input { flex:1; min-width:140px; border:1px solid #ddd7cc; border-radius:8px; padding:7px 10px; font-size:12px; background:#fdfbf7; color:var(--ink,#1a1612); }
.cc-urge-input:focus { outline:none; border-color:var(--cinnabar,#b7422b); }
.cc-urge-btn { background:var(--cinnabar,#b7422b); color:#fff; border:none; border-radius:8px; padding:8px 16px; font-size:12px; font-weight:700; cursor:pointer; white-space:nowrap; }
.cc-urge-btn:hover:not(:disabled) { background:#962318; }
.cc-urge-btn:disabled { opacity:.6; cursor:not-allowed; }
.cc-urge-result { font-size:12px; margin:8px 0 0; color:var(--jade,#2d6a4f); }
@media (max-width:640px) { .cc-metrics { grid-template-columns:repeat(2,1fr); } }
`;
