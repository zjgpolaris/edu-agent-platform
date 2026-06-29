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
  try {
    const [lesson, toc] = await Promise.all([getLesson(params.bookId, params.lessonId), getToc(params.bookId)]);
    return <LessonLearningClient lesson={lesson} toc={toc} />;
  } catch {
    // 后端不可达时降级，避免整页 500。
    return (
      <main className="academy-shell textbook-learning-shell">
        <section className="panel textbook-toc-page" aria-label="课程内容">
          <h1>课程内容暂时无法加载</h1>
          <p>无法连接教材服务，请稍后重试。</p>
          <a className="hero-game-link" href={`/textbook-learning/${params.bookId}`}>返回教材目录</a>
        </section>
      </main>
    );
  }
}
