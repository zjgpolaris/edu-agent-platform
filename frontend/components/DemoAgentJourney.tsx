"use client";

import { useEffect, useState } from "react";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export type DemoJourneyEvent = {
  sequence: number;
  phase: string;
  label: string;
  status: "completed" | "waiting" | "failed" | "degraded" | "blocked";
  summary: string;
  duration_ms?: number | null;
  decision_source?: "policy" | "tool" | "langchain_primary" | "langchain_fallback_profile" | "deterministic_fallback" | "evidence_store" | null;
  model?: {
    provider?: string | null;
    profile?: string | null;
    name?: string | null;
    fallback_used?: boolean;
  } | null;
};

type DemoJourneyResponse = {
  enabled: boolean;
  session_id: string;
  status: string;
  events: DemoJourneyEvent[];
};

const STATUS_LABEL: Record<DemoJourneyEvent["status"], string> = {
  completed: "已完成",
  waiting: "进行中",
  failed: "未通过",
  degraded: "已降级",
  blocked: "已阻断",
};

const DECISION_SOURCE_LABEL: Record<NonNullable<DemoJourneyEvent["decision_source"]>, string> = {
  policy: "受限策略执行",
  tool: "工具检索与核验",
  langchain_primary: "真实模型决策",
  langchain_fallback_profile: "备用模型完成",
  deterministic_fallback: "确定性安全降级",
  evidence_store: "学习证据写入",
};

function decisionSourceLabel(source: DemoJourneyEvent["decision_source"]): string {
  return source ? DECISION_SOURCE_LABEL[source] || "来源未记录" : "来源未记录";
}

export function DemoAgentJourney({ sessionId, revision, token }: { sessionId: string; revision: number; token: string }) {
  const [data, setData] = useState<DemoJourneyResponse | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setUnavailable(false);
    fetch(`${API}/api/autotutor/session/${encodeURIComponent(sessionId)}/demo-trace`, {
      headers: authHeaders(token),
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json() as Promise<DemoJourneyResponse>;
      })
      .then((payload) => setData(payload))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setUnavailable(true);
      });
    return () => controller.abort();
  }, [sessionId, revision, token]);

  return (
    <aside className="panel learning-observation-panel" aria-label="Agent 演示旅程">
      <div className="panel-kicker">Agent Journey</div>
      <h2>Agent 如何做决定</h2>
      <p style={{ color: "var(--muted)", fontSize: 12, lineHeight: 1.6 }}>
        这里只展示当前辅导会话的脱敏决策，不包含提示词、模型原文或其他学生数据。
      </p>
      {unavailable ? (
        <p role="status" style={{ color: "var(--muted)", fontSize: 13 }}>决策轨迹暂不可用，辅导仍可继续。</p>
      ) : (
        <ol className="learning-runtime-list" style={{ maxHeight: 520, overflowY: "auto", padding: 0, listStyle: "none" }}>
          {(data?.events || []).map((event) => (
            <li className={`learning-runtime-step ${event.status}`} key={`${event.sequence}-${event.phase}`}>
              <div className="learning-runtime-step-head">
                <span>{event.sequence}. {event.label}</span>
                <strong>{STATUS_LABEL[event.status]}</strong>
              </div>
              <div className="learning-runtime-chips" aria-label="决策来源">
                <small>{decisionSourceLabel(event.decision_source)}</small>
                {event.model?.name ? <small>{event.model.profile || event.model.provider || "模型"} · {event.model.name}</small> : null}
              </div>
              {event.summary ? <p className="learning-runtime-summary">{event.summary}</p> : null}
              {event.duration_ms != null ? <em>{Math.round(event.duration_ms)}ms</em> : null}
            </li>
          ))}
          {!data?.events.length ? <li style={{ color: "var(--muted)", fontSize: 13 }}>正在等待 Agent 产生第一步决策…</li> : null}
        </ol>
      )}
    </aside>
  );
}
