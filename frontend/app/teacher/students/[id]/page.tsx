"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Profile = {
  student_id: string; grade: string | null;
  recent_topics: string[]; weak_topics: string[]; strong_topics: string[];
  quiz_stats: { attempts?: number; average_score?: number };
  game_stats: { attempts?: number; average_score?: number };
};
type Event = { id: string; feature: string; event_type: string; topic: string | null; score: number | null; created_at: string };

const FEATURE_LABELS: Record<string, string> = {
  learning_assistant: "学习助手",
  history_character: "历史人物对话",
  quiz_practice: "智能练习",
  history_games: "历史游戏",
  textbook_learning: "教材同步",
  history_debate: "历史辩论",
  material_upload: "资料学习",
};
const EVENT_LABELS: Record<string, string> = {
  completed: "已完成",
  started: "已开始",
  tool_result: "工具调用",
  quiz_correct: "答题正确",
  quiz_wrong: "答题错误",
};

function label(map: Record<string, string>, key: string) {
  return map[key] || key;
}

export default function TeacherStudentDetail() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const params = useParams();
  const studentId = params.id as string;
  const [profile, setProfile] = useState<Profile | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!ready) return;
    if (!user) { router.replace("/login"); return; }
    if (user.role === "student") { router.replace("/"); return; }
    const h = authHeaders(user.token);
    Promise.all([
      fetch(`${API}/api/teacher/students/${studentId}/profile`, { headers: h }),
      fetch(`${API}/api/teacher/students/${studentId}/events`, { headers: h }),
    ]).then(async ([pr, er]) => {
      if (!pr.ok) { setErr(`无法加载学生数据 (${pr.status})`); return; }
      const [p, e] = await Promise.all([pr.json(), er.ok ? er.json() : []]);
      setProfile(p); setEvents(Array.isArray(e) ? e : []);
    }).catch(() => setErr("网络错误，请重试"));
  }, [user, ready, studentId, router]);

  if (!ready || (!profile && !err)) return (
    <main className="workbench-page" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: 300 }}>
      <span style={{ color: "var(--muted)" }}>加载中…</span>
    </main>
  );

  if (err) return (
    <main className="workbench-page" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, minHeight: 300 }}>
      <p style={{ color: "var(--cinnabar)" }}>{err}</p>
      <Link href="/teacher" style={{ color: "var(--jade)" }}>← 返回班级总览</Link>
    </main>
  );

  const quizPct = profile!.quiz_stats.average_score != null ? Math.round(profile!.quiz_stats.average_score * 100) : null;
  const gamePct = profile!.game_stats.average_score != null ? Math.round(profile!.game_stats.average_score * 100) : null;

  return (
    <main className="workbench-page">
      <nav style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--muted)", marginBottom: 28 }}>
        <Link href="/teacher" style={{ color: "var(--jade)" }}>← 班级总览</Link>
        <span>/</span>
        <span>{profile!.student_id}</span>
      </nav>

      <section className="workbench-hero" style={{ marginBottom: 32 }}>
        <div className="workbench-hero-copy">
          <p className="workbench-kicker">学情档案</p>
          <h1>{profile!.student_id}</h1>
          {profile!.grade && <div className="student-hero-meta"><span>{profile!.grade}</span></div>}
        </div>
        <aside className="workbench-next-card" style={{ minHeight: "auto" }}>
          <span>成绩概览</span>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 8 }}>
            {[
              { label: "测验", pct: quizPct, attempts: profile!.quiz_stats.attempts },
              { label: "游戏", pct: gamePct, attempts: profile!.game_stats.attempts },
            ].map(({ label: l, pct, attempts }) => (
              <div key={l} style={{ textAlign: "center" }}>
                <strong style={{ fontSize: 28, color: "var(--cinnabar)" }}>{pct != null ? `${pct}%` : "—"}</strong>
                <p style={{ fontSize: 12, color: "var(--muted)", margin: "2px 0 0" }}>{l} · {attempts ?? 0} 次</p>
              </div>
            ))}
          </div>
        </aside>
      </section>

      <section style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 32 }}>
        <div className="workbench-next-card" style={{ minHeight: "auto" }}>
          <span style={{ color: "var(--cinnabar)" }}>薄弱知识点</span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
            {profile!.weak_topics.length === 0
              ? <span style={{ color: "var(--muted)", fontSize: 13 }}>暂无薄弱项</span>
              : profile!.weak_topics.map(t => <span key={t} className="workbench-tag" style={{ background: "rgba(183,66,43,0.08)", color: "var(--cinnabar-dark)" }}>{t}</span>)}
          </div>
        </div>
        <div className="workbench-next-card" style={{ minHeight: "auto" }}>
          <span style={{ color: "var(--jade)" }}>掌握较好</span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
            {profile!.strong_topics.length === 0
              ? <span style={{ color: "var(--muted)", fontSize: 13 }}>暂无记录</span>
              : profile!.strong_topics.map(t => <span key={t} className="workbench-tag" style={{ background: "var(--jade-soft)", color: "var(--jade-dark)" }}>{t}</span>)}
          </div>
        </div>
      </section>

      <section>
        <div className="workbench-section-heading" style={{ marginBottom: 16 }}>
          <p className="workbench-kicker">近期学习记录</p>
        </div>
        {events.length === 0 ? (
          <p style={{ color: "var(--muted)", fontSize: 14 }}>暂无学习记录</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["功能模块", "事件", "知识点", "得分", "时间"].map(h => (
                  <th key={h} style={{ textAlign: "left", padding: "8px 12px", color: "var(--muted)", fontWeight: 500 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events.map(e => {
                const s = e.score != null ? Math.round(e.score * 100) : null;
                return (
                  <tr key={e.id} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "10px 12px" }}>{label(FEATURE_LABELS, e.feature)}</td>
                    <td style={{ padding: "10px 12px", color: "var(--muted)" }}>{label(EVENT_LABELS, e.event_type)}</td>
                    <td style={{ padding: "10px 12px" }}>{e.topic || "—"}</td>
                    <td style={{ padding: "10px 12px" }}>
                      {s != null ? (
                        <span style={{ color: s >= 80 ? "var(--jade)" : s >= 60 ? "var(--gold)" : "var(--cinnabar)", fontWeight: 600 }}>{s}%</span>
                      ) : "—"}
                    </td>
                    <td style={{ padding: "10px 12px", color: "var(--muted)" }}>{e.created_at.slice(0, 16).replace("T", " ")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
