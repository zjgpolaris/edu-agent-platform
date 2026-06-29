"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { authHeaders, clientSessionHeaders } from "@/lib/auth";
import { useAuth } from "@/contexts/AuthContext";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type StudentProfile = {
  student_id: string;
  grade?: string | null;
  recent_topics?: string[];
  weak_topics?: string[];
  strong_topics?: string[];
  character_interests?: string[];
  updated_at?: string;
};

type LearningEvent = {
  id: string;
  student_id: string;
  feature: string;
  event_type: string;
  topic?: string | null;
  grade?: string | null;
  score?: number | null;
  success?: boolean | null;
  created_at: string;
  metadata?: Record<string, unknown>;
};

type MemoryEntry = {
  id: string;
  student_id: string;
  type: string;
  content: unknown;
  source_feature?: string | null;
  source_event_id?: string | null;
  confidence: number;
  status: "enabled" | "disabled" | "deleted" | string;
  reason?: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  last_used_at?: string | null;
  disabled_at?: string | null;
  deleted_at?: string | null;
};

type MemoryAuditEvent = {
  id: string;
  action: string;
  resource_type?: string | null;
  resource_id?: string | null;
  success: boolean;
  created_at: string;
  metadata?: Record<string, unknown>;
};

const featureLabels: Record<string, string> = {
  history_character: "历史人物对话",
  learning_assistant: "学习助手",
  quiz_practice: "练习测验",
  essay_grading: "作文批改",
  history_debate: "历史辩论",
  material_qa: "资料问答",
  textbook_learning: "教材学习",
  student_profile: "学生画像",
};

const eventTypeLabels: Record<string, string> = {
  quiz_completed: "测验完成",
  quiz_answer: "答题记录",
  weak_topic_detected: "薄弱点检测",
  strong_topic_confirmed: "掌握确认",
  character_chat: "角色对话",
  lesson_viewed: "课文浏览",
  tool_call: "工具调用",
};

const memoryTypeLabels: Record<string, string> = {
  weak_point: "薄弱点",
  interest: "兴趣",
  learning_preference: "学习偏好",
  recent_mistake: "近期错误",
  teacher_note: "教师备注",
  review_goal: "复习目标",
  recent_activity: "近期学习",
};

const auditLabels: Record<string, string> = {
  "memory.entries_read": "查看记忆",
  "memory.entry_disable": "禁用记忆",
  "memory.entry_enable": "启用记忆",
  "memory.entry_delete": "删除记忆",
  "memory.event_delete": "删除事件",
  "student_profile.read": "查看画像",
  "student_profile.review_plan": "生成复习计划",
  "student_profile.event_write": "写入学习事件",
};

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function formatMemoryValue(value: unknown): string {
  if (value == null || value === "") return "-";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.slice(0, 4).map(formatMemoryValue).join("、");
  return JSON.stringify(value).slice(0, 160);
}

function memoryReason(event: LearningEvent): string {
  if (event.feature === "learning_assistant") return "用于生成后续学习建议、弱点复习提示和工具选择观测。";
  if (event.feature === "history_character") return "用于记录历史人物兴趣，后续可个性化推荐对话对象。";
  if (event.score != null) return "用于判断掌握程度，并更新薄弱点或已掌握主题。";
  return "用于构建学生近期学习上下文。";
}

export default function MemoryCenterPage() {
  const { user } = useAuth();
  const studentId = user?.actorId || "";
  const token = user?.token || "";

  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [memoryEntries, setMemoryEntries] = useState<MemoryEntry[]>([]);
  const [events, setEvents] = useState<LearningEvent[]>([]);
  const [auditEvents, setAuditEvents] = useState<MemoryAuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [mutatingMemoryId, setMutatingMemoryId] = useState<string | null>(null);
  const [memoryStatus, setMemoryStatus] = useState<"enabled" | "disabled" | "all">("enabled");

  const loadMemoryData = useCallback(async (cancelledRef?: { cancelled: boolean }) => {
    if (!studentId || !token) { setLoading(false); return; }
    setLoading(true);
    setError("");
    try {
      const headers = { ...authHeaders(token), ...clientSessionHeaders() };
      const statusParam = memoryStatus === "all" ? "&status=all" : `&status=${memoryStatus}`;
      const [profileRes, memoryRes, eventsRes, auditRes] = await Promise.all([
        fetch(`${apiBaseUrl}/api/students/${studentId}/profile`, { headers }),
        fetch(`${apiBaseUrl}/api/students/${studentId}/memory-entries?limit=100${statusParam}`, { headers }),
        fetch(`${apiBaseUrl}/api/students/${studentId}/events?limit=100`, { headers }),
        fetch(`${apiBaseUrl}/api/students/${studentId}/memory-audit?limit=30`, { headers }),
      ]);
      const profileData = await profileRes.json().catch(() => ({}));
      const memoryData = await memoryRes.json().catch(() => ({}));
      const eventsData = await eventsRes.json().catch(() => ({}));
      const auditData = await auditRes.json().catch(() => ({}));
      if (cancelledRef?.cancelled) return;
      if (profileRes.ok) setProfile(profileData.profile ?? null);
      if (memoryRes.ok) setMemoryEntries(memoryData.memory_entries ?? []);
      if (eventsRes.ok) setEvents(eventsData.events ?? []);
      if (auditRes.ok) setAuditEvents(auditData.events ?? []);
      if (!profileRes.ok && !memoryRes.ok && !eventsRes.ok) setError(profileData.detail || memoryData.detail || "加载失败");
    } catch (err) {
      if (!cancelledRef?.cancelled) setError(err instanceof Error ? err.message : "加载失败，请稍后重试");
    } finally {
      if (!cancelledRef?.cancelled) setLoading(false);
    }
  }, [memoryStatus, studentId, token]);

  useEffect(() => {
    const state = { cancelled: false };
    void loadMemoryData(state);
    return () => { state.cancelled = true; };
  }, [loadMemoryData]);

  async function deleteEvent(eventId: string) {
    if (!studentId || !token) return;
    if (!window.confirm("确定删除这条学习事件记录吗？学生画像中的聚合字段不会自动回滚。")) return;
    setDeletingId(eventId);
    try {
      const res = await fetch(`${apiBaseUrl}/api/students/${studentId}/events/${eventId}`, {
        method: "DELETE",
        headers: { ...authHeaders(token), ...clientSessionHeaders() },
      });
      if (res.ok) {
        setEvents((prev) => prev.filter((e) => e.id !== eventId));
        setAuditEvents((prev) => [{
          id: `local-delete-${eventId}`,
          action: "memory.event_delete",
          resource_type: "student",
          resource_id: studentId,
          success: true,
          created_at: new Date().toISOString(),
          metadata: { event_id: eventId },
        }, ...prev]);
      } else {
        const data = await res.json().catch(() => ({}));
        alert(data.detail || "删除失败");
      }
    } finally {
      setDeletingId(null);
    }
  }

  async function updateMemoryStatus(memoryId: string, status: "enabled" | "disabled" | "deleted") {
    if (!studentId || !token) return;
    if (status === "deleted" && !window.confirm("确定删除这条记忆吗？删除后不会再用于 Agent 个性化。")) return;
    setMutatingMemoryId(memoryId);
    try {
      const res = await fetch(`${apiBaseUrl}/api/students/${studentId}/memory-entries/${memoryId}`, {
        method: status === "deleted" ? "DELETE" : "PATCH",
        headers: { "Content-Type": "application/json", ...authHeaders(token), ...clientSessionHeaders() },
        body: status === "deleted" ? undefined : JSON.stringify({ status, reason: "Memory Center 手动操作" }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        alert(data.detail || "操作失败");
        return;
      }
      if (status === "deleted") {
        setMemoryEntries((prev) => prev.filter((entry) => entry.id !== memoryId));
      } else if (data.memory_entry) {
        setMemoryEntries((prev) => prev.map((entry) => entry.id === memoryId ? data.memory_entry : entry));
      }
      setAuditEvents((prev) => [{
        id: `local-memory-${status}-${memoryId}`,
        action: status === "deleted" ? "memory.entry_delete" : status === "disabled" ? "memory.entry_disable" : "memory.entry_enable",
        resource_type: "student",
        resource_id: studentId,
        success: true,
        created_at: new Date().toISOString(),
        metadata: { memory_id: memoryId },
      }, ...prev]);
    } finally {
      setMutatingMemoryId(null);
    }
  }

  return (
    <main className="academy-shell material-library-shell">
      <section className="academy-hero material-upload-hero">
        <div className="hero-copy">
          <span className="eyebrow">Memory Center</span>
          <h1>学习记忆中心</h1>
          <p>查看 Agent 记住的学习画像、长期记忆与学习事件，了解哪些内容影响了回答，并可禁用或删除不准确的记忆。</p>
          <div className="hero-flow">
            <span>学生画像</span>
            <span>Typed Memory</span>
            <span>学习事件</span>
            <span>Audit Log</span>
          </div>
        </div>
        <aside className="teaching-card material-ink-card">
          <span className="seal-mark">忆</span>
          <strong>记忆可解释</strong>
          <p>每条长期记忆都有类型、来源、置信度与最近使用时间；禁用后将不会再用于个性化回答。</p>
        </aside>
      </section>

      {!user && (
        <section className="panel material-library-panel">
          <div className="material-empty-state">
            <strong>请先登录</strong>
            <p>需要登录才能查看学习记忆。</p>
            <Link className="primary-link" href="/login">去登录</Link>
          </div>
        </section>
      )}

      {user && (
        <>
          {loading && (
            <section className="panel material-library-panel">
              <p className="empty-hint">正在加载记忆数据...</p>
            </section>
          )}
          {error && (
            <section className="panel material-library-panel">
              <div className="error-card"><p>{error}</p></div>
            </section>
          )}

          {!loading && !error && profile && (
            <section className="panel material-library-panel">
              <div className="panel-heading-row">
                <div>
                  <p className="section-kicker">STUDENT PROFILE</p>
                  <h2>学生画像</h2>
                </div>
                <small style={{ color: "var(--ink-light)", fontSize: 13 }}>
                  更新于 {formatDate(profile.updated_at)}
                </small>
              </div>
              <div className="memory-profile-grid">
                <div className="memory-profile-card">
                  <span>薄弱点</span>
                  {(profile.weak_topics ?? []).length > 0
                    ? (profile.weak_topics ?? []).map((t) => <em key={t}>{t}</em>)
                    : <p>暂无记录</p>}
                </div>
                <div className="memory-profile-card">
                  <span>已掌握</span>
                  {(profile.strong_topics ?? []).length > 0
                    ? (profile.strong_topics ?? []).map((t) => <em key={t}>{t}</em>)
                    : <p>暂无记录</p>}
                </div>
                <div className="memory-profile-card">
                  <span>最近主题</span>
                  {(profile.recent_topics ?? []).length > 0
                    ? (profile.recent_topics ?? []).slice(0, 6).map((t) => <em key={t}>{t}</em>)
                    : <p>暂无记录</p>}
                </div>
                <div className="memory-profile-card">
                  <span>感兴趣人物</span>
                  {(profile.character_interests ?? []).length > 0
                    ? (profile.character_interests ?? []).map((t) => <em key={t}>{t}</em>)
                    : <p>暂无记录</p>}
                </div>
              </div>
            </section>
          )}

          {!loading && !error && (
            <section className="panel material-library-panel">
              <div className="panel-heading-row">
                <div>
                  <p className="section-kicker">TYPED MEMORY ENTRIES</p>
                  <h2>长期记忆 <small style={{ fontWeight: 400, fontSize: 18 }}>({memoryEntries.length})</small></h2>
                </div>
                <div className="memory-filter-row">
                  <button className={memoryStatus === "enabled" ? "active" : ""} type="button" onClick={() => setMemoryStatus("enabled")}>启用中</button>
                  <button className={memoryStatus === "disabled" ? "active" : ""} type="button" onClick={() => setMemoryStatus("disabled")}>已禁用</button>
                  <button className={memoryStatus === "all" ? "active" : ""} type="button" onClick={() => setMemoryStatus("all")}>全部</button>
                </div>
              </div>

              {memoryEntries.length === 0 ? (
                <div className="material-empty-state">
                  <strong>还没有长期记忆</strong>
                  <p>学习助手、历史人物对话和测验会逐步沉淀可解释的 typed memory。</p>
                  <Link className="primary-link" href="/learning-assistant">打开学习助手</Link>
                </div>
              ) : (
                <div className="memory-entry-grid">
                  {memoryEntries.map((entry) => (
                    <article className={`memory-entry-card ${entry.status}`} key={entry.id}>
                      <div className="memory-entry-topline">
                        <span>{memoryTypeLabels[entry.type] ?? entry.type}</span>
                        <em>{entry.status === "enabled" ? "启用中" : entry.status === "disabled" ? "已禁用" : "已删除"}</em>
                      </div>
                      <strong>{formatMemoryValue(entry.content)}</strong>
                      {entry.reason && <p>{entry.reason}</p>}
                      <div className="memory-entry-metrics">
                        <span>来源：{featureLabels[entry.source_feature ?? ""] ?? entry.source_feature ?? "—"}</span>
                        <span>置信度：{Math.round((entry.confidence ?? 0) * 100)}%</span>
                        <span>创建：{formatDate(entry.created_at)}</span>
                        <span>最近使用：{formatDate(entry.last_used_at)}</span>
                      </div>
                      <div className="memory-entry-id">{entry.id}</div>
                      <div className="memory-entry-actions">
                        {entry.status === "enabled" ? (
                          <button type="button" disabled={mutatingMemoryId === entry.id} onClick={() => void updateMemoryStatus(entry.id, "disabled")}>禁用</button>
                        ) : entry.status === "disabled" ? (
                          <button type="button" disabled={mutatingMemoryId === entry.id} onClick={() => void updateMemoryStatus(entry.id, "enabled")}>启用</button>
                        ) : null}
                        {entry.status !== "deleted" && (
                          <button type="button" className="danger" disabled={mutatingMemoryId === entry.id} onClick={() => void updateMemoryStatus(entry.id, "deleted")}>删除</button>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
          )}

          {!loading && !error && (
            <section className="panel material-library-panel">
              <div className="panel-heading-row">
                <div>
                  <p className="section-kicker">LEARNING EVENTS</p>
                  <h2>学习事件记录 <small style={{ fontWeight: 400, fontSize: 18 }}>({events.length})</small></h2>
                </div>
              </div>

              {events.length === 0 ? (
                <div className="material-empty-state">
                  <strong>还没有学习记录</strong>
                  <p>开始使用学习助手、练习测验或历史对话后，学习事件会自动记录在这里。</p>
                  <Link className="primary-link" href="/learning-assistant">打开学习助手</Link>
                </div>
              ) : (
                <div className="memory-events-list">
                  {events.map((event) => (
                    <div className="memory-event-row" key={event.id}>
                      <div className="memory-event-main">
                        <div className="memory-event-header">
                          <strong>{featureLabels[event.feature] ?? event.feature}</strong>
                          <em>{eventTypeLabels[event.event_type] ?? event.event_type}</em>
                          {event.topic && <span>{event.topic}</span>}
                          {event.score != null && (
                            <span className={event.score >= 0.7 ? "memory-score-good" : "memory-score-weak"}>
                              {Math.round(event.score * 100)}%
                            </span>
                          )}
                        </div>
                        <small>{formatDate(event.created_at)}{event.grade ? ` · ${event.grade}` : ""}</small>
                        <p className="memory-event-reason">{memoryReason(event)}</p>
                        <div className="memory-event-metadata">
                          {event.metadata?.trace_id != null && <span>trace: {formatMemoryValue(event.metadata.trace_id)}</span>}
                          {event.metadata?.intent != null && <span>intent: {formatMemoryValue(event.metadata.intent)}</span>}
                          {event.metadata?.tool_name != null && <span>tool: {formatMemoryValue(event.metadata.tool_name)}</span>}
                          {event.metadata?.reason != null && <span>reason: {formatMemoryValue(event.metadata.reason)}</span>}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="memory-delete-btn"
                        disabled={deletingId === event.id}
                        onClick={() => void deleteEvent(event.id)}
                        aria-label="删除此记录"
                      >
                        {deletingId === event.id ? "..." : "删除事件"}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}

          {!loading && !error && (
            <section className="panel material-library-panel">
              <div className="panel-heading-row">
                <div>
                  <p className="section-kicker">AUDIT TRAIL</p>
                  <h2>记忆审计日志 <small style={{ fontWeight: 400, fontSize: 18 }}>({auditEvents.length})</small></h2>
                </div>
              </div>
              {auditEvents.length === 0 ? (
                <p className="empty-hint">暂无记忆相关审计事件。</p>
              ) : (
                <div className="memory-audit-list">
                  {auditEvents.map((event) => (
                    <div className={`memory-audit-row ${event.success ? "success" : "failed"}`} key={event.id}>
                      <div>
                        <strong>{auditLabels[event.action] ?? event.action}</strong>
                        <small>{formatDate(event.created_at)}{event.resource_type ? ` · ${event.resource_type}` : ""}</small>
                      </div>
                      <div className="memory-event-metadata">
                        <span>{event.success ? "success" : "failed"}</span>
                        {event.metadata?.trace_id != null && <span>trace: {formatMemoryValue(event.metadata.trace_id)}</span>}
                        {event.metadata?.tool_name != null && <span>tool: {formatMemoryValue(event.metadata.tool_name)}</span>}
                        {event.metadata?.memory_id != null && <span>memory: {formatMemoryValue(event.metadata.memory_id)}</span>}
                        {event.metadata?.event_id != null && <span>event: {formatMemoryValue(event.metadata.event_id)}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}
        </>
      )}
    </main>
  );
}
