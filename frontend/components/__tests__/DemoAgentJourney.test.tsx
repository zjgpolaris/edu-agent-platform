import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DemoAgentJourney } from "../DemoAgentJourney";

describe("DemoAgentJourney", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders only the projected demo events returned by the session endpoint", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      enabled: true,
      session_id: "at_demo",
      status: "awaiting_answer",
      events: [{
        sequence: 1,
        phase: "reflect",
        label: "反思当前教学策略",
        status: "completed",
        summary: "发现当前回答存在概念混淆，需要调整讲解",
        decision_source: "deterministic_fallback",
      }],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    render(<DemoAgentJourney sessionId="at_demo" revision={1} token="token" />);

    expect(await screen.findByText("反思当前教学策略", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("发现当前回答存在概念混淆，需要调整讲解")).toBeInTheDocument();
    expect(screen.getByText("确定性安全降级")).toBeInTheDocument();
    expect(screen.queryByText("真实模型决策")).not.toBeInTheDocument();
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/autotutor/session/at_demo/demo-trace"),
      expect.objectContaining({ cache: "no-store" }),
    ));
  });

  it("shows a compatibility label for old sessions without provenance", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      enabled: true,
      session_id: "at_old",
      status: "awaiting_answer",
      events: [{ sequence: 1, phase: "plan", label: "制定计划", status: "completed", summary: "" }],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<DemoAgentJourney sessionId="at_old" revision={1} token="token" />);
    expect(await screen.findByText("来源未记录")).toBeInTheDocument();
  });

  it("ignores an old response after session changes and aborts on unmount", async () => {
    let finishOld!: (value: Response) => void;
    const response = (label: string) => new Response(JSON.stringify({ enabled: true, events: [
      { sequence: 1, phase: "plan", label, status: "completed", summary: "" },
    ] }), { status: 200 });
    const fetcher = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; }))
      .mockResolvedValueOnce(response("当前会话"));
    const view = render(<DemoAgentJourney sessionId="old" revision={0} token="token" />);
    const oldSignal = fetcher.mock.calls[0][1]?.signal;
    view.rerender(<DemoAgentJourney sessionId="new" revision={1} token="token" />);
    expect(await screen.findByText(/当前会话/)).toBeInTheDocument();
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => { finishOld(response("过期会话")); });
    expect(screen.queryByText(/过期会话/)).not.toBeInTheDocument();
    // A completed request has already removed its abort listener. Only an
    // in-flight request should receive cancellation when the view unmounts.
    fetcher.mockImplementationOnce(() => new Promise(() => {}));
    view.rerender(<DemoAgentJourney sessionId="pending" revision={2} token="token" />);
    view.unmount();
    expect(fetcher.mock.calls[2][1]?.signal?.aborted).toBe(true);
  });
});
