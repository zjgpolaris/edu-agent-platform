"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
type Student = { actor_id: string; display_name: string | null };
type ReviewStats = { total: number; approved: number; edited: number; rejected: number };

const MARKS = ["青", "史", "文", "学", "知", "道", "明", "智"];

export default function TeacherPage() {
  const { user } = useAuth();
  const displayName = user?.displayName || user?.actorId || "老师";
  const [students, setStudents] = useState<Student[] | null>(null);
  const [reviewStats, setReviewStats] = useState<ReviewStats | null>(null);

  useEffect(() => {
    if (!user?.token) return;
    const h = authHeaders(user.token);
    fetch(`${API}/api/teacher/students`, { headers: h })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d) setStudents(Array.isArray(d) ? d : (d.students ?? [])); })
      .catch(() => {});
    fetch(`${API}/api/chinese/essay/review-stats`, { headers: h })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d) setReviewStats(d); })
      .catch(() => {});
  }, [user?.token]);

  const studentCount = students !== null ? students.length : null;
  function fmt(v: number | null) { return v !== null ? String(v) : "—"; }

  return (
    <main className="workbench-page teacher-workbench">
      <section className="workbench-hero">
        <div className="workbench-hero-copy">
          <p className="workbench-kicker">教师协同工作台</p>
          <h1>{displayName}，先看班级状态还是批改任务？</h1>
          <p>教师端聚合班级学情、作文批改、作业批改和资料生成。AI 可以先完成结构化整理，关键评分和教学决策仍由教师确认。</p>
          <div className="workbench-actions">
            <Link href="/teacher/grading?tab=essay" className="workbench-primary-link">进入作文批改</Link>
            <Link href="/teacher/grading?tab=homework" className="workbench-secondary-link">拍照作业批改</Link>
          </div>
        </div>
        <aside className="workbench-next-card teacher-next-card" aria-label="批改摘要">
          <span>批改统计</span>
          <h2>作文批改总量</h2>
          <div className="teacher-review-list">
            <div className="teacher-review-item warm">
              <span>累计批改</span>
              <strong>{fmt(reviewStats?.total ?? null)} 篇</strong>
            </div>
            <div className="teacher-review-item jade">
              <span>已通过</span>
              <strong>{fmt(reviewStats?.approved ?? null)} 篇</strong>
            </div>
            <div className="teacher-review-item gold">
              <span>教师修改</span>
              <strong>{fmt(reviewStats ? reviewStats.edited + reviewStats.rejected : null)} 篇</strong>
            </div>
          </div>
        </aside>
      </section>

      <section className="workbench-overview-grid" aria-label="班级概览">
        <div className="workbench-metric"><strong>{fmt(studentCount)}</strong><span>班级学生</span></div>
        <div className="workbench-metric"><strong>{fmt(reviewStats?.total ?? null)}</strong><span>累计批改</span></div>
        <div className="workbench-metric"><strong>{fmt(reviewStats?.approved ?? null)}</strong><span>已通过</span></div>
        <div className="workbench-metric"><strong>{fmt(reviewStats ? reviewStats.edited + reviewStats.rejected : null)}</strong><span>教师修改/驳回</span></div>
      </section>

      <section className="workbench-main-grid teacher-main-grid" style={{ display: "block" }}>
        <div className="workbench-section-heading" style={{ marginBottom: 20 }}>
          <p className="workbench-kicker">学生学情</p>
          <h2>班级成员 {studentCount !== null ? `（${studentCount} 人）` : ""}</h2>
          <p>点击学生卡片查看个人学习轨迹、薄弱点和测验记录。</p>
        </div>

        {students === null ? (
          <p style={{ color: "var(--muted)", fontSize: 14 }}>加载中…</p>
        ) : students.length === 0 ? (
          <p style={{ color: "var(--muted)", fontSize: 14 }}>暂无学生数据</p>
        ) : (
          <div className="workbench-module-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))" }}>
            {students.map((s, i) => (
              <Link
                key={s.actor_id}
                href={`/teacher/students/${s.actor_id}`}
                className="workbench-module-card"
                style={{ flexDirection: "column", gap: 8, padding: "18px 20px" }}
              >
                <div style={{ width: 44, height: 44, borderRadius: "50%", background: "var(--jade-soft)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, color: "var(--jade-dark)", fontWeight: 700 }}>
                  {MARKS[i % MARKS.length]}
                </div>
                <div>
                  <strong style={{ fontSize: 15 }}>{s.display_name || s.actor_id}</strong>
                  <p style={{ margin: "2px 0 0", fontSize: 12, color: "var(--muted)" }}>{s.actor_id}</p>
                </div>
                <span style={{ fontSize: 12, color: "var(--jade)", marginTop: "auto" }}>查看学情 →</span>
              </Link>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
