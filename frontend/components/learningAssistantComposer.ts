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
