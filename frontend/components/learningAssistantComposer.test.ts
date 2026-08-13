import { describe, expect, it } from "vitest";
import { buildTextbookRequestFields, shouldSubmitComposerKey } from "./learningAssistantComposer";

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
});
