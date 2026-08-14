export type TextbookContextFields = {
  grade: string;
  bookId: string;
  lessonId: string;
};

export function buildTextbookRequestFields(context: TextbookContextFields | null) {
  return {
    grade: context?.grade || null,
    book_id: context?.bookId || null,
    lesson_id: context?.lessonId || null,
  };
}

export function shouldSubmitComposerKey(event: { key: string; shiftKey: boolean; isComposing: boolean }) {
  return event.key === "Enter" && !event.shiftKey && !event.isComposing;
}

export type AssistantPlanStep = {
  step_id: string;
  title: string;
  kind?: "tool" | "generation";
  operation?: string;
  sequence?: number;
  status: "pending" | "running" | "waiting_confirmation" | "completed" | "failed" | "cancelled";
  result_summary?: string | null;
  latency_ms?: number | null;
};

export function updateAssistantPlanStep(
  steps: AssistantPlanStep[],
  event: Partial<AssistantPlanStep> & Pick<AssistantPlanStep, "step_id">,
): AssistantPlanStep[] {
  const definedEvent = Object.fromEntries(Object.entries(event).filter(([, value]) => value !== undefined)) as Partial<AssistantPlanStep> & Pick<AssistantPlanStep, "step_id">;
  return steps.map((step) => step.step_id === event.step_id ? { ...step, ...definedEvent } : step);
}

export function assistantCompletionLabel(status?: string) {
  if (status === "partial") return "已完成部分学习任务";
  if (status === "needs_clarification") return "等待补充信息";
  if (status === "waiting_confirmation") return "等待确认";
  if (status === "failed") return "任务未完成";
  return "已完成";
}

export function dedupeAssistantTools<T extends { tool_name: string }>(tools: readonly T[]): T[] {
  const result: T[] = [];
  const indexByName = new Map<string, number>();
  for (const tool of tools) {
    const existingIndex = indexByName.get(tool.tool_name);
    if (existingIndex === undefined) {
      indexByName.set(tool.tool_name, result.length);
      result.push(tool);
    } else {
      result[existingIndex] = tool;
    }
  }
  return result;
}

export function assistantToolStatus(tool: {
  tool_name: string;
  ok?: boolean;
  data?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  error?: { message?: string } | null;
}) {
  if (tool.ok === false) return { state: "error", label: tool.error?.message || "执行失败" };
  if (tool.tool_name !== "search_history_knowledge") return { state: "ok", label: "已完成" };
  const status = tool.data?.retrieval_status || tool.metadata?.retrieval_status;
  if (status === "sufficient") return { state: "ok", label: "已找到依据" };
  if (status === "partial") return { state: "partial", label: "仅找到部分依据" };
  if (status === "none") return { state: "empty", label: "未找到足够依据" };
  return { state: "ok", label: "检索已完成" };
}
