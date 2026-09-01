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
      }],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    render(<DemoAgentJourney sessionId="at_demo" revision={1} token="token" />);

    expect(await screen.findByText("反思当前教学策略", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("发现当前回答存在概念混淆，需要调整讲解")).toBeInTheDocument();
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/autotutor/session/at_demo/demo-trace"),
      expect.objectContaining({ cache: "no-store" }),
    ));
  });
});
