"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders, clearAuth } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
type Student = { actor_id: string; display_name: string | null };
type ClassAnalytics = {
  total_students: number;
  top_weak_topics: [string, number][];
};

const AVATARS = ["青", "史", "文", "学", "知", "道", "明", "智"];

export default function TeacherDashboard() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const [students, setStudents] = useState<Student[]>([]);
  const [analytics, setAnalytics] = useState<ClassAnalytics | null>(null);
  const [pendingReviews, setPendingReviews] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ready) return;
    if (user?.role === "student") { router.replace("/"); return; }
    if (!user) { router.replace("/"); return; }
    const headers = authHeaders(user.token);
    Promise.all([
      fetch(`${API}/api/teacher/students`, { headers }),
      fetch(`${API}/api/teacher/class-analytics`, { headers }),
      fetch(`${API}/api/teacher/homework-reviews?decision=pending&limit=50`, { headers }),
    ])
      .then(async ([studentsResponse, analyticsResponse, reviewsResponse]) => {
        const data = await studentsResponse.json().catch(() => []);
        if (Array.isArray(data)) setStudents(data);
        else if (Array.isArray(data.students)) setStudents(data.students);
        else setStudents([]);

        if (analyticsResponse.ok) {
          const analyticsData = await analyticsResponse.json().catch(() => null);
          if (analyticsData) setAnalytics(analyticsData);
        }

        if (reviewsResponse.ok) {
          const reviewsData = await reviewsResponse.json().catch(() => null);
          if (reviewsData) setPendingReviews(reviewsData.total ?? 0);
        }
      })
      .finally(() => setLoading(false));
  }, [user, ready, router]);

  if (!ready) return null;

  const topWeakTopic = analytics?.top_weak_topics?.[0];
  const weakShare = topWeakTopic && analytics?.total_students
    ? Math.round((topWeakTopic[1] / Math.max(analytics.total_students, 1)) * 100)
    : null;

  return (
    <div className="teacher-shell">
      <div className="teacher-deco-bar" />

      <div className="teacher-main">
        <div className="teacher-page-header">
          <div>
            <p className="teacher-eyebrow">Teacher Dashboard · 教务管理</p>
            <h1 className="teacher-page-title">班级<span>学情</span>总览</h1>
          </div>
          {!loading && (
            <div style={{ display: "flex", gap: 12 }}>
              <div className="teacher-count-badge">
                <div>
                  <div className="teacher-count-num">{students.length}</div>
                  <div style={{ fontSize: 11, letterSpacing: 2, marginTop: 2 }}>名学生</div>
                </div>
              </div>
              {pendingReviews !== null && pendingReviews > 0 && (
                <a href="/teacher/grading?tab=homework" className="teacher-count-badge" style={{ background: "var(--cinnabar, #c94a38)", textDecoration: "none" }}>
                  <div>
                    <div className="teacher-count-num">{pendingReviews}</div>
                    <div style={{ fontSize: 11, letterSpacing: 2, marginTop: 2 }}>待审核</div>
                  </div>
                </a>
              )}
            </div>
          )}
        </div>

        <div className="teacher-nav">
          <a href="/teacher/class-analytics" className="teacher-nav-link">班级学情分析</a>
          <a href="/teacher/materials" className="teacher-nav-link">学生资料库</a>
          <a href="/teacher/grading" className="teacher-nav-link">作业审核</a>
        </div>

        {topWeakTopic && (
          <a href="/teacher/class-analytics" className="teacher-focus-card">
            <span className="teacher-focus-kicker">本轮讲评重点</span>
            <strong>{topWeakTopic[0]}</strong>
            <span>
              {topWeakTopic[1]} 名学生存在薄弱记录
              {weakShare != null ? ` · ${weakShare}%` : ""}，点击查看讲评建议。
            </span>
          </a>
        )}

        {loading ? (
          <div className="teacher-loading">
            <div className="teacher-spinner" />
            <span>正在加载学生数据…</span>
          </div>
        ) : (
          <div className="teacher-grid">
            {students.length === 0 ? (
              <div className="teacher-empty">暂无学生数据</div>
            ) : students.map((s, i) => (
              <a
                key={s.actor_id}
                href={`/teacher/students/${s.actor_id}`}
                className="teacher-card"
                style={{ animationDelay: `${i * 50}ms` }}
              >
                <div className="teacher-avatar">
                  {AVATARS[i % AVATARS.length]}
                </div>
                <div className="teacher-card-info">
                  <div className="teacher-card-name">{s.display_name || s.actor_id}</div>
                  <div className="teacher-card-id">{s.actor_id}</div>
                </div>
                <span className="teacher-card-arrow">›</span>
              </a>
            ))}
          </div>
        )}
      </div>

      <style jsx>{`
        .teacher-nav {
          display: flex;
          gap: 12px;
          margin-bottom: 24px;
          padding-bottom: 16px;
          border-bottom: 1px solid var(--border, #e5e7eb);
        }

        .teacher-nav-link {
          padding: 8px 16px;
          border: 1px solid var(--border, #e5e7eb);
          background: var(--bg, #ffffff);
          border-radius: 6px;
          text-decoration: none;
          color: var(--text, #1f2937);
          font-size: 0.9rem;
          transition: all 0.2s;
        }

        .teacher-nav-link:hover {
          border-color: var(--accent, #4b9560);
          color: var(--accent, #4b9560);
        }

        .teacher-focus-card {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          margin-bottom: 24px;
          padding: 18px 20px;
          border: 1px solid rgba(75, 149, 96, 0.24);
          border-radius: 14px;
          background: linear-gradient(135deg, rgba(75, 149, 96, 0.1), rgba(217, 119, 6, 0.08));
          color: var(--text, #1f2937);
          text-decoration: none;
          transition: transform 0.2s, border-color 0.2s;
        }

        .teacher-focus-card:hover {
          transform: translateY(-1px);
          border-color: rgba(75, 149, 96, 0.45);
        }

        .teacher-focus-card strong {
          font-size: 1.2rem;
        }

        .teacher-focus-card span:last-child {
          color: var(--text-muted, #6b7280);
          font-size: 0.9rem;
        }

        .teacher-focus-kicker {
          font-size: 0.72rem;
          font-weight: 700;
          letter-spacing: 0.12em;
          color: var(--accent, #4b9560);
        }
      `}</style>
    </div>
  );
}
