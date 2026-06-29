import LessonLearningClient from "./LessonLearningClient";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function getLesson(bookId: string, lessonId: string) {
  const response = await fetch(`${apiBaseUrl}/api/textbooks/${bookId}/lessons/${lessonId}`, { cache: "no-store" });
  if (!response.ok) throw new Error("课程内容加载失败");
  return response.json();
}

async function getToc(bookId: string) {
  const response = await fetch(`${apiBaseUrl}/api/textbooks/${bookId}/toc`, { cache: "no-store" });
  if (!response.ok) throw new Error("教材目录加载失败");
  return response.json();
}

export default async function TextbookLessonPage({ params }: { params: { bookId: string; lessonId: string } }) {
  const [lesson, toc] = await Promise.all([getLesson(params.bookId, params.lessonId), getToc(params.bookId)]);
  return <LessonLearningClient lesson={lesson} toc={toc} />;
}
