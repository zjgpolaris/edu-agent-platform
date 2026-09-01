"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AutoTutorEvidenceCard, type AutoTutorEvidence } from "@/components/AutoTutorEvidenceCard";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

function TeacherEvidenceInner() {
  const { user } = useAuth();
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("session_id") || "";
  const [data, setData] = useState<AutoTutorEvidence | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "forbidden" | "missing" | "error">("idle");

  useEffect(() => {
    if (!sessionId || !user?.token) return;
    const controller = new AbortController();
    setStatus("loading");
    setData(null);
    fetch(`${API}/api/autotutor/session/${encodeURIComponent(sessionId)}/evidence`, {
      headers: authHeaders(user.token),
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (response.status === 403) throw new Error("forbidden");
        if (response.status === 404) throw new Error("missing");
        if (!response.ok) throw new Error("error");
        return response.json() as Promise<AutoTutorEvidence>;
      })
      .then((payload) => {
        setData(payload);
        setStatus("idle");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        const message = error instanceof Error ? error.message : "error";
        setStatus(message === "forbidden" ? "forbidden" : message === "missing" ? "missing" : "error");
      });
    return () => controller.abort();
  }, [sessionId, user?.token]);

  return (
    <main className="academy-shell">
      <section className="academy-hero">
        <div className="eyebrow">Teacher Evidence View</div>
        <h1>本次 Agent 辅导证据</h1>
        <p>按会话核对学生经历的反思、重规划、退出票和掌握证据，不展示答案、提示词或原始运行轨迹。</p>
      </section>
      {!sessionId ? <section className="panel" role="status"><h2>等待选择会话</h2><p>请从学生 AutoTutor 完成页点击“切换教师视角查看证据”。</p></section> : null}
      {status === "loading" ? <section className="panel" role="status">正在读取会话证据…</section> : null}
      {status === "forbidden" ? <section className="panel" role="alert"><h2>无权查看</h2><p>该学生不在当前教师的班级或作业范围内。</p></section> : null}
      {status === "missing" ? <section className="panel" role="alert"><h2>证据不存在</h2><p>会话可能已过期或未成功创建。</p></section> : null}
      {status === "error" ? <section className="panel" role="alert"><h2>证据暂不可用</h2><p>请稍后重试，班级其他功能不受影响。</p></section> : null}
      {data ? <AutoTutorEvidenceCard data={data} /> : null}
      <div className="learning-suggestion-row" style={{ marginTop: 16 }}>
        <Link href="/teacher/class-analytics">查看班级学情聚合</Link>
        <Link href="/teacher">返回教师总览</Link>
      </div>
    </main>
  );
}

export default function TeacherEvidencePage() {
  return (
    <Suspense fallback={<main className="academy-shell" aria-busy="true" />}>
      <TeacherEvidenceInner />
    </Suspense>
  );
}
