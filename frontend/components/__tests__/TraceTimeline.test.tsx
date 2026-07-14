import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { TraceTimeline } from "../TraceTimeline"

afterEach(() => vi.restoreAllMocks())

describe("TraceTimeline", () => {
  it("renders nothing and does not request data without a trace id", () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
    const { container } = render(<TraceTimeline traceId={null} />)

    expect(container).toBeEmptyDOMElement()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("loads trace events with authorization and renders RAG details", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        events: [{
          trace_id: "trace-1",
          agent_name: "history_agent",
          step_name: "retrieve_context",
          event_type: "tool_result",
          status: "success",
          latency_ms: 42,
          timestamp: "2026-07-14T00:00:00Z",
          metadata: {
            rag_inspector: {
              original_query: "辛亥革命",
              retrieval_strategy: "hybrid",
              source_count: 3,
              top_score: 0.91,
            },
          },
        }],
      }), { status: 200 }),
    )

    render(<TraceTimeline traceId="trace-1" token="secret-token" />)

    expect(screen.getByText("加载中...")).toBeInTheDocument()
    expect(await screen.findByText("retrieve_context")).toBeInTheDocument()
    expect(screen.getByText("42ms")).toBeInTheDocument()
    expect(screen.getByText("RAG Inspector")).toBeInTheDocument()
    expect(screen.getByText("query: 辛亥革命")).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/traces/trace-1",
      { headers: { Authorization: "Bearer secret-token" } },
    )
  })

  it("shows a request failure instead of stale trace content", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 503 }))

    render(<TraceTimeline traceId="trace-failed" />)

    await waitFor(() => {
      expect(screen.getByText("加载失败: Failed to fetch trace")).toBeInTheDocument()
    })
    expect(screen.queryByText("暂无轨迹数据")).not.toBeInTheDocument()
  })
})
