import { render, screen, waitFor } from "@testing-library/react";
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
});
