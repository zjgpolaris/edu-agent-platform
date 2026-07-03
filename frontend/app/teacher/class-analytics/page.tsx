"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type ClassAnalytics = {
  total_students: number;
  active_students: number;
  average_quiz_score: number | null;
  average_game_score: number | null;
  weak_topics_distribution: Record<string, number>;
  strong_topics_distribution: Record<string, number>;
  top_weak_topics: [string, number][];
  activity_by_day: Record<string, number>;
};

type TeachingSuggestions = {
  suggestions: string[];
  activities: string[];
  key_topics: string[];
  homework_suggestions: string[];
};

type ClassMasteryTag = {
  tag: string;
  student_count: number;
  avg_wrong: number;
  avg_strength: number;  // 0-1
};

type ClassMasteryHeatmap = {
  tags: ClassMasteryTag[];
  total_students: number;
  total_tags: number;
};

export default function TeacherClassAnalyticsPage() {
  const { user } = useAuth();
  const [analytics, setAnalytics] = useState<ClassAnalytics | null>(null);
  const [suggestions, setSuggestions] = useState<TeachingSuggestions | null>(null);
  const [classHeatmap, setClassHeatmap] = useState<ClassMasteryHeatmap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (user?.role !== "teacher" && user?.role !== "admin") {
      setError("仅教师可访问此页面");
      setLoading(false);
      return;
    }
    fetchAnalytics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  async function fetchAnalytics() {
    if (!user?.token) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const [analyticsRes, heatmapRes] = await Promise.all([
        fetch(`${API}/api/teacher/class-analytics`, { headers: authHeaders(user.token) }),
        fetch(`${API}/api/teacher/class-mastery-heatmap`, { headers: authHeaders(user.token) }),
      ]);
      if (!analyticsRes.ok) throw new Error("获取班级学情失败");
      const data = await analyticsRes.json();
      setAnalytics(data);
      if (heatmapRes.ok) setClassHeatmap(await heatmapRes.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "获取班级学情失败");
    } finally {
      setLoading(false);
    }
  }

  async function generateSuggestions() {
    if (!user?.token) return;
    setGenerating(true);
    try {
      const response = await fetch(`${API}/api/teacher/teaching-suggestions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(user.token),
        },
        body: JSON.stringify({ focus: "weak_topics" }),
      });
      if (!response.ok) throw new Error("生成教学建议失败");
      const data = await response.json();
      setSuggestions(data);
    } catch (err) {
      alert(err instanceof Error ? err.message : "生成教学建议失败");
    } finally {
      setGenerating(false);
    }
  }

  function copyOutline() {
    if (!suggestions) return;
    const lines = [
      "【教学建议】",
      ...suggestions.suggestions.map((s) => `• ${s}`),
      "",
      "【课堂活动】",
      ...suggestions.activities.map((a) => `• ${a}`),
      "",
      "【重点知识点】",
      suggestions.key_topics.join("、"),
      "",
      "【作业建议】",
      ...suggestions.homework_suggestions.map((h) => `• ${h}`),
    ];
    void navigator.clipboard.writeText(lines.join("\n")).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  if (loading) {
    return (
      <main className="academy-shell">
        <section className="panel">
          <div className="panel-heading-row">
            <div>
              <p className="section-kicker">教师工作台</p>
              <h2>班级学情分析</h2>
            </div>
          </div>
          <p className="empty-hint">加载中...</p>
        </section>
      </main>
    );
  }

  if (error) {
    return (
      <main className="academy-shell">
        <section className="panel">
          <div className="panel-heading-row">
            <div>
              <p className="section-kicker">教师工作台</p>
              <h2>班级学情分析</h2>
            </div>
          </div>
          <div className="error-card"><p>{error}</p></div>
        </section>
      </main>
    );
  }

  const quizPct = analytics?.average_quiz_score != null
    ? Math.round(analytics.average_quiz_score * 100)
    : null;
  const gamePct = analytics?.average_game_score != null
    ? Math.round(analytics.average_game_score * 100)
    : null;
  const topWeakTopic = analytics?.top_weak_topics?.[0];
  const weakStudentShare = topWeakTopic && analytics?.total_students
    ? Math.round((topWeakTopic[1] / Math.max(analytics.total_students, 1)) * 100)
    : null;

  return (
    <main className="academy-shell">
      <section className="panel">
        <div className="panel-heading-row">
          <div>
            <p className="section-kicker">教师工作台</p>
            <h2>班级学情分析</h2>
          </div>
          <Link className="secondary-link" href="/teacher">返回班级总览</Link>
        </div>

        {topWeakTopic && (
          <div className="teaching-focus-card">
            <div>
              <p className="section-kicker">CLOSURE FOCUS</p>
              <h3>本轮讲评重点：{topWeakTopic[0]}</h3>
              <p>
                {topWeakTopic[1]} 名学生在该知识点上出现薄弱记录
                {weakStudentShare != null ? `，约占全班 ${weakStudentShare}%` : ""}。建议优先结合错题本讲评并布置同类巩固练习。
              </p>
            </div>
            <button className="primary" onClick={generateSuggestions} disabled={generating}>
              {generating ? "生成中..." : "生成讲评建议"}
            </button>
          </div>
        )}

        <div className="stats-grid">
          <div className="stat-card">
            <span className="stat-label">学生总数</span>
            <strong className="stat-value">{analytics?.total_students}</strong>
          </div>
          <div className="stat-card">
            <span className="stat-label">活跃学生（近7天）</span>
            <strong className="stat-value">{analytics?.active_students}</strong>
          </div>
          <div className="stat-card">
            <span className="stat-label">平均测验分</span>
            <strong className="stat-value">{quizPct != null ? `${quizPct}%` : "—"}</strong>
          </div>
          <div className="stat-card">
            <span className="stat-label">平均游戏分</span>
            <strong className="stat-value">{gamePct != null ? `${gamePct}%` : "—"}</strong>
          </div>
        </div>

        <div className="analytics-section">
          <div className="panel-heading-row">
            <div>
              <p className="section-kicker">WEAK POINTS</p>
              <h3>薄弱点分布</h3>
            </div>
          </div>
          {analytics?.top_weak_topics.length === 0 ? (
            <p className="empty-hint">暂无薄弱点数据</p>
          ) : (
            <div className="weak-point-list">
              {analytics!.top_weak_topics.map(([topic, count], index) => {
                const share = analytics!.total_students > 0 ? Math.round((count / analytics!.total_students) * 100) : 0;
                return (
                  <div key={topic} className="weak-point-item" style={{ animationDelay: `${index * 50}ms` }}>
                    <span className="weak-point-rank">{index + 1}</span>
                    <span className="weak-point-name">{topic}</span>
                    <span className="weak-point-bar" aria-hidden="true"><span style={{ width: `${Math.max(8, share)}%` }} /></span>
                    <span className="weak-point-count">{count} 人 · {share}%</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 班级知识点掌握度热力图 */}
        {classHeatmap && classHeatmap.tags.length > 0 && (
          <div className="analytics-section">
            <div className="panel-heading-row">
              <div>
                <p className="section-kicker">MASTERY HEATMAP</p>
                <h3>班级知识点掌握度热力图</h3>
              </div>
              <span style={{ fontSize: "0.78rem", color: "var(--text-muted, #6b7280)" }}>
                {classHeatmap.total_tags} 个知识点 · {classHeatmap.total_students} 名学生有记录
              </span>
            </div>
            <p style={{ fontSize: "0.78rem", color: "var(--text-muted, #6b7280)", margin: "0 0 12px" }}>
              颜色深浅反映班级平均掌握强度，红色=普遍薄弱，绿色=普遍掌握。点击知识点可在教学建议中重点关注。
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
              {classHeatmap.tags.slice(0, 30).map((item) => {
                const s = item.avg_strength;
                const bg = s >= 0.7 ? "#d1fae5" : s >= 0.4 ? "#fef3c7" : "#fee2e2";
                const fg = s >= 0.7 ? "#065f46" : s >= 0.4 ? "#92400e" : "#991b1b";
                const share = classHeatmap.total_students > 0
                  ? Math.round((item.student_count / classHeatmap.total_students) * 100)
                  : 0;
                return (
                  <div
                    key={item.tag}
                    title={`${item.tag}｜${item.student_count} 人薄弱（${share}%）｜平均出错 ${item.avg_wrong} 次`}
                    style={{
                      display: "inline-flex", flexDirection: "column", alignItems: "center",
                      gap: "3px", padding: "8px 14px", borderRadius: "8px",
                      background: bg, color: fg,
                      fontSize: "0.82rem", fontWeight: 600,
                      border: `1px solid ${fg}22`, cursor: "default",
                    }}
                  >
                    <span>{item.tag}</span>
                    <span style={{ fontSize: "0.65rem", opacity: 0.75 }}>{item.student_count}人 · {share}%</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="analytics-section">
          <div className="panel-heading-row">
            <div>
              <p className="section-kicker">STRONG POINTS</p>
              <h3>优势点分布</h3>
            </div>
          </div>
          {analytics?.strong_topics_distribution && Object.keys(analytics.strong_topics_distribution).length === 0 ? (
            <p className="empty-hint">暂无优势点数据</p>
          ) : (
            <div className="strong-point-cloud">
              {analytics?.strong_topics_distribution && Object.entries(analytics.strong_topics_distribution)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 10)
                .map(([topic, count]) => (
                  <span key={topic} className="strong-point-tag" style={{ fontSize: `${Math.max(12, Math.min(18, 12 + count))}px` }}>
                    {topic}
                  </span>
                ))}
            </div>
          )}
        </div>

        <div className="analytics-section">
          <div className="panel-heading-row">
            <div>
              <p className="section-kicker">TEACHING SUGGESTIONS</p>
              <h3>教学建议</h3>
            </div>
            <button
              className="secondary"
              onClick={generateSuggestions}
              disabled={generating}
            >
              {generating ? "生成中..." : "生成教学建议"}
            </button>
          </div>
          {!suggestions && (
            <p className="empty-hint">点击上方按钮生成基于班级学情的教学建议</p>
          )}
          {suggestions && (
            <div className="suggestions-content">
              <button type="button" className="copy-outline-btn" onClick={copyOutline}>
                {copied ? "✓ 已复制" : "复制讲评大纲"}
              </button>
              <div className="suggestion-block">
                <h4>教学建议</h4>
                <ul>
                  {suggestions.suggestions.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </div>
              <div className="suggestion-block">
                <h4>课堂活动</h4>
                <ul>
                  {suggestions.activities.map((a, i) => <li key={i}>{a}</li>)}
                </ul>
              </div>
              <div className="suggestion-block">
                <h4>重点知识点</h4>
                <div className="topic-tags">
                  {suggestions.key_topics.map((t, i) => <span key={i} className="topic-tag">{t}</span>)}
                </div>
              </div>
              <div className="suggestion-block">
                <h4>作业建议</h4>
                <ul>
                  {suggestions.homework_suggestions.map((h, i) => <li key={i}>{h}</li>)}
                </ul>
              </div>
            </div>
          )}
        </div>
      </section>

      <style jsx>{`
        .teaching-focus-card {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 20px;
          padding: 20px;
          margin-bottom: 24px;
          border-radius: 12px;
          border: 1px solid rgba(75, 149, 96, 0.24);
          background: linear-gradient(135deg, rgba(75, 149, 96, 0.1), rgba(217, 119, 6, 0.08));
        }

        .teaching-focus-card h3 {
          margin: 4px 0 8px;
          font-size: 1.25rem;
        }

        .teaching-focus-card p {
          margin: 0;
          color: var(--text-muted, #6b7280);
          line-height: 1.6;
        }

        .stats-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 16px;
          margin-bottom: 32px;
        }

        .stat-card {
          padding: 20px;
          background: var(--bg-muted, #f3f4f6);
          border-radius: 8px;
          text-align: center;
        }

        .stat-label {
          display: block;
          font-size: 0.85rem;
          color: var(--text-muted, #6b7280);
          margin-bottom: 8px;
        }

        .stat-value {
          display: block;
          font-size: 2rem;
          color: var(--accent, #4b9560);
        }

        .analytics-section {
          margin-bottom: 32px;
          padding: 20px;
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 8px;
        }

        .weak-point-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .weak-point-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 16px;
          background: var(--bg, #ffffff);
          border-radius: 6px;
          border: 1px solid var(--border, #e5e7eb);
        }

        .weak-point-rank {
          width: 28px;
          height: 28px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--danger-bg, #fee2e2);
          color: var(--danger-text, #991b1b);
          border-radius: 50%;
          font-size: 0.85rem;
          font-weight: 600;
        }

        .weak-point-name {
          min-width: 120px;
          flex: 1;
          font-weight: 500;
        }

        .weak-point-bar {
          position: relative;
          flex: 1;
          height: 8px;
          overflow: hidden;
          border-radius: 999px;
          background: var(--bg-muted, #f3f4f6);
        }

        .weak-point-bar span {
          display: block;
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, #d97706, #dc2626);
        }

        .weak-point-count {
          min-width: 88px;
          text-align: right;
          font-size: 0.85rem;
          color: var(--text-muted, #6b7280);
        }

        .strong-point-cloud {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .strong-point-tag {
          padding: 6px 12px;
          background: var(--success-bg, #d1fae5);
          color: var(--success-text, #065f46);
          border-radius: 16px;
          font-weight: 500;
        }

        .copy-outline-btn {
          grid-column: 1 / -1;
          align-self: start;
          padding: 6px 14px;
          border: 1px solid var(--border, #d1d5db);
          border-radius: 6px;
          background: white;
          cursor: pointer;
          font-size: 13px;
        }

        .suggestions-content {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 20px;
        }

        @media (max-width: 768px) {
          .suggestions-content {
            grid-template-columns: 1fr;
          }
        }

        .suggestion-block {
          padding: 16px;
          background: var(--bg-muted, #f3f4f6);
          border-radius: 8px;
        }

        .suggestion-block h4 {
          margin: 0 0 12px 0;
          font-size: 0.95rem;
          color: var(--text-muted, #6b7280);
        }

        .suggestion-block ul {
          margin: 0;
          padding-left: 20px;
        }

        .suggestion-block li {
          margin-bottom: 8px;
        }

        .topic-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .topic-tag {
          padding: 4px 10px;
          background: var(--accent-bg, #f0fdf4);
          color: var(--accent, #4b9560);
          border-radius: 4px;
          font-size: 0.85rem;
        }
      `}</style>
    </main>
  );
}
