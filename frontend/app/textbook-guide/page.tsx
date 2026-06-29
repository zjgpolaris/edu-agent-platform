"use client";

import { useEffect, useMemo, useState } from "react";

type Textbook = { id: string; grade: string; book: string; status: "ready" | "empty" | "invalid" };
type TocUnit = { title: string; lessons: Array<{ id: string; title: string; item_count: number }> };
type Lesson = {
  book_id: string;
  lesson_id: string;
  grade: string;
  book: string;
  unit_title: string;
  lesson_title: string;
  items: Array<{ id: string; text: string; topic: string; entities: string[] }>;
};
type QuizQuestion = { id: string; question: string; answer: string; explanation: string; source_item_ids?: string[] };

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

function getStudentId() {
  const key = "edu-agent-student-id";
  const existing = localStorage.getItem(key);
  if (existing) return existing;
  const created = `student-${crypto.randomUUID()}`;
  localStorage.setItem(key, created);
  return created;
}

export default function TextbookGuidePage() {
  const [textbooks, setTextbooks] = useState<Textbook[]>([]);
  const [bookId, setBookId] = useState("");
  const [toc, setToc] = useState<TocUnit[]>([]);
  const [lessonId, setLessonId] = useState("");
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [summary, setSummary] = useState("");
  const [questions, setQuestions] = useState<QuizQuestion[]>([]);
  const [userAnswers, setUserAnswers] = useState<Record<string, string>>({});
  const [quizResult, setQuizResult] = useState<{ total: number; correct: number; score: number; results: any[] } | null>(null);
  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${apiBaseUrl}/api/textbooks`)
      .then((response) => response.json())
      .then((data) => setTextbooks((data.textbooks || []).filter((item: Textbook) => item.status === "ready")))
      .catch(() => setError("教材列表加载失败"));
  }, []);

  async function selectBook(nextBookId: string) {
    setBookId(nextBookId);
    setLessonId("");
    setLesson(null);
    setSummary("");
    setQuestions([]);
    setUserAnswers({});
    setQuizResult(null);
    setLoading("toc");
    setError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/textbooks/${nextBookId}/toc`);
      if (!response.ok) throw new Error("目录加载失败");
      const data = await response.json();
      setToc(data.units || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "目录加载失败");
    } finally {
      setLoading("");
    }
  }

  async function selectLesson(nextLessonId: string) {
    if (!bookId) return;
    setLessonId(nextLessonId);
    setSummary("");
    setQuestions([]);
    setUserAnswers({});
    setQuizResult(null);
    setLoading("lesson");
    setError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/textbooks/${bookId}/lessons/${nextLessonId}`);
      if (!response.ok) throw new Error("课程加载失败");
      setLesson(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "课程加载失败");
    } finally {
      setLoading("");
    }
  }

  async function generateGuide() {
    if (!lesson) return;
    setLoading("guide");
    setError("");
    try {
      const [summaryResponse, quizResponse] = await Promise.all([
        fetch(`${apiBaseUrl}/api/textbook-learning/summary`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ book_id: lesson.book_id, lesson_id: lesson.lesson_id, mode: "exam_points" }),
        }),
        fetch(`${apiBaseUrl}/api/textbook-learning/quiz`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ book_id: lesson.book_id, lesson_id: lesson.lesson_id, question_types: ["short_answer", "explanation"], count: 5 }),
        }),
      ]);
      if (!summaryResponse.ok || !quizResponse.ok) throw new Error("导读生成失败");
      const summaryData = await summaryResponse.json();
      const quizData = await quizResponse.json();
      setSummary(summaryData.response || "");
      setQuestions(quizData.questions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导读生成失败");
    } finally {
      setLoading("");
    }
  }

  async function submitQuiz() {
    if (!lesson || questions.length === 0) return;
    setLoading("submit");
    setError("");
    try {
      const answers = questions.map((q) => ({ question_id: q.id, user_answer: userAnswers[q.id] || "" }));
      const response = await fetch(`${apiBaseUrl}/api/textbook-learning/quiz/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ book_id: lesson.book_id, lesson_id: lesson.lesson_id, answers, student_id: getStudentId() }),
      });
      if (!response.ok) throw new Error("提交失败");
      setQuizResult(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setLoading("");
    }
  }

  const relatedCharacters = useMemo(() => {
    if (!lesson) return [];
    return Array.from(new Set(lesson.items.flatMap((item) => item.entities || []))).slice(0, 8);
  }, [lesson]);

  return (
    <main className="academy-shell textbook-guide-shell">
      <section className="academy-hero textbook-hero">
        <div className="hero-copy">
          <div className="eyebrow">初中历史 · 章节导读</div>
          <h1>把一课书压成一张考点卷</h1>
          <p>选择教材课次，一键生成核心考点、思考题和可继续对话的历史人物。</p>
          <div className="hero-flow" aria-label="导读流程"><span>选教材</span><span>定课次</span><span>生成考点</span><span>追问人物</span></div>
          <a className="hero-game-link" href="/">返回学习大厅</a>
        </div>
      </section>

      <section className="textbook-guide-layout">
        <aside className="guide-sidebar panel">
          <h2>教材与目录</h2>
          <div className="guide-book-list">
            {textbooks.map((book) => (
              <button key={book.id} className={bookId === book.id ? "active" : ""} onClick={() => selectBook(book.id)}>
                <span>{book.grade}</span><strong>{book.book}</strong>
              </button>
            ))}
          </div>
          {toc.length > 0 && (
            <div className="guide-toc-list">
              {toc.map((unit) => (
                <div key={unit.title} className="guide-unit-block">
                  <div className="guide-unit-title">{unit.title}</div>
                  {unit.lessons.map((item) => (
                    <button key={item.id} className={lessonId === item.id ? "active" : ""} onClick={() => selectLesson(item.id)}>{item.title}</button>
                  ))}
                </div>
              ))}
            </div>
          )}
        </aside>

        <section className="guide-main panel">
          {loading === "lesson" ? (
            <div className="empty-state"><p>课程加载中...</p></div>
          ) : !lesson ? (
            <div className="empty-state"><h2>先选一课，AI 再导读</h2><p>左侧选择教材和章节后，这里会展示课次知识点、考点梳理和思考题。</p></div>
          ) : (
            <>
              <div className="guide-title-row">
                <div><span>{lesson.grade} · {lesson.unit_title}</span><h2>{lesson.lesson_title}</h2></div>
                <button className="primary" onClick={generateGuide} disabled={Boolean(loading)}>{loading === "guide" ? "生成中..." : "生成章节导读"}</button>
              </div>
              <div className="guide-item-grid">
                {lesson.items.slice(0, 8).map((item) => <article key={item.id} className="guide-knowledge-card"><strong>{item.topic}</strong><p>{item.text}</p></article>)}
              </div>
              {summary && <article className="guide-output-card exam-points"><span className="card-label">核心考点</span><div className="guide-prose">{summary}</div></article>}
              {questions.length > 0 && (
                <article className="guide-output-card">
                  <span className="card-label">思考题</span>
                  <div className="guide-question-list">
                    {questions.map((question, index) => (
                      <div key={question.id} className="guide-question-card">
                        <p>{index + 1}. {question.question}</p>
                        <textarea
                          placeholder="输入你的答案..."
                          value={userAnswers[question.id] || ""}
                          onChange={(e) => setUserAnswers({ ...userAnswers, [question.id]: e.target.value })}
                          disabled={Boolean(quizResult)}
                        />
                        {quizResult && (
                          <div className={`quiz-feedback ${quizResult.results[index]?.is_correct ? "correct" : "wrong"}`}>
                            <strong>参考答案：</strong>{question.answer}
                            {question.explanation && <p><strong>解析：</strong>{question.explanation}</p>}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                  {!quizResult && (
                    <button className="primary" onClick={submitQuiz} disabled={loading === "submit"}>
                      {loading === "submit" ? "提交中..." : "提交答案"}
                    </button>
                  )}
                  {quizResult && (
                    <div className="quiz-summary">
                      <span>正确率：{Math.round(quizResult.score * 100)}%</span>
                      <span>({quizResult.correct}/{quizResult.total})</span>
                    </div>
                  )}
                </article>
              )}
              {relatedCharacters.length > 0 && <article className="guide-output-card"><span className="card-label">相关历史人物</span><div className="character-tags">{relatedCharacters.map((character) => <a key={character} href={`/history-character?character=${encodeURIComponent(character)}`}>{character}</a>)}</div></article>}
            </>
          )}
          {error && <div className="error-card">{error}</div>}
        </section>
      </section>
    </main>
  );
}
