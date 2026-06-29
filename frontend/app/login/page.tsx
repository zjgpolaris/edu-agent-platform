"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";
import { AuthUser, clearAuth, saveAuth } from "@/lib/auth";

const quickAccounts = [
  {
    label: "学生体验",
    username: "student_001",
    role: "student" as const,
    displayName: "李明",
    description: "继续教材学习与错题复盘",
    badge: "Learner",
  },
  {
    label: "教师体验",
    username: "teacher_zhang",
    role: "teacher" as const,
    displayName: "张老师",
    description: "查看班级洞察与批改任务",
    badge: "Mentor",
  },
];

export default function LoginPage() {
  return <Suspense><LoginContent /></Suspense>;
}

function LoginContent() {
  const { login } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const roleHint = params.get("role") as "student" | "teacher" | null;
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    clearAuth();
  }, []);

  async function doLogin(nextUsername: string, nextPassword: string) {
    setError("");
    setLoading(true);
    try {
      await login(nextUsername, nextPassword);
      const auth = JSON.parse(localStorage.getItem("edu_auth") || "{}");
      router.push(auth.role === "teacher" ? "/teacher" : "/student");
    } catch {
      setError("用户名或密码错误");
    } finally {
      setLoading(false);
    }
  }

  function enterDemo(account: (typeof quickAccounts)[number]) {
    const auth: AuthUser = {
      actorId: account.username,
      role: account.role,
      displayName: account.displayName,
      token: `demo-${account.role}-token`,
    };

    saveAuth(auth);
    window.location.assign(account.role === "teacher" ? "/teacher" : "/student");
  }

  return (
    <main className="auth-page">
      <Link href="/" className="auth-brand" aria-label="返回 EduAgent 首页">
        <span className="auth-brand-mark">教</span>
        <span>
          <strong>EduAgent</strong>
          <small>陪伴式 AI 学习伙伴</small>
        </span>
      </Link>

      <section className="auth-shell" aria-labelledby="login-title">
        <div className="auth-story">
          <div className="auth-orbit" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <p className="auth-kicker">多 Agent 协作学习</p>
          <h1 id="login-title">进入你的学习工作台</h1>
          <p>
            登录后继续历史对话、作文批改、教材同步学习和个性化学习路径。AI 负责陪伴、追问与反馈，思考仍然属于学生。
          </p>
          <div className="auth-proof-grid">
            <span><strong>史料可追溯</strong><small>RAG 检索辅助理解</small></span>
            <span><strong>即时反馈</strong><small>练习、作文、辩论复盘</small></span>
            <span><strong>教师协同</strong><small>高风险评分人工确认</small></span>
          </div>
        </div>

        <div className="auth-card">
          <div className="auth-card-heading">
            <p className="auth-kicker">账号登录</p>
            <h2>欢迎回来</h2>
            <span>选择体验账号，或使用你的学号登录。</span>
          </div>

          <form className="auth-form" onSubmit={(event) => { event.preventDefault(); doLogin(username, password); }}>
            <label className="auth-field">
              <span>用户名 / 学号</span>
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="输入学号或用户名"
                required
                autoFocus
              />
            </label>
            <label className="auth-field">
              <span>密码</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="输入密码"
                required
              />
            </label>
            {error && <p className="auth-error">{error}</p>}
            <button className="auth-submit" type="submit" disabled={loading}>
              {loading ? "验证中..." : "登录工作台"}
            </button>
          </form>

          <div className="auth-divider"><span>快捷体验</span></div>

          <div className="auth-quick-grid">
            {quickAccounts.map((account) => (
              <button
                type="button"
                className={`auth-quick-card auth-quick-card-${account.role}${roleHint === account.role ? " suggested" : ""}`}
                key={account.username}
                disabled={loading}
                onClick={() => enterDemo(account)}
              >
                <small>{account.badge}</small>
                <strong>{account.label}</strong>
                <span>{account.description}</span>
                <em>{account.username}</em>
              </button>
            ))}
          </div>

          <p className="auth-footnote">
            还没有账号？<Link href="/register">创建学生账号</Link>
          </p>
        </div>
      </section>
    </main>
  );
}
