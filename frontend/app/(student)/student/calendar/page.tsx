"use client";
import { useState, useEffect } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type ReviewDay = { completed: number; total: number };
type LearningReport = {
  streak_days: number;
  active_days: number;
  activity_by_day: Record<string, number>;
  review_by_day: Record<string, ReviewDay>;
  review_completed_total: number;
  review_tasks_total: number;
  weakpoint_count: number;
  autotutor_sessions: number;
};

// ── helpers ──────────────────────────────────────────────────────────────────

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

function activityLevel(count: number): 0 | 1 | 2 | 3 | 4 {
  if (count === 0) return 0;
  if (count < 3) return 1;
  if (count < 6) return 2;
  if (count < 10) return 3;
  return 4;
}

const LEVEL_COLORS = [
  "var(--cal-cell-0,#ebedf0)",
  "var(--cal-cell-1,#9be9a8)",
  "var(--cal-cell-2,#40c463)",
  "var(--cal-cell-3,#30a14e)",
  "var(--cal-cell-4,#216e39)",
];

const WEEKDAY_CN = ["日", "一", "二", "三", "四", "五", "六"];
const MONTH_CN = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"];

// ── Component ────────────────────────────────────────────────────────────────

export default function LearningCalendarPage() {
  const { user } = useAuth();
  const [report, setReport] = useState<LearningReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [days] = useState(63); // 9 周
  const [tooltip, setTooltip] = useState<{ date: string; act: number; rev: ReviewDay | null } | null>(null);

  useEffect(() => {
    if (!user?.actorId || !user?.token) { setLoading(false); return; }
    const sid = user.actorId;
    fetch(`${API}/api/student/${sid}/learning-report?days=${days}`, { headers: authHeaders(user.token) })
      .then(r => r.ok ? r.json() : null)
      .then(d => { setReport(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [user?.actorId, user?.token, days]);

  const allDays = lastNDays(days);

  // 按周分组（每列 = 一周，从最旧到最新）
  const weeks: string[][] = [];
  for (let i = 0; i < allDays.length; i += 7) {
    weeks.push(allDays.slice(i, i + 7));
  }

  const actMap = report?.activity_by_day ?? {};
  const revMap = report?.review_by_day ?? {};

  // 月份标签：每周首日所在月份，变化时显示
  const monthLabels: Array<string | null> = weeks.map((w, wi) => {
    const firstDay = w[0];
    const month = MONTH_CN[new Date(firstDay).getMonth()];
    if (wi === 0) return month;
    const prevFirst = weeks[wi - 1][0];
    return new Date(firstDay).getMonth() !== new Date(prevFirst).getMonth() ? month : null;
  });

  const reviewRate = report
    ? (report.review_tasks_total > 0 ? Math.round(report.review_completed_total / report.review_tasks_total * 100) : null)
    : null;

  return (
    <main className="academy-shell" style={{ minHeight: "100vh" }}>
      <style>{CSS}</style>

      <section className="panel">
        <div className="panel-heading-row">
          <div>
            <p className="section-kicker">LEARNING CALENDAR</p>
            <h2>学习日历</h2>
          </div>
          <Link className="secondary-link" href="/student/dashboard?tab=report" style={{ fontSize: "0.85rem" }}>
            查看完整报告 →
          </Link>
        </div>

        {loading && <p className="empty-hint">加载中…</p>}

        {!loading && report && (
          <>
            {/* 摘要卡片 */}
            <div className="cal-summary">
              <div className="cal-stat">
                <b>{report.streak_days}</b>
                <span>连续打卡天数 🔥</span>
              </div>
              <div className="cal-stat">
                <b>{report.active_days}</b>
                <span>活跃天数（近{days}天）</span>
              </div>
              <div className="cal-stat">
                <b>{reviewRate != null ? `${reviewRate}%` : "—"}</b>
                <span>复习完成率</span>
              </div>
              <div className="cal-stat">
                <b>{report.weakpoint_count}</b>
                <span>当前错题数</span>
              </div>
              <div className="cal-stat">
                <b>{report.autotutor_sessions}</b>
                <span>AI 辅导次数</span>
              </div>
            </div>

            {/* 热力图 */}
            <div className="cal-heatmap-wrap">
              {/* 月份标签行 */}
              <div className="cal-month-row">
                {weeks.map((_, wi) => (
                  <div key={wi} className="cal-month-cell">
                    {monthLabels[wi] ?? ""}
                  </div>
                ))}
              </div>
              {/* 周几标签 + 格子 */}
              <div className="cal-grid-area">
                <div className="cal-weekday-col">
                  {[0, 2, 4, 6].map(d => (
                    <div key={d} className="cal-weekday-lbl" style={{ gridRow: d + 1 }}>
                      {WEEKDAY_CN[d]}
                    </div>
                  ))}
                </div>
                <div className="cal-grid">
                  {weeks.map((week, wi) =>
                    week.map((date, di) => {
                      const act = actMap[date] ?? 0;
                      const rev = revMap[date] ?? null;
                      const level = activityLevel(act);
                      const hasReview = rev && rev.total > 0;
                      const revDone = hasReview && rev!.completed >= rev!.total;
                      return (
                        <div
                          key={date}
                          className="cal-cell"
                          style={{
                            background: LEVEL_COLORS[level],
                            gridColumn: wi + 1,
                            gridRow: di + 1,
                            outline: hasReview ? `2px solid ${revDone ? "#30a14e" : "#f59e0b"}` : undefined,
                            outlineOffset: "-2px",
                          }}
                          onMouseEnter={() => setTooltip({ date, act, rev: rev })}
                          onMouseLeave={() => setTooltip(null)}
                        />
                      );
                    })
                  )}
                </div>
              </div>

              {/* 图例 */}
              <div className="cal-legend">
                <span className="cal-legend-lbl">少</span>
                {LEVEL_COLORS.map((c, i) => (
                  <div key={i} className="cal-cell-mini" style={{ background: c }} />
                ))}
                <span className="cal-legend-lbl">多</span>
                <span className="cal-legend-sep">·</span>
                <div className="cal-cell-mini" style={{ background: LEVEL_COLORS[2], outline: "2px solid #f59e0b", outlineOffset: "-2px" }} />
                <span className="cal-legend-lbl">复习进行中</span>
                <div className="cal-cell-mini" style={{ background: LEVEL_COLORS[3], outline: "2px solid #30a14e", outlineOffset: "-2px" }} />
                <span className="cal-legend-lbl">复习完成</span>
              </div>
            </div>

            {/* Tooltip */}
            {tooltip && (
              <div className="cal-tooltip">
                <b>{tooltip.date}</b>
                <span>学习事件 {tooltip.act} 次</span>
                {tooltip.rev && tooltip.rev.total > 0 && (
                  <span>复习 {tooltip.rev.completed}/{tooltip.rev.total} 题</span>
                )}
                {(!tooltip.rev || tooltip.rev.total === 0) && tooltip.act === 0 && (
                  <span style={{ opacity: 0.6 }}>无学习记录</span>
                )}
              </div>
            )}

            {/* 日历说明 */}
            <p className="cal-hint">
              每格代表一天，颜色深浅反映学习事件数量（答题、阅读、辅导均计入）。
              带边框的格子表示当天有复习任务：橙框=进行中，绿框=全部完成。
            </p>
          </>
        )}

        {!loading && !report && (
          <p className="empty-hint">暂无学习记录，完成第一次练习后日历将自动更新。</p>
        )}
      </section>
    </main>
  );
}

const CSS = `
.cal-summary {
  display:flex; flex-wrap:wrap; gap:12px; margin-bottom:24px;
}
.cal-stat {
  flex:1; min-width:90px; padding:12px 14px; border-radius:10px;
  background:var(--surface-alt,#f9f9f8); border:1px solid var(--border-subtle,#e5e7eb);
  display:flex; flex-direction:column; align-items:center; gap:3px; text-align:center;
}
.cal-stat b { font-size:1.3rem; font-weight:800; color:var(--text-primary,#111); }
.cal-stat span { font-size:0.72rem; color:var(--text-muted,#6b7280); }
.cal-heatmap-wrap { overflow-x:auto; padding-bottom:8px; }
.cal-month-row {
  display:grid;
  grid-template-columns:repeat(var(--cal-weeks,9),14px);
  gap:3px; margin-left:22px; margin-bottom:3px;
}
.cal-month-cell { font-size:10px; color:var(--text-muted,#6b7280); }
.cal-grid-area { display:flex; gap:4px; }
.cal-weekday-col {
  display:grid; grid-template-rows:repeat(7,14px); gap:3px; align-items:center;
}
.cal-weekday-lbl { font-size:9px; color:var(--text-muted,#6b7280); text-align:right; padding-right:4px; }
.cal-grid {
  display:grid;
  grid-template-rows:repeat(7,14px);
  grid-auto-columns:14px; grid-auto-flow:column;
  gap:3px;
}
.cal-cell {
  width:14px; height:14px; border-radius:2px; cursor:default;
  transition:transform .1s;
}
.cal-cell:hover { transform:scale(1.25); z-index:1; }
.cal-cell-mini { width:11px; height:11px; border-radius:2px; flex-shrink:0; }
.cal-legend {
  display:flex; align-items:center; gap:4px; margin-top:8px;
  margin-left:22px; flex-wrap:wrap;
}
.cal-legend-lbl { font-size:10px; color:var(--text-muted,#6b7280); }
.cal-legend-sep { color:var(--text-muted,#6b7280); margin:0 4px; }
.cal-tooltip {
  display:inline-flex; flex-direction:column; gap:2px;
  background:#1f2937; color:#fff; border-radius:6px; padding:8px 12px;
  font-size:12px; margin-top:8px; margin-left:22px;
}
.cal-tooltip b { font-size:13px; }
.cal-hint { font-size:12px; color:var(--text-muted,#6b7280); margin-top:12px; line-height:1.6; }
`;
