import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { ToolConfirmationDialog } from "../ToolConfirmationDialog"

describe("ToolConfirmationDialog", () => {
  it("shows the tool risk and authorization details", () => {
    render(
      <ToolConfirmationDialog
        toolName="delete_assignment"
        message="此操作不可撤销"
        riskLevel="high"
        sideEffect="删除作业及提交记录"
        requiredRole="teacher"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByRole("heading", { name: "确认执行高风险工具" })).toBeInTheDocument()
    expect(screen.getByText("工具：delete_assignment")).toBeInTheDocument()
    expect(screen.getByText("此操作不可撤销")).toBeInTheDocument()
    expect(screen.getByText("high")).toHaveClass("risk-high")
    expect(screen.getByText("影响：删除作业及提交记录")).toBeInTheDocument()
    expect(screen.getByText("需要角色：teacher")).toBeInTheDocument()
  })

  it("does not render optional details when they are absent", () => {
    const { container } = render(
      <ToolConfirmationDialog
        toolName="read_profile"
        message="确认读取学生档案"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(container.querySelector(".risk-badge")).not.toBeInTheDocument()
    expect(container.querySelector(".side-effect")).not.toBeInTheDocument()
    expect(container.querySelector(".required-role")).not.toBeInTheDocument()
  })

  it("calls the matching action callback", async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(
      <ToolConfirmationDialog
        toolName="publish_report"
        message="确认发布报告"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )

    await user.click(screen.getByRole("button", { name: "确认执行" }))
    await user.click(screen.getByRole("button", { name: "取消" }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})
