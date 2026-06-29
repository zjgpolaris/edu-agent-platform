"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Profile = { recent_topics: string[]; weak_topics: string[]; grade?: string | null };
type Weakpoint = { knowledge_tag: string; wrong_count: number; last_wrong_at: string; source: string };
type ReviewPlan = { recommended_actions?: string[]; weakpoints?: Weakpoint[]; priority_topics?: string[] };
type ModuleTone = "jade" | "cinnabar" | "gold" | "ink";
type ModuleCard = {
  href: string; icon: string; title: string; desc: string; cta: string;
  tags: string[]; eyebrow: string; artifact: string; tone: ModuleTone; featured?: boolean;
};

const modules: ModuleCard[] = [
  { href: "/student/assistant", icon: "问", title: "学习助手", desc: "把教材、资料和追问整理成一条可执行的学习线索。", cta: "开始探索", tags: ["学习路线", "知识点提问"], eyebrow: "问学", artifact: "策", tone: "jade", featured: true },
  { href: "/student/textbook", icon: "册", title: "教材同步", desc: "按章节阅读、理解与复盘，适合课前预习和课后查漏。", cta: "进入教材", tags: ["章节学习", "知识理解"], eyebrow: "读史", artifact: "卷", tone: "gold" },
  { href: "/student/materials", icon: "纸", title: "资料学习", desc: "上传 PDF 或截图，识别文本后生成摘要和随堂练习。", cta: "上传资料", tags: ["OCR 校对", "练习生成"], eyebrow: "研材", artifact: "笺", tone: "ink" },
  { href: "/student/history/chat", icon: "人", title: "历史人物对话", desc: "与历史人物展开追问，在角色视角中理解人物与时代。", cta: "开始对话", tags: ["人物理解", "史实速览"], eyebrow: "入境", artifact: "像", tone: "cinnabar", featured: true },
  { href: "/student/history/debate", icon: "辩", title: "历史辩论场", desc: "围绕辩题组织论点、论据和反驳，训练历史思辨能力。", cta: "开始辩论", tags: ["正反论证", "裁判反馈"], eyebrow: "论辩", artifact: "辩", tone: "gold" },
  { href: "/student/history/games", icon: "弈", title: "历史游戏大厅", desc: "时间线、卡牌和多人模拟，把历史知识放进挑战任务。", cta: "进入大厅", tags: ["闯关练习", "知识挑战"], eyebrow: "闯关", artifact: "弈", tone: "jade" },
];

export default function StudentDashboardPage() {
  const { user } = useAuth();
  const displayName = user?.displayName || user?.actorId || "同学";
  const [profile, setProfile] = useState<Profile | null>(null);
  const [reviewPlan, setReviewPlan] = useState<ReviewPlan | null>(null);
  const [pendingReview, setPendingReview] = useState<number | null>(null);

  useEffect(() => {
    if (!user?.actorId) return;
    const headers = authHeaders(user.token);
    Promise.all([
      fetch(`${API}/api/students/${user.actorId}/profile`, { headers }),
      fetch(`${API}/api/students/${user.actorId}/review-plan`, { headers }),
      fetch(`${API}/api/students/${user.actorId}/review/today`, { headers }),
    ])
      .then(async ([profileRes, planRes, reviewRes]) => {
        if (profileRes.ok) {
          const profileData = await profileRes.json();
          if (profileData?.profile) setProfile(profileData.profile);
        }
        if (planRes.ok) {
          const planData = await planRes.json();
          if (planData?.review_plan) setReviewPlan(planData.review_plan);
        }
        if (reviewRes.ok) {
          const reviewData = await reviewRes.json();
          const remaining = (reviewData?.total ?? 0) - (reviewData?.completed ?? 0);
          setPendingReview(remaining > 0 ? remaining : 0);
        }
      })
      .catch(() => {});
  }, [user?.actorId, user?.token]);

  const recentTopics = profile?.recent_topics ?? [];
  const weakTopics = profile?.weak_topics ?? [];
  const priorityWeakpoints = reviewPlan?.weakpoints ?? [];
  const priorityTopics = reviewPlan?.priority_topics ?? weakTopics;
  const topReviewAction = reviewPlan?.recommended_actions?.[0];

  return (
    <main className="workbench-page student-workbench">
      <section className="workbench-hero">
        <div className="workbench-hero-copy student-hero-panel">
          <div className="student-hero-topline">
            <p className="workbench-kicker">学生学习工作台</p>
            <span className="student-hero-seal" aria-hidden="true">史</span>
          </div>
          <h1>{displayName}，今天从一个历史问题开始</h1>
          {priorityTopics[0] && (
            <div className="student-hero-question">
              今日优先复习「{priorityTopics[0]}」
            </div>
          )}
          <p>EduAgent 会把历史对话、教材学习、资料分析、作业批改和错题复习串起来，帮助你把薄弱点变成下一次练习任务。</p>
          {(recentTopics[0] || priorityWeakpoints.length > 0 || weakTopics.length > 0) && (
            <div className="student-hero-meta" aria-label="当前学习主题">
              {recentTopics[0] && <span>{recentTopics[0]}</span>}
              {priorityWeakpoints.length > 0 ? <span>错题本 {priorityWeakpoints.length} 个重点</span> : weakTopics.length > 0 && <span>薄弱点 {weakTopics.length} 个</span>}
            </div>
          )}
          <div className="workbench-actions">
            {pendingReview !== null && pendingReview > 0 && (
              <Link href="/student/review" className="workbench-primary-link" style={{ background: "var(--cinnabar, #c94a38)" }}>
                今日有 {pendingReview} 个知识点待复习
              </Link>
            )}
            <Link href="/student/learning-path" className={pendingReview ? "workbench-secondary-link" : "workbench-primary-link"}>查看复习路径</Link>
            <Link href="/student/weakpoints" className="workbench-secondary-link">打开错题本</Link>
          </div>
        </div>
        <aside className="workbench-next-card student-dossier-card" aria-label="今日建议">
          <span>今日学案</span>
          {priorityWeakpoints.length > 0 ? (
            <>
              <h2>建议复习：{priorityWeakpoints[0].knowledge_tag}</h2>
              <p>{topReviewAction || "以下是错题本中优先级最高的知识点，建议先复盘再练习。"}</p>
              <ol className="student-dossier-steps">
                {priorityWeakpoints.slice(0, 3).map((point) => (
                  <li key={point.knowledge_tag}>{point.knowledge_tag} · 出错 {point.wrong_count} 次</li>
                ))}
              </ol>
            </>
          ) : weakTopics.length > 0 ? (
            <>
              <h2>建议复习：{weakTopics[0]}</h2>
              <p>{topReviewAction || "以下是近期需要加强的知识点，建议逐一追问或做练习巩固。"}</p>
              <ol className="student-dossier-steps">
                {weakTopics.slice(0, 3).map((t) => <li key={t}>{t}</li>)}
              </ol>
            </>
          ) : (
            <>
              <h2>开始你的第一次学习</h2>
              <p>与历史人物对话、做练习或阅读教材，系统会自动记录你的学习轨迹。</p>
            </>
          )}
          <Link href={priorityWeakpoints.length > 0 || weakTopics.length > 0 ? "/student/learning-path" : "/student/textbook"}>
            {priorityWeakpoints.length > 0 || weakTopics.length > 0 ? "进入复习路径" : "进入教材"}
          </Link>
        </aside>
      </section>

      <section className="workbench-overview-grid" aria-label="今日任务">
        <div className="workbench-metric student-metric">
          <span className="student-metric-mark" aria-hidden="true">复</span>
          <strong>{pendingReview !== null ? pendingReview : "—"}</strong>
          <span>今日待复习</span>
        </div>
        <div className="workbench-metric student-metric">
          <span className="student-metric-mark" aria-hidden="true">错</span>
          <strong>{priorityWeakpoints.length > 0 ? priorityWeakpoints.length : weakTopics.length || "—"}</strong>
          <span>错题本知识点</span>
        </div>
        <div className="workbench-metric student-metric">
          <span className="student-metric-mark" aria-hidden="true">弱</span>
          <strong>{priorityTopics[0] ? <span style={{ fontSize: "0.85em" }}>{priorityTopics[0]}</span> : "—"}</strong>
          <span>优先复习</span>
        </div>
        <div className="workbench-metric student-metric">
          <span className="student-metric-mark" aria-hidden="true">主</span>
          <strong>{recentTopics.length > 0 ? <span style={{ fontSize: "0.85em" }}>{recentTopics[0]}</span> : "—"}</strong>
          <span>最近主题</span>
        </div>
      </section>

      <section className="workbench-main-grid">
        <div className="workbench-section student-module-section">
          <div className="workbench-section-heading student-section-heading">
            <p className="workbench-kicker">AGENT 协作馆</p>
            <h2>把历史学习拆成六种能力</h2>
            <p>从提问、读史、研材到论辩闯关，每个 Agent 都对应一种学习动作。</p>
          </div>
          <div className="workbench-module-grid">
            {modules.map((m) => (
              <Link
                key={m.href}
                href={m.href}
                className={`workbench-module-card module-${m.tone}${m.featured ? " featured" : ""}`}
              >
                <span className="student-module-artifact" aria-hidden="true">{m.artifact}</span>
                <div className="workbench-module-icon-box">{m.icon}</div>
                <div className="student-module-copy">
                  <span className="student-module-eyebrow">{m.eyebrow}</span>
                  <h3>{m.title}</h3>
                  <p>{m.desc}</p>
                  <div className="workbench-tag-row">
                    {m.tags.map((tag) => <span key={tag}>{tag}</span>)}
                  </div>
                </div>
                <strong>{m.cta}<span aria-hidden="true"> &rarr;</span></strong>
              </Link>
            ))}
          </div>
        </div>

        <aside className="workbench-side-panel student-path-panel" aria-label="学习路径">
          <div className="workbench-section-heading student-section-heading">
            <p className="workbench-kicker">学习路径</p>
            <h2>近期探索记录</h2>
            <p>以下是系统记录的学习话题和错题优先级，反映你近期最值得复盘的方向。</p>
          </div>
          <div className="path-meter"><span /></div>
          {priorityTopics.length > 0 ? (
            <ul className="workbench-plan-list student-timeline-list">
              {priorityTopics.slice(0, 5).map((topic, i) => {
                const point = priorityWeakpoints.find((item) => item.knowledge_tag === topic);
                return (
                  <li key={topic} className={i === 0 ? "active" : "done"}>
                    <div className="student-plan-copy"><strong>{topic}</strong></div>
                    <small>{point ? `错 ${point.wrong_count} 次` : i === 0 ? "优先" : "待巩固"}</small>
                  </li>
                );
              })}
            </ul>
          ) : recentTopics.length > 0 ? (
            <ul className="workbench-plan-list student-timeline-list">
              {recentTopics.slice(0, 5).map((topic, i) => (
                <li key={topic} className={i === 0 ? "active" : "done"}>
                  <div className="student-plan-copy"><strong>{topic}</strong></div>
                  <small>{i === 0 ? "最近" : "已学"}</small>
                </li>
              ))}
            </ul>
          ) : (
            <p style={{ color: "var(--muted)", fontSize: 14, padding: "12px 0" }}>
              开始学习后，这里会显示你的话题轨迹。
            </p>
          )}
          <Link href="/student/learning-path" className="workbench-secondary-link full">进入复习路径</Link>
        </aside>
      </section>
    </main>
  );
}
