"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Textbook = { id: string; grade: string; book: string; status: string };
type TocLesson = { id: string; title: string };
type TocUnit = { title: string; lessons: TocLesson[] };
type Question = { id: string; type: string; question: string; options: string[] | null; answer: string; explanation: string; topic?: string; source_item_ids?: string[] };
type Answer = { questionId: string; value: string };
type GradeResult = { questionId: string; correct: boolean; explanation: string };

export default function QuizPracticePage() {
  const { user } = useAuth();
  const studentId = user?.actorId ?? "";
  const [books, setBooks] = useState<Textbook[]>([]);
  const [bookId, setBookId] = useState("");
  const [units, setUnits] = useState<TocUnit[]>([]);
  const [lessonId, setLessonId] = useState("");
  const [count, setCount] = useState(5);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [results, setResults] = useState<GradeResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [grading, setGrading] = useState(false);
  const [error, setError] = useState("");
  const [phase, setPhase] = useState<"setup" | "quiz" | "result">("setup");
  const [currentQ, setCurrentQ] = useState(0);

  useEffect(() => {
    fetch(`${API}/api/textbooks`).then((r) => r.json())
      .then((d) => setBooks((d.textbooks || []).filter((b: Textbook) => b.status === "ready")))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!bookId) { setUnits([]); setLessonId(""); return; }
    fetch(`${API}/api/textbooks/${bookId}/toc`).then((r) => r.json())
      .then((d) => { setUnits(d.units || []); setLessonId(""); })
      .catch(() => {});
  }, [bookId]);

  async function startQuiz() {
    if (!bookId || !lessonId) { setError("请选择教材和课次"); return; }
    setError(""); setLoading(true);
    try {
      const res = await fetch(`${API}/api/textbook-learning/quiz`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ book_id: bookId, lesson_id: lessonId, count, student_id: studentId || null }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const qs: Question[] = data.questions || [];
      setQuestions(qs);
      setAnswers(qs.map((q) => ({ questionId: q.id, value: "" })));
      setResults([]); setCurrentQ(0); setPhase("quiz");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "出题失败");
    } finally { setLoading(false); }
  }

  function setAnswer(questionId: string, value: string) {
    setAnswers((prev) => prev.map((a) => a.questionId === questionId ? { ...a, value } : a));
  }

  async function submitQuiz() {
    setGrading(true);
    const graded: GradeResult[] = questions.map((q) => {
      const userAnswer = answers.find((a) => a.questionId === q.id)?.value.trim() ?? "";
      const correct = q.type === "single_choice"
        ? userAnswer.toUpperCase() === q.answer.trim().toUpperCase()
        : userAnswer.length > 0;
      return { questionId: q.id, correct, explanation: q.explanation };
    });
    setResults(graded); setPhase("result");
    if (studentId.trim()) {
      const score = graded.filter((r) => r.correct).length / questions.length;
      await Promise.all([
        fetch(`${API}/api/students/${studentId}/events`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ student_id: studentId, feature: "quiz_practice", event_type: "quiz_completed", book_id: bookId, lesson_id: lessonId, score, success: score >= 0.6 }),
        }).catch(() => {}),
        fetch(`${API}/api/textbook-learning/quiz/submit`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(user?.token ? authHeaders(user.token) : {}) },
          body: JSON.stringify({ book_id: bookId, lesson_id: lessonId, student_id: studentId, answers: answers.map((a) => ({ question_id: a.questionId, user_answer: a.value.trim(), source_item_ids: questions.find((q) => q.id === a.questionId)?.source_item_ids ?? [] })) }),
        }).catch(() => {}),
      ]);
    }
    setGrading(false);
  }

  const correctCount = results.filter((r) => r.correct).length;
  const currentAns = answers.find((a) => a.questionId === questions[currentQ]?.id);
  const allAnswered = answers.every((a) => a.value.trim().length > 0);
  const progress = questions.length ? answers.filter((a) => a.value.trim()).length / questions.length : 0;

  const pct = questions.length ? Math.round(correctCount / questions.length * 100) : 0;

  return (
    <div className="academy-shell">
      <header className="quiz-page-hero">
        <div className="quiz-page-hero-text">
          <p className="eyebrow">Quiz Practice · 出题练习</p>
          <h1>智能出题练习</h1>
          <p>按教材章节出题，即时判卷，练习结果自动记录到学生画像。</p>
        </div>
        <div className="quiz-page-hero-badge" aria-hidden>练</div>
      </header>

      {phase === "setup" && (
        <div className="quiz-setup-layout">
          <div className="quiz-setup-card">
            <div className="quiz-setup-inner">
              <p className="quiz-setup-title">选择练习内容</p>

              <div className="quiz-field-group">
                <div className="quiz-field">
                  <label className="quiz-label">选择教材</label>
                  <div className="quiz-select-wrap">
                    <select className="quiz-select" value={bookId} onChange={(e) => setBookId(e.target.value)}>
                      <option value="">— 请选择 —</option>
                      {books.map((b) => <option key={b.id} value={b.id}>{b.grade} · {b.book}</option>)}
                    </select>
                  </div>
                </div>

                {units.length > 0 && (
                  <div className="quiz-field">
                    <label className="quiz-label">选择课次</label>
                    <div className="quiz-select-wrap">
                      <select className="quiz-select" value={lessonId} onChange={(e) => setLessonId(e.target.value)}>
                        <option value="">— 请选择 —</option>
                        {units.map((u) => (
                          <optgroup key={u.title} label={u.title}>
                            {u.lessons.map((l) => <option key={l.id} value={l.id}>{l.title}</option>)}
                          </optgroup>
                        ))}
                      </select>
                    </div>
                  </div>
                )}
              </div>

              <div className="quiz-count-row">
                <p className="quiz-label">题目数量</p>
                <div className="quiz-count-btns">
                  {[3, 5, 8, 10].map((n) => (
                    <button key={n} className={`quiz-count-btn${count === n ? " active" : ""}`} onClick={() => setCount(n)}>
                      {n} 题
                    </button>
                  ))}
                </div>
              </div>

              {error && <p className="quiz-error">{error}</p>}

              <button className="quiz-cta" onClick={startQuiz} disabled={loading || !bookId || !lessonId}>
                {loading ? <><span className="quiz-cta-spinner" />生成题目中…</> : "开始练习 →"}
              </button>
            </div>
            <div className="quiz-setup-deco" aria-hidden>历</div>
          </div>

          <aside className="quiz-setup-hint">
            <div className="quiz-hint-card">
              <p className="quiz-hint-card-title">使用步骤</p>
              <ol className="quiz-hint-steps">
                <li data-n="1">选择教材和课次</li>
                <li data-n="2">设定题目数量</li>
                <li data-n="3">逐题作答，随时跳转</li>
                <li data-n="4">提交后即时查看解析</li>
              </ol>
            </div>
            <div className="quiz-hint-card">
              <p className="quiz-hint-card-title">题型说明</p>
              <ol className="quiz-hint-steps">
                <li data-n="选">单选题：选择最佳选项</li>
                <li data-n="填">填空题：简短文字作答</li>
                <li data-n="答">简答题：完整阐述观点</li>
              </ol>
            </div>
          </aside>
        </div>
      )}

      {phase === "quiz" && questions.length > 0 && (
        <div className="quiz-stage">
          <div className="quiz-progress-header">
            <div className="quiz-progress-bar">
              <div className="quiz-progress-fill" style={{ width: `${progress * 100}%` }} />
            </div>
            <div className="quiz-progress-meta">
              <span>{answers.filter((a) => a.value.trim()).length} / {questions.length} 已作答</span>
              <span className="quiz-progress-frac">{currentQ + 1}<span style={{ color: "var(--muted)", fontSize: 14, fontWeight: 700 }}>/{questions.length}</span></span>
            </div>
          </div>

          <div className="quiz-card" key={questions[currentQ].id}>
            <div className="quiz-card-meta">
              <span className="quiz-type-badge">
                {questions[currentQ].type === "single_choice" ? "单选题" : questions[currentQ].type === "fill_blank" ? "填空题" : "简答题"}
              </span>
              <span className="quiz-card-num">{currentQ + 1}</span>
            </div>
            <p className="quiz-card-question">{questions[currentQ].question}</p>

            {questions[currentQ].type === "single_choice" && questions[currentQ].options ? (
              <div className="quiz-options">
                {questions[currentQ].options!.map((opt, oi) => {
                  const letter = String.fromCharCode(65 + oi);
                  const selected = currentAns?.value === letter;
                  return (
                    <button key={letter} className={`quiz-option${selected ? " selected" : ""}`}
                      onClick={() => {
                        setAnswer(questions[currentQ].id, letter);
                        if (currentQ < questions.length - 1) {
                          setTimeout(() => setCurrentQ((q) => q + 1), 320);
                        }
                      }}>
                      <span className="quiz-option-letter">{letter}</span>
                      <span>{opt}</span>
                    </button>
                  );
                })}
              </div>
            ) : (
              <textarea className="quiz-textarea" placeholder="请输入你的答案…" rows={4}
                value={currentAns?.value ?? ""}
                onChange={(e) => setAnswer(questions[currentQ].id, e.target.value)} />
            )}
          </div>

          <div className="quiz-nav">
            <button className="quiz-nav-btn" onClick={() => setCurrentQ((q) => Math.max(0, q - 1))} disabled={currentQ === 0}>
              ← 上一题
            </button>
            <div className="quiz-dot-nav">
              {questions.map((q, i) => (
                <button key={q.id} aria-label={`第 ${i + 1} 题`}
                  className={`quiz-dot${i === currentQ ? " active" : ""}${answers.find((a) => a.questionId === q.id)?.value ? " done" : ""}`}
                  onClick={() => setCurrentQ(i)} />
              ))}
            </div>
            {currentQ < questions.length - 1 ? (
              <button className="quiz-nav-btn primary" onClick={() => setCurrentQ((q) => Math.min(questions.length - 1, q + 1))}>
                下一题 →
              </button>
            ) : (
              <button className="quiz-nav-btn primary" onClick={submitQuiz} disabled={grading || !allAnswered}>
                {grading ? "批改中…" : "提交答案"}
              </button>
            )}
          </div>
        </div>
      )}

      {phase === "result" && (
        <div className="quiz-result-layout">
          <div className="quiz-score-card">
            <p className="quiz-score-label-top">本次得分</p>
            <div className="quiz-score-ring">
              <svg viewBox="0 0 100 100" className="quiz-score-svg">
                <defs>
                  <linearGradient id="scoreGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="var(--jade)" />
                    <stop offset="100%" stopColor="var(--gold)" />
                  </linearGradient>
                </defs>
                <circle cx="50" cy="50" r="42" className="quiz-ring-bg" />
                <circle cx="50" cy="50" r="42" className="quiz-ring-fill"
                  style={{ strokeDasharray: `${2 * Math.PI * 42 * correctCount / questions.length} ${2 * Math.PI * 42}` }} />
              </svg>
              <div className="quiz-score-center">
                <span className="quiz-score-num">{correctCount}</span>
                <span className="quiz-score-total">/{questions.length}</span>
              </div>
            </div>
            <p className="quiz-score-pct">{pct}%</p>
            <p className="quiz-score-msg">
              {correctCount === questions.length ? "全部正确，太棒了！" :
                correctCount >= questions.length * 0.6 ? "良好，继续努力！" : "还需加强，多复习！"}
            </p>
            <button className="quiz-cta" onClick={() => { setPhase("setup"); setQuestions([]); }}>
              再来一次
            </button>
          </div>

          <div className="quiz-review-list">
            {questions.map((q, idx) => {
              const r = results.find((x) => x.questionId === q.id);
              const userAns = answers.find((a) => a.questionId === q.id)?.value;
              return (
                <div key={q.id} className={`quiz-review-item${r?.correct ? " correct" : " wrong"}`}
                  style={{ animationDelay: `${idx * 55}ms` }}>
                  <div className="quiz-review-top">
                    <span className={`quiz-review-verdict${r?.correct ? " v-correct" : " v-wrong"}`}>
                      {r?.correct ? "✓" : "✗"}
                    </span>
                    <span className="quiz-review-qnum">第 {idx + 1} 题</span>
                  </div>
                  <p className="quiz-review-question">{q.question}</p>
                  <p className="quiz-review-yours">你的答案：{userAns || "（未作答）"}</p>
                  {!r?.correct && <p className="quiz-review-correct">正确答案：{q.answer}</p>}
                  <p className="quiz-review-exp">{q.explanation}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
