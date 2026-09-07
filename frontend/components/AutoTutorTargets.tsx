"use client";

import { useEffect, useRef, useState } from "react";
import { authHeaders } from "@/lib/auth";
import { fetchApiJson } from "@/lib/api";

type Target = { objective_id: string; label: string; grade: string | null; launchable: boolean };
type Catalog = { items: Target[] };

export function AutoTutorTargets({ apiBase, token, disabled, onSelect }: {
  apiBase: string; token: string; disabled: boolean; onSelect: (label: string) => boolean;
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const selecting = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setCatalog(null); setError(false); selecting.current = false;
    fetchApiJson<Catalog>(`${apiBase}/api/autotutor/targets`, {
      headers: authHeaders(token), timeoutMs: 5000, signal: controller.signal,
    }).then(data => { if (active) setCatalog(data); }).catch(() => { if (active) setError(true); });
    return () => { active = false; controller.abort(); };
  }, [apiBase, token, attempt]);
  return <section aria-label="选择学习目标" className="teaching-card">
    <h3>选择学习目标</h3>
    <p>也可以从有审核教材支持的目标开始。不同册次已标明。</p>
    {error ? <p role="status">目标目录暂不可用，已开始的课程可继续。<button type="button" onClick={() => setAttempt(a => a + 1)}>重试目标目录</button></p>
      : !catalog ? <p role="status">正在读取学习目标…</p>
      : catalog.items.length === 0 ? <p>暂无可用目标，请稍后重试或进入随问。</p>
      : <div className="learning-suggestion-row">{catalog.items.map(item => <button type="button" key={item.objective_id}
        disabled={disabled || !item.launchable} onClick={() => {
          if (selecting.current || disabled) return;
          selecting.current = true;
          if (!onSelect(item.label)) selecting.current = false;
        }}>
        {item.label} · {item.grade || "册次未标明"}{!item.launchable ? " · 内容待补充" : ""}
      </button>)}</div>}
  </section>;
}

export type PlanningDecision = { revision: number; reason_code: string | null; skipped_count: number; launchable: boolean };

export function AutoTutorPlanningSummary({ decision }: { decision?: PlanningDecision | null }) {
  if (!decision) return null;
  const message = !decision.launchable ? "本次目标暂缺可用的教材或独立检验内容，尚未改变掌握记录。"
    : decision.reason_code === "explicit_focus" ? "按你指定的目标安排本节课。"
    : decision.reason_code === "lower_difficulty_available" ? "保持学习目标，先用当前可用的较低难度练习。"
    : decision.reason_code === "default_available" ? "暂无学情，从当前册次有教材支持的目标开始。"
    : "优先巩固有教材支持的薄弱点。";
  return <p aria-label="目标安排说明">{message}{decision.skipped_count > 0 ? ` 另有 ${decision.skipped_count} 个候选目标暂不可用，已保留待后续学习。` : ""}</p>;
}
