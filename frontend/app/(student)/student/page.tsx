"use client";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";
import TodayPlanCard from "./TodayPlanCard";
import WeeklySummaryCard from "./WeeklySummaryCard";
import ContinueLearningCard from "./ContinueLearningCard";
import { useStudentWorkbenchData } from "./useStudentWorkbenchData";
type ModuleTone = "jade" | "cinnabar" | "gold" | "ink";
type ModuleCard = {
  href: string; icon: string; title: string; desc: string; cta: string;
  tags: string[]; eyebrow: string; artifact: string; tone: ModuleTone; featured?: boolean;
};

const modules: ModuleCard[] = [
  { href: "/student/assistant", icon: "问", title: "随问 · 学习助手", desc: "有问题就问，也可以接着追问刚才的内容。", cta: "开始提问", tags: ["自由提问", "多轮追问"], eyebrow: "问学", artifact: "策", tone: "jade", featured: true },
  { href: "/student/materials?tab=textbook", icon: "册", title: "教材同步", desc: "按章节阅读、理解与复盘，适合课前预习和课后查漏。", cta: "进入教材", tags: ["章节学习", "知识理解"], eyebrow: "读史", artifact: "卷", tone: "gold" },
  { href: "/student/materials", icon: "纸", title: "学习资料", desc: "上传 PDF 或截图，识别文本后生成摘要和随堂练习；或切换到教材目录。", cta: "上传资料", tags: ["OCR 校对", "练习生成"], eyebrow: "研材", artifact: "笺", tone: "ink" },
  { href: "/student/history/chat", icon: "人", title: "历史人物对话", desc: "与历史人物展开追问，在角色视角中理解人物与时代。", cta: "开始对话", tags: ["人物理解", "史实速览"], eyebrow: "入境", artifact: "像", tone: "cinnabar", featured: true },
  { href: "/student/history/debate", icon: "辩", title: "历史辩论场", desc: "围绕辩题组织论点、论据和反驳，训练历史思辨能力。", cta: "开始辩论", tags: ["正反论证", "裁判反馈"], eyebrow: "论辩", artifact: "辩", tone: "gold" },
  { href: "/student/history/games", icon: "弈", title: "历史游戏大厅", desc: "时间线、卡牌和多人模拟，把历史知识放进挑战任务。", cta: "进入大厅", tags: ["闯关练习", "知识挑战"], eyebrow: "闯关", artifact: "弈", tone: "jade" },
];

export default function StudentDashboardPage() {
  const { user } = useAuth();
  const displayName = user?.displayName || user?.actorId || "同学";
  const { profile, reviewPlan, todayPlan, loading, error, refreshTodayPlan } = useStudentWorkbenchData(user?.actorId, user?.token);

  const recentTopics = profile?.recent_topics ?? [];
  const weakTopics = profile?.weak_topics ?? [];
  const priorityWeakpoints = reviewPlan?.weakpoints ?? [];
  const priorityTopics = reviewPlan?.priority_topics ?? weakTopics;

  return (
    <main className="workbench-page student-workbench">
      <section className="student-hero-band">
        <div className="student-hero-band-copy">
          <p className="workbench-kicker">学生学习工作台</p>
          <h1>{displayName}，今天从一个历史问题开始</h1>
          <p>
            EduAgent 把历史对话、教材学习、资料分析、作业批改和错题复习串起来，
            帮助你把薄弱点变成下一次练习任务。
          </p>
          {(recentTopics[0] || priorityTopics[0]) && (
            <div className="student-hero-meta" aria-label="当前学习主题">
              {priorityTopics[0] && <span>优先复习 · {priorityTopics[0]}</span>}
              {recentTopics[0] && <span>最近学过 · {recentTopics[0]}</span>}
            </div>
          )}
        </div>
        <span className="student-hero-band-seal" aria-hidden="true">史</span>
      </section>

      <ContinueLearningCard plan={todayPlan} loading={loading} failed={Boolean(error)} />
      <TodayPlanCard plan={todayPlan} loading={loading} error={Boolean(error)} onPlanRefresh={refreshTodayPlan} />
      <WeeklySummaryCard />

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
