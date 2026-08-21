import { describe, expect, it } from "vitest";

import {
  createAgentRunIdempotencyKey,
  mergeAgentRunClientState,
  normalizeAgentRuntimeEvent,
  replayEventToSse,
  runtimeCorrelationKey,
} from "./agentRuntime";

describe("Agent Runtime client contract", () => {
  it("keeps one idempotency key while revisions and cursors advance", () => {
    const first = mergeAgentRunClientState(null, {
      run_id: "run-1",
      run_revision: 2,
      event_cursor: 3,
    }, "request-key-1");
    const next = mergeAgentRunClientState(first, {
      run_id: "run-1",
      run_revision: 4,
      event_cursor: 7,
      step_id: "step-1",
    }, "ignored-key");

    expect(next).toEqual({
      runId: "run-1",
      runRevision: 4,
      eventCursor: 7,
      idempotencyKey: "request-key-1",
      stepId: "step-1",
    });
    expect(runtimeCorrelationKey("confirm", next!)).toBe("confirm:run-1:4");
  });

  it("normalizes persisted v2 envelopes and replay records", () => {
    expect(normalizeAgentRuntimeEvent({
      event: "step_completed",
      data: {
        schema_version: 2,
        run_id: "run-2",
        trace_id: "trace-2",
        sequence: 9,
        event: "step_completed",
        data: { step_id: "step-2" },
      },
    })).toEqual({
      id: "9",
      event: "step_completed",
      data: { step_id: "step-2", run_id: "run-2", trace_id: "trace-2", event_cursor: 9 },
    });
    expect(replayEventToSse({
      run_id: "run-2",
      trace_id: "trace-2",
      sequence: 10,
      event: "run_completed",
      data: { completion: { status: "completed" } },
    })?.data.event_cursor).toBe(10);
  });

  it("creates bounded request keys", () => {
    const key = createAgentRunIdempotencyKey("session with spaces");
    expect(key.startsWith("learning-assistant:sessionwithspaces:")).toBe(true);
    expect(key.length).toBeLessThanOrEqual(200);
  });
});
