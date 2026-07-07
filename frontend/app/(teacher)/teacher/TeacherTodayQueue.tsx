"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { fetchApiJson, normalizeError } from "@/lib/api";

type CompletionOverview = {
  summary?: { students_with_overdue?: number; student_count?: number; assignment_count?: number };
  students?: Array<{ student_id: string; pending: number; overdue: number }>;
};
type HomeworkReviewsResponse = { reviews?: unknown[]; items?: unknown[] } | unknown[];
type ClassAnalytics = { top_weak_topics?: [string, number][]; weak_topics_distribution?: Record<string, number> };
type ClassWrongAnalysis = { questions?: Array<{ knowledge_tag?: string | null; accuracy?: number; student_count_wrong?: number; assignment_title?: string }> };
type QualityDashboard = { effectiveness?: { blind_spots_open?: number } };

type QueueItem = {
  key: string;
  tone: "danger" | "warm" | "jade" | "gold";
  label: string;
  title: string;
  detail: string;
  href: string;
  cta: string;
};

function reviewCount(data: HomeworkReviewsResponse | null): number {
  if (!data) return 0;
  if (Array.isArray(data)) return data.length;
  if (Array.isArray(data.reviews)) return data.reviews.length;
  if (Array.isArray(data.items)) return data.items.length;
  return 0;
}

/** 教师首页「今日教学队列」：复用现有教师接口，聚合今天先处理的教学动作。 */
export default function TeacherTodayQueue() {
  const { user } = useAuth();
  const [reviews, setReviews] = useState<HomeworkReviewsResponse | null>(null);
  const [completion, setCompletion] = useState<CompletionOverview | null>(null);
  const [analytics, setAnalytics] = useState<ClassAnalytics | null>(null);
  const [wrongAnalysis, setWrongAnalysis] = useState<ClassWrongAnalysis | null>(null);
  const [quality, setQuality] = useState<QualityDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user?.token) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.allSettled([
      fetchApiJson<HomeworkReviewsResponse>("/api/teacher/homework-reviews?decision=pending&limit=50", { token: user.token }),
      fetchApiJson<CompletionOverview>("/api/teacher/completion-overview", { token: user.token }),
      fetchApiJson<ClassAnalytics>("/api/teacher/class-analytics", { token: user.token }),
      fetchApiJson<ClassWrongAnalysis>("/api/teacher/class-wrong-analysis?limit_assignments=8&top_n=5", { token: user.token }),
      fetchApiJson<QualityDashboard>("/api/teacher/quality-dashboard", { token: user.token }),
    ]).then((results) => {
      if (cancelled) return;
      const [reviewRes, completionRes, analyticsRes, wrongRes, qualityRes] = results;
      if (reviewRes.status === "fulfilled") setReviews(reviewRes.value);
      if (completionRes.status === "fulfilled") setCompletion(completionRes.value);
      if (analyticsRes.status === "fulfilled") setAnalytics(analyticsRes.value);
      if (wrongRes.status === "fulfilled") setWrongAnalysis(wrongRes.value);
      if (qualityRes.status === "fulfilled") setQuality(qualityRes.value);
      const firstRejected = results.find((r): r is PromiseRejectedResult => r.status === "rejected");
      if (results.every((r) => r.status === "rejected") && firstRejected) {
        setError(normalizeError(firstRejected.reason, "教学队列加载失败"));
      }
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [user?.token]);

  const items = useMemo<QueueItem[]>(() => {
    const next: QueueItem[] = [];
    const pendingReviews = reviewCount(reviews);
    if (pendingReviews > 0) {
      next.push({
        key: "reviews",
        tone: "danger",
        label: "待复核",
        title: `${pendingReviews} 份作业/批改等待确认`,
        detail: "先处理需要教师判断的 AI 批改结果，避免学生反馈卡在待审核状态。",
        href: "/teacher/grading?tab=homework",
        cta: "进入批改",
      });
    }

    const blindSpots = quality?.effectiveness?.blind_spots_open || 0;
    if (blindSpots > 0) {
      next.push({
        key: "quality-blind-spots",
        tone: "warm",
        label: "质检盲区",
        title: `${blindSpots} 处 AI 质检盲区待复核`,
        detail: "这些题 AI 判为合格但真实正确率异常低，复核后会回流命题质检。",
        href: "/teacher/quality-dashboard",
        cta: "去复核",
      });
    }

    const students = completion?.students || [];
    const behind = students.filter((s) => (s.pending || 0) > 0);
    const overdue = completion?.summary?.students_with_overdue || behind.filter((s) => (s.overdue || 0) > 0).length;
    if (behind.length > 0) {
      next.push({
        key: "completion",
        tone: overdue > 0 ? "warm" : "gold",
        label: overdue > 0 ? "有逾期" : "待催办",
        title: `${behind.length} 名学生还有作业未交`,
        detail: overdue > 0 ? `其中 ${overdue} 名学生存在逾期作业，建议优先催办。` : "可查看完成情况并对欠交学生发送提醒。",
        href: "/teacher/assignments",
        cta: "查看作业",
      });
    }

    const weak = analytics?.top_weak_topics?.[0];
    if (weak) {
      next.push({
        key: "weak-topic",
        tone: "jade",
        label: "讲评重点",
        title: `优先讲评「${weak[0]}」`,
        detail: `${weak[1]} 名学生暴露该薄弱点，可先看班级学情再生成讲评建议。`,
        href: "/teacher/class-analytics",
        cta: "查看学情",
      });
    }

    const wrong = wrongAnalysis?.questions?.[0];
    if (wrong) {
      next.push({
        key: "wrong-question",
        tone: "gold",
        label: "共性错题",
        title: wrong.knowledge_tag ? `复盘「${wrong.knowledge_tag}」错题` : "复盘全班高错率题",
        detail: `来自${wrong.assignment_title ? `「${wrong.assignment_title}」` : "近期作业"}，${wrong.student_count_wrong || 0} 人答错。`,
        href: "/teacher/class-analytics",
        cta: "查看难题榜",
      });
    }
    return next.slice(0, 4);
  }, [reviews, completion, analytics, wrongAnalysis, quality]);

  if (!user?.token) return null;

  return (
    <section className="ttq-card" aria-label="今日教学队列">
      <style>{CSS}</style>
      <div className="ttq-head">
        <div>
          <p className="ttq-eyebrow">TODAY QUEUE · 今日教学队列</p>
          <h2>今天先处理这些</h2>
        </div>
        <Link href="/teacher/class-analytics" className="ttq-head-link">班级学情 →</Link>
      </div>

      {loading ? (
        <div className="ttq-skeleton"><span /><span /><span /></div>
      ) : error ? (
        <p className="ttq-empty">{error}</p>
      ) : items.length === 0 ? (
        <div className="ttq-clear">
          <strong>当前没有紧急教学待办</strong>
          <p>可以查看班级学情，或为下一节课准备资料。</p>
          <div className="ttq-actions">
            <Link href="/teacher/materials">生成资料</Link>
            <Link href="/teacher/class-analytics">查看学情</Link>
          </div>
        </div>
      ) : (
        <div className="ttq-list">
          {items.map((item) => (
            <Link key={item.key} href={item.href} className={`ttq-item ${item.tone}`}>
              <span className="ttq-label">{item.label}</span>
              <span className="ttq-copy">
                <strong>{item.title}</strong>
                <small>{item.detail}</small>
              </span>
              <span className="ttq-cta">{item.cta} →</span>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

const CSS = `
.ttq-card { background:linear-gradient(145deg, rgba(255,252,244,.96), rgba(246,238,219,.82)); border:1px solid rgba(96,72,44,.18); border-radius:18px; padding:20px 22px; margin:0 0 24px; box-shadow:var(--shadow-sm); }
.ttq-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:14px; }
.ttq-eyebrow { font-size:10px; letter-spacing:.24em; color:var(--cinnabar,#b7422b); margin:0 0 4px; }
.ttq-head h2 { margin:0; font-size:20px; letter-spacing:.04em; }
.ttq-head-link { color:var(--cinnabar,#b7422b); font-size:12px; font-weight:800; white-space:nowrap; }
.ttq-list { display:grid; gap:10px; }
.ttq-item { display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:12px; align-items:center; padding:13px 14px; border-radius:14px; border:1px solid rgba(96,72,44,.13); background:rgba(255,252,244,.72); text-decoration:none; color:inherit; transition:transform .18s, border-color .18s, box-shadow .18s; }
.ttq-item:hover { transform:translateX(3px); border-color:rgba(183,66,43,.24); box-shadow:0 12px 28px rgba(59,39,19,.08); }
.ttq-label { border-radius:999px; padding:4px 9px; font-size:11px; font-weight:900; white-space:nowrap; }
.ttq-item.danger .ttq-label { background:#fee2e2; color:#991b1b; }
.ttq-item.warm .ttq-label { background:#ffedd5; color:#9a3412; }
.ttq-item.jade .ttq-label { background:#dff3eb; color:#0b4f48; }
.ttq-item.gold .ttq-label { background:#fef3c7; color:#92400e; }
.ttq-copy { min-width:0; }
.ttq-copy strong { display:block; font-size:15px; color:var(--ink,#1a1612); margin-bottom:3px; }
.ttq-copy small { display:block; color:var(--muted,#887967); line-height:1.5; }
.ttq-cta { color:var(--jade,#0f6b5f); font-size:12px; font-weight:900; white-space:nowrap; }
.ttq-empty,.ttq-clear p { color:var(--muted,#887967); font-size:13px; line-height:1.7; }
.ttq-clear { background:rgba(15,107,95,.06); border:1px solid rgba(15,107,95,.12); border-radius:14px; padding:14px; }
.ttq-clear strong { display:block; color:var(--ink,#1a1612); margin-bottom:4px; }
.ttq-actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
.ttq-actions a { border:1px solid rgba(15,107,95,.18); border-radius:999px; padding:7px 12px; color:var(--jade-dark,#0b4f48); text-decoration:none; font-size:12px; font-weight:800; }
.ttq-skeleton { display:grid; gap:10px; }
.ttq-skeleton span { height:58px; border-radius:14px; background:linear-gradient(90deg,#f2eadc 0%,#fffaf0 48%,#f2eadc 100%); background-size:220% 100%; animation:ttqShimmer 1.2s ease-in-out infinite; }
@keyframes ttqShimmer { 0%{background-position:120% 0} 100%{background-position:-120% 0} }
@media (max-width:640px) { .ttq-item { grid-template-columns:1fr; } .ttq-cta { justify-self:start; } }
`;
