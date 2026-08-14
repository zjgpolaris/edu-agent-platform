import { describe, expect, it } from "vitest";
import { assistantCompletionLabel, assistantToolStatus, buildTextbookRequestFields, dedupeAssistantTools, shouldSubmitComposerKey, updateAssistantPlanStep } from "./learningAssistantComposer";

describe("learning assistant composer", () => {
  it("keeps textbook fields optional for a direct question", () => {
    expect(buildTextbookRequestFields(null)).toEqual({
      grade: null,
      book_id: null,
      lesson_id: null,
    });
  });

  it("maps an explicitly attached lesson to the existing API contract", () => {
    expect(buildTextbookRequestFields({ grade: "八年级上册", bookId: "history-8-1", lessonId: "lesson-4" })).toEqual({
      grade: "八年级上册",
      book_id: "history-8-1",
      lesson_id: "lesson-4",
    });
  });

  it("submits on Enter only", () => {
    expect(shouldSubmitComposerKey({ key: "Enter", shiftKey: false, isComposing: false })).toBe(true);
    expect(shouldSubmitComposerKey({ key: "Enter", shiftKey: true, isComposing: false })).toBe(false);
    expect(shouldSubmitComposerKey({ key: "Enter", shiftKey: false, isComposing: true })).toBe(false);
  });

  it("merges streamed plan progress without changing other steps", () => {
    const steps = [
      { step_id: "step_1", title: "检索", status: "running" as const },
      { step_id: "step_2", title: "回答", status: "pending" as const },
    ];
    expect(updateAssistantPlanStep(steps, { step_id: "step_1", status: "completed", latency_ms: 42 })).toEqual([
      { step_id: "step_1", title: "检索", status: "completed", latency_ms: 42 },
      steps[1],
    ]);
  });

  it("labels partial and clarification completions explicitly", () => {
    expect(assistantCompletionLabel("partial")).toBe("已完成部分学习任务");
    expect(assistantCompletionLabel("needs_clarification")).toBe("等待补充信息");
    expect(assistantCompletionLabel("completed")).toBe("已完成");
  });

  it("keeps only the latest result for duplicate tool cards", () => {
    const tools = [
      { tool_name: "search_history_knowledge", attempt: 1, data: { sources: [] } },
      { tool_name: "recommend_character", attempt: 1 },
      { tool_name: "search_history_knowledge", attempt: 2, data: { sources: [{ topic: "赤壁之战" }] } },
    ];
    expect(dedupeAssistantTools(tools)).toEqual([
      tools[2],
      tools[1],
    ]);
  });

  it("distinguishes retrieval completion from evidence sufficiency", () => {
    expect(assistantToolStatus({
      tool_name: "search_history_knowledge",
      ok: true,
      data: { retrieval_status: "sufficient" },
    })).toEqual({ state: "ok", label: "已找到依据" });
    expect(assistantToolStatus({
      tool_name: "search_history_knowledge",
      ok: true,
      metadata: { retrieval_status: "partial" },
    })).toEqual({ state: "partial", label: "仅找到部分依据" });
    expect(assistantToolStatus({
      tool_name: "search_history_knowledge",
      ok: true,
      data: { retrieval_status: "none" },
    })).toEqual({ state: "empty", label: "未找到足够依据" });
  });
});
