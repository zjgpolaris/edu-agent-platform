"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

// ── Types ────────────────────────────────────────────────────────────────────

type WeakpointSummary = { tag: string; count: number };
type HwEntry = { date: string; score: number | null };
type ReviewDay = { completed: number; total: number };

type LearningReport = {
  student_id: string;
  generated_at: string;
  period_days: number;
  // 掌握率
  mastery_pct: number | null;
  weak_topic_count: number;
  strong_topic_count: number;
  // 练习
  quiz_avg_score: number | null;
  quiz_attempts: number;
  game_avg_score: number | null;
  // SM-2 复习
  review_by_day: Record<string, ReviewDay>;
  review_completed_total: number;
  review_tasks_total: number;
  review_completion_rate: number | null;
  // 作业批改
  homework_trend: HwEntry[];
  homework_count: number;
  homework_avg_score: number | null;
  // 活跃度
  activity_by_day: Record<string, number>;
  active_days: number;
  streak_days: number;
  // AutoTutor
  autotutor_sessions: number;
  // 错题本
  weakpoint_count: number;
  top_weakpoints: WeakpointSummary[];
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function pct(v: number | null, decimals = 0): string {
  if (v == null) return "—";
  return v.toFixed(decimals) + "%";
}

function fmt(v: number | null, decimals = 1): string {
  if (v == null) return "—";
  return v.toFixed(decimals);
}

/** Last N days in YYYY-MM-DD order */
function lastNDays(n: number): string[] {
  const days: string[] = [];
  const today = new Date();
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    days.push(d.toISOString().slice(0, 10));
  }
  return days;
}

function levelColor(count: number): string {
  if (count === 0) return "var(--rpt-cell-0)";
  if (count < 3) return "var(--rpt-cell-1)";
  if (count < 6) return "var(--rpt-cell-2)";
  if (count < 10) return "var(--rpt-cell-3)";
  return "var(--rpt-cell-4)";
}

// ── Sub-components ───────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  level,
}: {
  label: string;
  value: string;
  sub?: string;
  level?: "high" | "mid" | "low" | "neutral";
}) {
  return (
    <div className={`rpt-stat-card rpt-stat-${level ?? "neutral"}`}>
      <span className="rpt-stat-val">{value}</span>
      <span className="rpt-stat-label">{label}</span>
      {sub && <span className="rpt-stat-sub">{sub}</span>}
    </div>
  );
}

function ActivityHeatmap({
  days,
  activity,
}: {
  days: string[];
  activity: Record<string, number>;
}) {
  return (
    <div className="rpt-section">
      <h3 className="rpt-section-title">学习活跃度</h3>
      <p className="rpt-section-desc">过去 {days.length} 天每日学习事件数</p>
      <div className="rpt-heatmap">
        {days.map((d) => {
          const count = activity[d] ?? 0;
          return (
            <div
              key={d}
              className="rpt-heatmap-cell"
              style={{ background: levelColor(count) }}
              title={`${d}：${count} 次活动`}
            />
          );
        })}
      </div>
      <div className="rpt-heatmap-legend">
        <span>少</span>
        {[0, 1, 2, 3, 4].map((lvl) => (
          <div
            key={lvl}
            className="rpt-heatmap-cell"
            style={{
              background: levelColor([0, 1, 4, 7, 12][lvl]),
              flexShrink: 0,
            }}
          />
        ))}
        <span>多</span>
      </div>
    </div>
  );
}

function ReviewProgress({
  reviewByDay,
  days,
}: {
  reviewByDay: Record<string, ReviewDay>;
  days: string[];
}) {
  const hasDays = days.some((d) => reviewByDay[d]);
  if (!hasDays) {
    return (
      <div className="rpt-section">
        <h3 className="rpt-section-title">SM-2 复习进度</h3>
        <p className="rpt-empty">本期内暂无复习记录，前往「今日复习」开始打卡。</p>
      </div>
    );
  }
  const max = Math.max(...days.map((d) => reviewByDay[d]?.total ?? 0), 1);
  return (
    <div className="rpt-section">
      <h3 className="rpt-section-title">SM-2 复习进度</h3>
      <p className="rpt-section-desc">每日复习完成 / 应复习数</p>
      <div className="rpt-bars">
        {days.slice(-14).map((d) => {
          const rv = reviewByDay[d];
          if (!rv) return <div key={d} className="rpt-bar-col"><div className="rpt-bar-empty" /></div>;
          const donePct = rv.total > 0 ? (rv.completed / rv.total) * 100 : 0;
          const totalH = (rv.total / max) * 80;
          return (
            <div key={d} className="rpt-bar-col" title={`${d}：${rv.completed}/${rv.total}`}>
              <div className="rpt-bar-wrap" style={{ height: `${Math.max(totalH, 4)}px` }}>
                <div className="rpt-bar-done" style={{ height: `${donePct}%` }} />
              </div>
              <span className="rpt-bar-lbl">{d.slice(8)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function HomeworkTrend({ trend }: { trend: HwEntry[] }) {
  if (!trend.length) {
    return (
      <div className="rpt-section">
        <h3 className="rpt-section-title">作业批改趋势</h3>
        <p className="rpt-empty">暂无作业批改记录，上传作业照片开始批改。</p>
      </div>
    );
  }
  const scores = trend.map((h) => h.score ?? 0);
  const maxScore = Math.max(...scores, 1);
  return (
    <div className="rpt-section">
      <h3 className="rpt-section-title">作业批改趋势</h3>
      <p className="rpt-section-desc">近 {trend.length} 次批改分数走势</p>
      <div className="rpt-sparkline">
        {trend.map((h, i) => {
          const h_pct = h.score != null ? (h.score / maxScore) * 100 : 0;
          const level =
            h.score == null ? "neutral"
            : h.score >= 85 ? "high"
            : h.score >= 70 ? "mid"
            : "low";
          return (
            <div key={i} className="rpt-spark-col" title={`${h.date}：${h.score ?? "—"}`}>
              <div className="rpt-spark-wrap">
                <div className={`rpt-spark-bar rpt-spark-${level}`} style={{ height: `${Math.max(h_pct, 4)}%` }} />
              </div>
              <span className="rpt-spark-score">
                {h.score != null ? h.score : "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WeakpointList({ points }: { points: WeakpointSummary[] }) {
  if (!points.length) {
    return (
      <div className="rpt-section">
        <h3 className="rpt-section-title">高频错题</h3>
        <p className="rpt-empty">暂无错题记录，继续保持！</p>
      </div>
    );
  }
  const maxCount = points[0]?.count ?? 1;
  return (
    <div className="rpt-section">
      <h3 className="rpt-section-title">高频错题 TOP5</h3>
      <p className="rpt-section-desc">出错次数最多的知识点</p>
      <div className="rpt-weaklist">
        {points.map((wp, i) => (
          <Link
            key={wp.tag}
            href={`/student/assistant?q=${encodeURIComponent(`帮我复习知识点「${wp.tag}」`)}`}
            className="rpt-weak-row"
          >
            <span className="rpt-weak-rank">#{i + 1}</span>
            <span className="rpt-weak-tag">{wp.tag}</span>
            <div className="rpt-weak-bar-wrap">
              <div
                className="rpt-weak-bar"
                style={{ width: `${(wp.count / maxCount) * 100}%` }}
              />
            </div>
            <span className="rpt-weak-count">×{wp.count}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function StudentReportPage() {
  const { user } = useAuth();
  const [report, setReport] = useState<LearningReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user?.actorId || user.role !== "student") {
      setError("请以学生身份登录");
      setLoading(false);
      return;
    }
    fetch(`${API}/api/student/${user.actorId}/learning-report?days=14`, {
      headers: authHeaders(user.token),
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<LearningReport>;
      })
      .then(setReport)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [user]);

  const days14 = lastNDays(14);

  return (
    <div className="rpt-shell">
      {/* Header */}
      <div className="rpt-header">
        <div className="rpt-header-seal" aria-hidden>报</div>
        <div className="rpt-header-text">
          <p className="rpt-eyebrow">LEARNING REPORT · 成长报告</p>
          <h1 className="rpt-title">学习成长报告</h1>
          <p className="rpt-subtitle">过去 14 天的学习轨迹综合分析</p>
        </div>
      </div>

      {loading && <p className="rpt-loading">报告生成中…</p>}
      {error && <p className="rpt-error">{error}</p>}

      {report && (
        <main className="rpt-main">
          {/* ── 摘要指标卡 ── */}
          <section className="rpt-stats-grid">
            <StatCard
              label="知识掌握率"
              value={pct(report.mastery_pct)}
              sub={`${report.strong_topic_count} 掌握 / ${report.weak_topic_count} 待加强`}
              level={
                report.mastery_pct == null ? "neutral"
                : report.mastery_pct >= 70 ? "high"
                : report.mastery_pct >= 40 ? "mid"
                : "low"
              }
            />
            <StatCard
              label="复习完成率"
              value={pct(report.review_completion_rate)}
              sub={`${report.review_completed_total} / ${report.review_tasks_total} 题`}
              level={
                report.review_completion_rate == null ? "neutral"
                : report.review_completion_rate >= 80 ? "high"
                : report.review_completion_rate >= 50 ? "mid"
                : "low"
              }
            />
            <StatCard
              label="连续打卡"
              value={`${report.streak_days} 天`}
              sub={`活跃 ${report.active_days} / ${report.period_days} 天`}
              level={
                report.streak_days >= 7 ? "high"
                : report.streak_days >= 3 ? "mid"
                : report.streak_days > 0 ? "low"
                : "neutral"
              }
            />
            <StatCard
              label="作业均分"
              value={fmt(report.homework_avg_score)}
              sub={`共 ${report.homework_count} 次批改`}
              level={
                report.homework_avg_score == null ? "neutral"
                : report.homework_avg_score >= 85 ? "high"
                : report.homework_avg_score >= 70 ? "mid"
                : "low"
              }
            />
            <StatCard
              label="练习均分"
              value={report.quiz_avg_score != null ? pct(report.quiz_avg_score * 100) : "—"}
              sub={`共 ${report.quiz_attempts} 次练习`}
              level={
                report.quiz_avg_score == null ? "neutral"
                : report.quiz_avg_score >= 0.8 ? "high"
                : report.quiz_avg_score >= 0.6 ? "mid"
                : "low"
              }
            />
            <StatCard
              label="自主辅导会话"
              value={`${report.autotutor_sessions}`}
              sub="AutoTutor 完成次数"
              level={report.autotutor_sessions > 0 ? "mid" : "neutral"}
            />
          </section>

          {/* ── 活跃度热图 ── */}
          <ActivityHeatmap days={days14} activity={report.activity_by_day} />

          {/* ── 复习进度 + 作业趋势 ── */}
          <div className="rpt-two-col">
            <ReviewProgress reviewByDay={report.review_by_day} days={days14} />
            <HomeworkTrend trend={report.homework_trend} />
          </div>

          {/* ── 高频错题 ── */}
          <WeakpointList points={report.top_weakpoints} />

          {/* ── 底部导航 ── */}
          <div className="rpt-footer-links">
            <Link href="/student/review" className="rpt-footer-btn">📅 今日复习</Link>
            <Link href="/student/auto-tutor" className="rpt-footer-btn">🤖 自主辅导</Link>
            <Link href="/student/review?tab=weakpoints" className="rpt-footer-btn">📖 错题库</Link>
            <Link href="/student/dashboard" className="rpt-footer-btn">📊 学情总览</Link>
          </div>
        </main>
      )}
    </div>
  );
}
