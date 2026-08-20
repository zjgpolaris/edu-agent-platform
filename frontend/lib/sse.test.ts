import { describe, expect, it } from "vitest";

import { parseSseFrame } from "./sse";

describe("shared SSE parser", () => {
  it("parses runtime event ids for cursor replay", () => {
    const event = parseSseFrame<{ run_id: string; sequence: number }>(
      ': keepalive\r\nid: 17\r\nevent: step_completed\r\ndata: {"run_id":"run-1",\r\ndata: "sequence":17}\r\n',
    );

    expect(event).toEqual({
      id: "17",
      event: "step_completed",
      data: { run_id: "run-1", sequence: 17 },
    });
  });

  it("ignores heartbeat frames without data", () => {
    expect(parseSseFrame(": heartbeat\n\n")).toBeNull();
  });
});
