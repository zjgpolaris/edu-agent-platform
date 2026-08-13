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
