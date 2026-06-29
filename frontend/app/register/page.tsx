"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";

export default function RegisterPage() {
  const { register } = useAuth();
  const router = useRouter();
  const [studentId, setStudentId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function doRegister(event: React.FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError("两次密码不一致");
      return;
    }

    setError("");
    setLoading(true);
    try {
      await register(studentId, password, displayName || undefined);
      router.push("/student-home");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "注册失败");
    } finally {
      setLoading(false);
    }
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

      <section className="auth-shell register-shell" aria-labelledby="register-title">
        <div className="auth-story">
          <p className="auth-kicker">学生账号</p>
          <h1 id="register-title">创建你的学习档案</h1>
          <p>
            注册后系统会持续记录练习、提问、作文批改和教材学习轨迹，用于生成更贴近你的复习路径。
          </p>
          <div className="auth-step-list">
            <span><strong>1</strong> 建立学生身份</span>
            <span><strong>2</strong> 进入学习工作台</span>
            <span><strong>3</strong> 沉淀个性化路径</span>
          </div>
        </div>

        <div className="auth-card">
          <div className="auth-card-heading">
            <p className="auth-kicker">开始使用</p>
            <h2>创建学生账号</h2>
            <span>教师账号由平台预置，这里仅开放学生注册。</span>
          </div>

          <form className="auth-form" onSubmit={doRegister}>
            <label className="auth-field">
              <span>学号</span>
              <input
                value={studentId}
                onChange={(event) => setStudentId(event.target.value)}
                placeholder="输入学号，登录时使用"
                required
                autoFocus
              />
            </label>
            <label className="auth-field">
              <span>姓名</span>
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="选填，便于老师识别"
              />
            </label>
            <label className="auth-field">
              <span>密码</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="至少 6 位"
                required
                minLength={6}
              />
            </label>
            <label className="auth-field">
              <span>确认密码</span>
              <input
                type="password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                placeholder="再次输入密码"
                required
              />
            </label>
            {error && <p className="auth-error">{error}</p>}
            <button className="auth-submit" type="submit" disabled={loading}>
              {loading ? "创建中..." : "创建并进入学习"}
            </button>
          </form>

          <p className="auth-footnote">
            已有账号？<Link href="/login">返回登录</Link>
          </p>
        </div>
      </section>
    </main>
  );
}
