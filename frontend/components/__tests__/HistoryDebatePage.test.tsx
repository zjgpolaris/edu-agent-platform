import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import HistoryDebatePage from "../../app/history-debate/page"

afterEach(() => vi.restoreAllMocks())

describe("HistoryDebatePage", () => {
  it("leaves the running state and shows the SSE error message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response('event: error\ndata: {"message":"辩论生成失败，请稍后重试。"}\n\n', {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    )

    render(<HistoryDebatePage />)
    fireEvent.change(screen.getByPlaceholderText("输入辩题，如：秦始皇统一六国利大于弊"), {
      target: { value: "测试辩题" },
    })
    fireEvent.click(screen.getByRole("button", { name: "开始辩论" }))

    expect(await screen.findByText("辩论生成失败，请稍后重试。")).toBeInTheDocument()
    expect(screen.queryByText("运行中…")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "开始辩论" })).toBeInTheDocument()
  })
})
