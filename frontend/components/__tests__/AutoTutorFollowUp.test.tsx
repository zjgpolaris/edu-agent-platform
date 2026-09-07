import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AutoTutorFollowUp } from "../AutoTutorFollowUp";
const response = (status: string) => new Response(JSON.stringify({ follow_up: { status, objective_label: "洋务运动目的", due_at: "2030-01-01T03:00:00Z" } }));
afterEach(() => vi.restoreAllMocks());

describe("AutoTutorFollowUp", () => {
  it("separates immediate evidence from missing retention content", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response("content_blocked"));
    render(<AutoTutorFollowUp sessionId="one" revision={3} token="token" />);
    expect(await screen.findByText(/课内检验已通过，延迟复测暂缺独立题/)).toBeInTheDocument();
    expect(screen.queryByText(/间隔复测通过，留存证据已记录/)).not.toBeInTheDocument();
  });
  it("retries failed state reads independently", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(response("scheduled"));
    render(<AutoTutorFollowUp sessionId="one" revision={3} token="token" />);
    fireEvent.click(await screen.findByRole("button", { name: "重试复测状态" }));
    expect(await screen.findByText(/等待间隔复测/)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("aborts old identity requests and discards late results", async () => {
    let finish!: (r: Response) => void;
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockResolvedValueOnce(response("superseded"));
    const view = render(<AutoTutorFollowUp sessionId="old" revision={3} token="old" />);
    const signal = fetcher.mock.calls[0][1]?.signal;
    view.rerender(<AutoTutorFollowUp sessionId="new" revision={4} token="new" allowReview={false} />);
    expect(await screen.findByText(/已有新的学习证据/)).toBeInTheDocument();
    expect(signal?.aborted).toBe(true);
    await act(async () => { finish(response("retention_verified")); });
    expect(screen.queryByText(/留存证据已记录/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
