"use client"

import { useState, useEffect } from "react"

interface TraceEvent {
  trace_id: string
  agent_name: string
  step_name: string
  event_type: string
  status: string
  latency_ms?: number
  metadata?: Record<string, any>
  timestamp: string
}

interface TraceTimelineProps {
  traceId: string | null
  token?: string
}

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"

export function TraceTimeline({ traceId, token }: TraceTimelineProps) {
  const [events, setEvents] = useState<TraceEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!traceId) {
      setEvents([])
      return
    }

    setLoading(true)
    setError(null)

    fetch(`${apiBaseUrl}/api/traces/${traceId}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
      .then(res => {
        if (!res.ok) throw new Error("Failed to fetch trace")
        return res.json()
      })
      .then(data => setEvents(data.events || []))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [traceId, token])

  if (!traceId) return null

  return (
    <div className="trace-timeline">
      <h3>Agent 执行轨迹</h3>
      {loading ? (
        <p className="loading">加载中...</p>
      ) : error ? (
        <p className="error">加载失败: {error}</p>
      ) : events.length === 0 ? (
        <p className="empty">暂无轨迹数据</p>
      ) : (
        <div className="timeline">
          {events.map((event, i) => (
            <div key={i} className={`timeline-item status-${event.status}`}>
              <div className="step-name">{event.step_name}</div>
              <div className="event-type">{event.event_type}</div>
              {event.latency_ms && (
                <div className="latency">{event.latency_ms}ms</div>
              )}
              {event.metadata && Object.keys(event.metadata).length > 0 && (
                <details className="metadata">
                  <summary>详情</summary>
                  <div className="metadata-content">
                    {Object.entries(event.metadata).map(([k, v]) => (
                      <div key={k} className="metadata-item">
                        <span className="key">{k}:</span>
                        <span className="value">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
