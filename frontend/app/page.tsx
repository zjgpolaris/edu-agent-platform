"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { AuthUser, saveAuth } from "@/lib/auth";

type Role = "student" | "teacher";

const DEMO: Record<Role, { username: string; displayName: string; avatar: string; hint: string }> = {
  student: { username: "student_001", displayName: "李明", avatar: "李", hint: "继续教材学习与错题复盘" },
  teacher: { username: "teacher_zhang", displayName: "张老师", avatar: "张", hint: "查看班级洞察与批改任务" },
};

const PROOF = [
  { title: "史料可追溯", desc: "RAG 检索，每个结论都有出处" },
  { title: "即时反馈", desc: "练习、作文、辩论实时复盘" },
  { title: "教师协同", desc: "高风险评分由人工确认" },
];

const COPY: Record<Role, { heading: string; sub: string; placeholder: string; cta: string }> = {
  student: {
    heading: "进入学习工作台",
    sub: "追问历史，打磨文章，复盘错题。",
    placeholder: "输入学号",
    cta: "登录学生工作台",
  },
  teacher: {
    heading: "进入教学工作台",
    sub: "批改作文，备课资源，全班学情一览。",
    placeholder: "输入教师账号",
    cta: "登录教师工作台",
  },
};

export default function Home() {
  const { login } = useAuth();
  const router = useRouter();
  const [role, setRole] = useState<Role>("student");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleLogin(event: FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
      const auth = JSON.parse(localStorage.getItem("edu_auth") || "{}");
      router.push(auth.role === "teacher" ? "/teacher" : "/student");
    } catch {
      setError("用户名或密码错误，请重试");
    } finally {
      setLoading(false);
    }
  }

  function enterDemo() {
    const account = DEMO[role];
    const auth: AuthUser = {
      actorId: account.username,
      role,
      displayName: account.displayName,
      token: `demo-${role}-token`,
    };
    saveAuth(auth);
    window.location.assign(role === "teacher" ? "/teacher" : "/student");
  }

  const copy = COPY[role];

  return (
    <main className="home">
      <div className="home-veil" aria-hidden="true" />

      <div className="home-inner">
        <section className="home-intro">
          <Link href="/" className="home-brand">
            <span className="home-brand-mark">教</span>
            <span className="home-brand-text">
              <strong>EduAgent</strong>
              <small>K-12 历史 · 语文 AI 学习平台</small>
            </span>
          </Link>

          <p className="home-kicker">多 Agent 协作 · 即时反馈 · 个性化路径</p>
          <h1 className="home-title">
            陪伴式
            <br />
            AI 学习伙伴
          </h1>
          <p className="home-subtitle">
            面向历史与语文学习，把史料检索、写作反馈、辩论训练与学情规划，组织成一个可持续成长的学习工作台。
          </p>

          <ul className="home-proof">
            {PROOF.map((item) => (
              <li key={item.title}>
                <strong>{item.title}</strong>
                <small>{item.desc}</small>
              </li>
            ))}
          </ul>

          <p className="home-seal" aria-hidden="true">
            學<br />而<br />時<br />習
          </p>
        </section>

        <section className={`home-access is-${role}`} aria-label="登录 EduAgent">
          <div className="home-access-glow" aria-hidden="true" />

          <div className="home-role-switch" role="tablist" aria-label="选择身份">
            <button
              type="button"
              role="tab"
              aria-selected={role === "student"}
              className={`home-role-tab${role === "student" ? " active" : ""}`}
              onClick={() => setRole("student")}
            >
              <span className="home-role-ico">学</span>
              学生
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={role === "teacher"}
              className={`home-role-tab${role === "teacher" ? " active" : ""}`}
              onClick={() => setRole("teacher")}
            >
              <span className="home-role-ico">师</span>
              教师
            </button>
            <span className="home-role-thumb" aria-hidden="true" />
          </div>

          <div className="home-access-head">
            <h2>{copy.heading}</h2>
            <p>{copy.sub}</p>
          </div>

          <form className="home-form" onSubmit={handleLogin}>
            <label className="home-field">
              <span>用户名 / 学号</span>
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder={copy.placeholder}
                autoComplete="username"
                required
              />
            </label>
            <label className="home-field">
              <span>密码</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="输入密码"
                autoComplete="current-password"
                required
              />
            </label>
            {error && <p className="home-error">{error}</p>}
            <button className="home-submit" type="submit" disabled={loading}>
              {loading ? "验证中…" : copy.cta}
            </button>
          </form>

          <div className="home-divider">
            <span>免注册 · 一键体验</span>
          </div>

          <button type="button" className="home-demo" onClick={enterDemo} disabled={loading}>
            <span className="home-demo-ava">{DEMO[role].avatar}</span>
            <span className="home-demo-meta">
              <strong>
                {DEMO[role].displayName} · {role === "student" ? "学生体验" : "教师体验"}
              </strong>
              <small>{DEMO[role].hint}</small>
            </span>
            <span className="home-demo-go" aria-hidden="true">
              →
            </span>
          </button>

          <p className="home-foot">
            还没有账号？<Link href="/register">创建学生账号</Link>
          </p>
        </section>
      </div>
    </main>
  );
}
