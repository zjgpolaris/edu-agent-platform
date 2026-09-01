"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { safeNextForRole } from "@/lib/auth";

type Role = "student" | "teacher";

const DEMO: Record<Role, { username: string; password: string; displayName: string; avatar: string; hint: string }> = {
  student: { username: "pilot-student", password: "pilot123", displayName: "Pilot 学生A", avatar: "学", hint: "体验今日计划、错题复习与 AutoTutor 精讲" },
  teacher: { username: "pilot-teacher", password: "pilot123", displayName: "Pilot 张老师", avatar: "师", hint: "体验今日教学队列、欠交催办与质检盲区" },
};

const PROOF = [
  { title: "自主规划", desc: "根据学情决定本节目标和教学顺序" },
  { title: "答错后调整", desc: "Judge、Reflect、Re-plan 改变后续讲解" },
  { title: "独立验证", desc: "退出票验证掌握并把证据回流教师端" },
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

function HomeInner() {
  const { login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedRole = searchParams.get("role") === "teacher" ? "teacher" : "student";
  const requestedNext = searchParams.get("next");
  const [role, setRole] = useState<Role>(requestedRole);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => setRole(requestedRole), [requestedRole]);

  async function handleLogin(event: FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
      const auth = JSON.parse(localStorage.getItem("edu_auth") || "{}");
      router.push(safeNextForRole(requestedNext, auth.role));
    } catch {
      setError("用户名或密码错误，请重试");
    } finally {
      setLoading(false);
    }
  }

  async function enterDemo() {
    const account = DEMO[role];
    setUsername(account.username);
    setPassword(account.password);
    setError("");
    setLoading(true);
    try {
      await login(account.username, account.password);
      if (requestedNext) {
        router.push(safeNextForRole(requestedNext, role));
      } else {
        router.push(role === "teacher" ? "/teacher" : `/student/auto-tutor?focus=${encodeURIComponent("洋务运动目的")}&demo=1&fresh=1`);
      }
    } catch {
      setError("Pilot 体验账号暂不可用，请先运行 seed_pilot_demo.py");
    } finally {
      setLoading(false);
    }
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

          <p className="home-kicker">Plan · Judge · Reflect · Re-plan · Evidence</p>
          <h1 className="home-title">
            看得见决策的
            <br />
            AutoTutor Agent
          </h1>
          <p className="home-subtitle">
            Agent 读取学情后自主规划教学；答错时反思并调整策略，最后用独立退出票验证掌握，把证据回流到复习与教师端。
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
                {DEMO[role].displayName} · {role === "student" ? "体验 Agent 自主辅导" : "教师体验"}
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

export default function Home() {
  return (
    <Suspense fallback={<main className="home" aria-busy="true" />}>
      <HomeInner />
    </Suspense>
  );
}
