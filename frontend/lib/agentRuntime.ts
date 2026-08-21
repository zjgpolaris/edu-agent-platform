import type { SseEvent } from "@/lib/sse";

export type AgentRunClientState = {
  runId: string;
  runRevision: number;
  eventCursor: number;
  idempotencyKey: string;
  stepId?: string;
};

function integer(value: unknown): number | undefined {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : undefined;
}

export function createAgentRunIdempotencyKey(sessionId: string): string {
  const random = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  const session = sessionId.replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 48) || "anonymous";
  return `learning-assistant:${session}:${random}`.slice(0, 200);
}

export function runtimeCorrelationKey(
  kind: "confirm" | "cancel" | "resume",
  state: Pick<AgentRunClientState, "runId" | "runRevision">,
): string {
  return `${kind}:${state.runId}:${state.runRevision}`.slice(0, 200);
}

export function normalizeAgentRuntimeEvent<TData extends Record<string, unknown>>(
  event: SseEvent<TData>,
): SseEvent<Record<string, unknown>> {
  const envelope = event.data;
  const nested = envelope.data;
  if (
    typeof envelope.run_id === "string"
    && typeof envelope.event === "string"
    && nested
    && typeof nested === "object"
    && !Array.isArray(nested)
  ) {
    return {
      id: event.id || String(envelope.sequence ?? ""),
      event: envelope.event,
      data: {
        ...(nested as Record<string, unknown>),
        run_id: envelope.run_id,
        trace_id: envelope.trace_id,
        event_cursor: envelope.sequence,
      },
    };
  }
  return event;
}

export function mergeAgentRunClientState(
  current: AgentRunClientState | null,
  data: Record<string, unknown>,
  idempotencyKey: string,
  eventId?: string,
): AgentRunClientState | null {
  const runId = typeof data.run_id === "string" ? data.run_id : current?.runId;
  if (!runId) return current;
  const runRevision = integer(data.run_revision) ?? integer(data.revision) ?? current?.runRevision ?? 0;
  const eventCursor = integer(data.event_cursor)
    ?? integer(data.sequence)
    ?? integer(eventId ? Number(eventId) : undefined)
    ?? current?.eventCursor
    ?? 0;
  const stepId = typeof data.step_id === "string" ? data.step_id : current?.stepId;
  const next = {
    runId,
    runRevision,
    eventCursor,
    idempotencyKey: current?.idempotencyKey || idempotencyKey,
    ...(stepId ? { stepId } : {}),
  };
  if (
    current
    && current.runId === next.runId
    && current.runRevision === next.runRevision
    && current.eventCursor === next.eventCursor
    && current.idempotencyKey === next.idempotencyKey
    && current.stepId === next.stepId
  ) {
    return current;
  }
  return next;
}

export function replayEventToSse(event: Record<string, unknown>): SseEvent<Record<string, unknown>> | null {
  if (typeof event.event !== "string" || typeof event.run_id !== "string") return null;
  const data = event.data && typeof event.data === "object" && !Array.isArray(event.data)
    ? event.data as Record<string, unknown>
    : {};
  return {
    id: typeof event.sequence === "number" ? String(event.sequence) : undefined,
    event: event.event,
    data: {
      ...data,
      run_id: event.run_id,
      trace_id: event.trace_id,
      event_cursor: event.sequence,
    },
  };
}
