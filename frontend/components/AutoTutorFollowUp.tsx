"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchApiJson } from "@/lib/api";

type FollowUp = { status: string; objective_label: string; due_at: string | null };
const messages: Record<string, string> = {
  not_scheduled: "本节尚未安排间隔复测。",
  scheduled: "本节已通过独立检验，等待间隔复测；到期后仍需核验是否有合适的独立题。",
  due: "已到最早复测时间，请进入今日复习核验可用题目。",
  content_blocked: "课内检验已通过，延迟复测暂缺独立题。原学习证据已保留。",
  retention_verified: "间隔复测通过，留存证据已记录。",
  needs_retrieval: "间隔复测尚未通过，需要重新巩固；原课内检验结果已保留。",
  superseded: "此目标已有新的学习证据，本节不展示其他课程的复测结果。",
  unavailable: "暂时无法关联本节课的后续复测证据。",
};
const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export function AutoTutorFollowUp({ sessionId, revision, token, allowReview = true }: { sessionId: string; revision: number; token: string; allowReview?: boolean }) {
  const [data, setData] = useState<FollowUp | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setData(null); setError(false);
    fetchApiJson<{ follow_up: FollowUp }>(`${API}/api/autotutor/session/${encodeURIComponent(sessionId)}/follow-up`, {
      token, signal: controller.signal, timeoutMs: 5000, cache: "no-store",
    }).then(result => { if (active) setData(result.follow_up); }).catch(() => { if (active) setError(true); });
    return () => { active = false; controller.abort(); };
  }, [sessionId, revision, token, attempt]);
  return <section aria-label="课后复测状态" className="panel" style={{ padding: 16, marginTop: 12 }}>
    <h3>课后间隔复测</h3>
    {error ? <p role="status">复测状态暂不可用，原课程证据仍可查看。</p>
      : !data ? <p role="status">正在读取复测状态…</p>
      : <><p>{messages[data.status] || messages.unavailable}</p>
        {data.due_at && Number.isFinite(Date.parse(data.due_at)) ? <p>最早复测时间：{new Date(data.due_at).toLocaleString("zh-CN", { hour12: false })}</p> : null}
        {allowReview && ["scheduled", "due", "content_blocked", "needs_retrieval"].includes(data.status) ? <Link href="/student/review">查看今日复习安排</Link> : null}</>}
    <button type="button" disabled={!data && !error} onClick={() => setAttempt(a => a + 1)}>{error ? "重试复测状态" : "刷新复测状态"}</button>
  </section>;
}
