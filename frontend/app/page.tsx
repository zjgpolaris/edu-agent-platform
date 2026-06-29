"use client";
import Link from "next/link";

export default function Home() {
  return (
    <main className="landing-page">
      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-hero-copy" style={{ maxWidth: 480, margin: "0 auto", textAlign: "center" }}>
          <Link href="/" className="landing-brand" style={{ justifyContent: "center", marginBottom: 24 }}>
            <span className="landing-brand-mark">教</span>
            <span>
              <strong>EduAgent</strong>
              <small>K-12 历史 · 语文 AI 学习平台</small>
            </span>
          </Link>
          <p className="landing-kicker">多 Agent 协作 · 即时反馈 · 个性化路径</p>
          <h1 id="landing-title">陪伴式 AI 学习伙伴</h1>
          <p className="landing-subtitle">
            面向历史与语文学习，把史料检索、写作反馈、辩论训练和学情规划组织成一个可持续成长的学习工作台。
          </p>
          <div className="landing-role-cards">
            <Link href="/login?role=student" className="landing-role-card">
              <div className="landing-role-icon">
                <span style={{ fontSize: 26 }}>学</span>
              </div>
              <strong>学生登录</strong>
              <small>进入学习工作台，追问历史，打磨文章</small>
            </Link>
            <Link href="/login?role=teacher" className="landing-role-card teacher">
              <div className="landing-role-icon">
                <span style={{ fontSize: 26 }}>师</span>
              </div>
              <strong>教师登录</strong>
              <small>批改作文，备课资源，全班学情一览</small>
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}
