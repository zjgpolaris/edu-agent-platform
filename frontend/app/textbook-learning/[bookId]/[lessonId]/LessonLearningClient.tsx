"use client";

import { useEffect, useMemo, useState } from "react";

type LessonItem = {
  id: string;
  text: string;
  topic: string;
  type: string;
  page: number | string;
};

type Lesson = {
  book_id: string;
  lesson_id: string;
  grade: string;
  book: string;
  unit_title: string;
  lesson_title: string;
  items: LessonItem[];
};

type TocLesson = { id: string; title: string; item_count: number };
type TocUnit = { title: string; lessons: TocLesson[] };
type Toc = { book_id: string; grade: string; book: string; units: TocUnit[] };

type Source = {
  topic?: string;
  source?: string;
  grade?: string;
  unit?: string;
  lesson?: string;
  type?: string;
  page?: string | number;
  content?: string;
};

type StreamEvent = { event: string; data: Record<string, unknown> };
type AssistantTab = "ask" | "summary" | "quiz" | "notes";
type SummaryMode = "overview" | "exam_points" | "mistakes" | "compare";

type Note = {
  id: string;
  itemId: string;
  topic: string;
  text: string;
  createdAt: number;
};

type QuizQuestion = {
  id: string;
  type: string;
  question: string;
  options?: string[] | null;
  answer: string;
  explanation: string;
  source_item_ids: string[];
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const summaryModes: { mode: SummaryMode; label: string }[] = [
  { mode: "overview", label: "本课概要" },
  { mode: "exam_points", label: "考点梳理" },
  { mode: "mistakes", label: "易错提醒" },
  { mode: "compare", label: "对比归纳" },
];

function createId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function parseSseFrame(frame: string): StreamEvent | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    if (line.startsWith("data: ")) dataLines.push(line.slice(6));
  }

  if (!dataLines.length) return null;
  return { event, data: JSON.parse(dataLines.join("\n")) as Record<string, unknown> };
}

function itemTypeLabel(type: string) {
  if (type === "primary") return "史料阅读";
  if (type === "concept") return "重要概念";
  if (type === "timeline") return "时间线索";
  return "核心知识点";
}

function groupItems(items: LessonItem[]) {
  return [
    { key: "textbook", title: "核心知识点", items: items.filter((item) => item.type === "textbook" || item.type === "timeline") },
    { key: "concept", title: "重要概念", items: items.filter((item) => item.type === "concept") },
    { key: "primary", title: "史料阅读", items: items.filter((item) => item.type === "primary") },
  ].filter((group) => group.items.length > 0);
}

function sourceTypeLabel(type?: string) {
  if (type === "primary") return "史料";
  if (type === "concept") return "概念";
  return "教材知识";
}

export default function LessonLearningClient({ lesson, toc }: { lesson: Lesson; toc: Toc }) {
  const [tab, setTab] = useState<AssistantTab>("ask");
  const [status, setStatus] = useState("选择知识点操作，或在右侧输入问题开始学习。");
  const [askAnswer, setAskAnswer] = useState("");
  const [summaryAnswer, setSummaryAnswer] = useState("");
  const [question, setQuestion] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [notes, setNotes] = useState<Note[]>([]);
  const [quiz, setQuiz] = useState<QuizQuestion[]>([]);
  const [quizRawText, setQuizRawText] = useState("");
  const [quizAnswers, setQuizAnswers] = useState<Record<string, string>>({});
  const [quizRevealed, setQuizRevealed] = useState<Record<string, boolean>>({});

  const noteKey = `textbook-learning:${lesson.book_id}:${lesson.lesson_id}:notes`;
  const groupedItems = useMemo(() => groupItems(lesson.items), [lesson.items]);
  const guideTopics = lesson.items.slice(0, 3).map((item) => item.topic);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(noteKey);
      const parsed = stored ? JSON.parse(stored) : [];
      setNotes(Array.isArray(parsed) ? parsed as Note[] : []);
    } catch {
      setNotes([]);
    }
  }, [noteKey]);

  function saveNotes(nextNotes: Note[]) {
    setNotes(nextNotes);
    window.localStorage.setItem(noteKey, JSON.stringify(nextNotes));
  }

  function addNote(item: LessonItem) {
    const nextNotes = [
      {
        id: createId("note"),
        itemId: item.id,
        topic: item.topic,
        text: item.text,
        createdAt: Date.now(),
      },
      ...notes,
    ];
    saveNotes(nextNotes);
    setTab("notes");
    setStatus(`已将“${item.topic}”加入本课笔记。`);
  }

  async function handleStream(response: Response, setTargetAnswer: (updater: (current: string) => string) => void) {
    if (!response.body) throw new Error("浏览器没有收到流式响应，请稍后重试。");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    async function handleEvent(streamEvent: StreamEvent) {
      const { event, data } = streamEvent;
      if (event === "status") {
        if (typeof data.message === "string") setStatus(data.message);
        return;
      }
      if (event === "sources") {
        setSources(Array.isArray(data.sources) ? data.sources as Source[] : []);
        return;
      }
      if (event === "delta") {
        const text = typeof data.text === "string" ? data.text : "";
        setTargetAnswer((current) => current + text);
        return;
      }
      if (event === "final") {
        if (typeof data.response === "string") setTargetAnswer(() => data.response as string);
        setStatus("已完成。");
        return;
      }
      if (event === "error") {
        throw new Error(typeof data.message === "string" ? data.message : "生成失败，请稍后重试。");
      }
    }

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";
      for (const frame of frames) {
        const streamEvent = parseSseFrame(frame.trim());
        if (streamEvent) await handleEvent(streamEvent);
      }
    }

    buffer += decoder.decode();
    if (buffer.trim()) {
      const streamEvent = parseSseFrame(buffer.trim());
      if (streamEvent) await handleEvent(streamEvent);
    }
  }

  async function askItem(item: LessonItem, action: string, label: string) {
    setTab("ask");
    setLoading(true);
    setErrorMessage("");
    setAskAnswer("");
    setSources([]);
    setStatus("正在连接教材问答接口...");

    try {
      const response = await fetch(`${apiBaseUrl}/api/textbook-learning/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          book_id: lesson.book_id,
          lesson_id: lesson.lesson_id,
          item_id: item.id,
          selected_text: item.text,
          question: label,
          action,
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await handleStream(response, setAskAnswer);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "请求失败，请稍后重试。");
      setStatus("本次学习辅助生成失败，请检查后端服务状态。");
    } finally {
      setLoading(false);
    }
  }

  async function askCustomQuestion() {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) {
      setErrorMessage("请先输入问题。");
      return;
    }
    setLoading(true);
    setErrorMessage("");
    setAskAnswer("");
    setSources([]);
    setStatus("正在连接教材问答接口...");

    try {
      const response = await fetch(`${apiBaseUrl}/api/textbook-learning/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ book_id: lesson.book_id, lesson_id: lesson.lesson_id, question: trimmedQuestion }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await handleStream(response, setAskAnswer);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "请求失败，请稍后重试。");
      setStatus("本次学习辅助生成失败，请检查后端服务状态。");
    } finally {
      setLoading(false);
    }
  }

  async function generateSummary(mode: SummaryMode) {
    setTab("summary");
    setLoading(true);
    setErrorMessage("");
    setSummaryAnswer("");
    setSources([]);

    try {
      const response = await fetch(`${apiBaseUrl}/api/textbook-learning/summary`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ book_id: lesson.book_id, lesson_id: lesson.lesson_id, mode }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await handleStream(response, setSummaryAnswer);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "摘要生成失败，请稍后重试。");
      setStatus("摘要生成失败，请检查后端服务状态。");
    } finally {
      setLoading(false);
    }
  }

  async function generateQuiz(focusItemId?: string) {
    setTab("quiz");
    setLoading(true);
    setErrorMessage("");
    setQuiz([]);
    setQuizRawText("");
    setQuizAnswers({});
    setQuizRevealed({});
    setSources([]);
    setStatus("正在生成本课自测题...");

    try {
      const response = await fetch(`${apiBaseUrl}/api/textbook-learning/quiz`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          book_id: lesson.book_id,
          lesson_id: lesson.lesson_id,
          question_types: ["single_choice", "short_answer", "explanation"],
          count: focusItemId ? 1 : 5,
          focus_item_id: focusItemId,
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as { questions?: QuizQuestion[]; raw_text?: string | null };
      setQuiz(data.questions || []);
      setQuizRawText(data.raw_text || "");
      setStatus("自测题已生成。先尝试作答，再点击核对答案查看解析。");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "自测题生成失败，请稍后重试。");
      setStatus("自测题生成失败，请检查后端服务状态。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="academy-shell textbook-learning-shell">
      <section className="academy-hero textbook-hero compact-hero">
        <div className="hero-copy">
          <div className="eyebrow">{lesson.grade} · {lesson.unit_title}</div>
          <h1>{lesson.lesson_title}</h1>
          <p>这是一份教材同步学习文档，围绕结构化知识点进行理解、提问、摘要和自测，不等同于教材 PDF 原文。</p>
          <div className="hero-flow" aria-label="本课学习入口">
            <span>{lesson.items.length} 条知识点</span>
            <span>AI 导学</span>
            <span>本地笔记</span>
            <span>自测练习</span>
          </div>
          <a className="hero-game-link" href={`/textbook-learning/${lesson.book_id}`}>返回教材目录</a>
        </div>
        <div className="teaching-card textbook-boundary-card" aria-label="本课导学">
          <div className="seal-mark" aria-hidden="true">导</div>
          <span className="card-label">本课导学</span>
          <strong>先抓住这些关键词</strong>
          <p>{guideTopics.join("、") || "先浏览本课知识点，再向 AI 提问。"}</p>
        </div>
      </section>

      <section className="textbook-workspace">
        <aside className="panel textbook-side-toc" aria-label="教材目录">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">目录</span>
              <h2>{lesson.book}</h2>
            </div>
          </div>
          {toc.units.map((unit) => (
            <section className="side-toc-unit" key={unit.title}>
              <strong>{unit.title}</strong>
              {unit.lessons.map((tocLesson) => (
                <a className={tocLesson.id === lesson.lesson_id ? "active" : ""} href={`/textbook-learning/${lesson.book_id}/${tocLesson.id}`} key={tocLesson.id}>
                  {tocLesson.title}
                </a>
              ))}
            </section>
          ))}
        </aside>

        <section className="panel lesson-document" aria-label="课程学习文档">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">学习文档</span>
              <h2>{lesson.lesson_title}</h2>
            </div>
            <small>页码为近似提示</small>
          </div>

          {groupedItems.map((group) => (
            <section className="lesson-section" key={group.key}>
              <h3>{group.title}</h3>
              <div className="knowledge-card-list">
                {group.items.map((item) => (
                  <article className={`knowledge-item-card ${item.type}`} key={item.id}>
                    <div className="knowledge-card-header">
                      <div>
                        <span className="panel-kicker">{itemTypeLabel(item.type)}</span>
                        <h4>{item.topic}</h4>
                      </div>
                      <em>约第 {item.page} 页</em>
                    </div>
                    <p>{item.text}</p>
                    <div className="knowledge-actions">
                      <button className="secondary" type="button" disabled={loading} onClick={() => askItem(item, "explain", "解释一下")}>解释一下</button>
                      <button className="secondary" type="button" disabled={loading} onClick={() => askItem(item, "importance", "为什么重要")}>为什么重要</button>
                      <button className="secondary" type="button" disabled={loading} onClick={() => askItem(item, "exam", "容易怎么考")}>容易怎么考</button>
                      <button className="secondary" type="button" disabled={loading} onClick={() => generateQuiz(item.id)}>生成一道题</button>
                      <button className="text-button" type="button" onClick={() => addNote(item)}>加入笔记</button>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </section>

        <aside className="panel learning-assistant-panel" aria-label="AI 学习助手">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">AI 助手</span>
              <h2>学习辅助</h2>
            </div>
            <small>{loading ? "生成中" : "可提问"}</small>
          </div>

          <div className="assistant-tabs" role="tablist" aria-label="学习助手面板">
            {(["ask", "summary", "quiz", "notes"] as AssistantTab[]).map((item) => (
              <button className={tab === item ? "active" : ""} type="button" key={item} onClick={() => setTab(item)}>
                {item === "ask" ? "问答" : item === "summary" ? "摘要" : item === "quiz" ? "自测" : "笔记"}
              </button>
            ))}
          </div>

          <div className="assistant-status">{status}</div>
          {errorMessage && <div className="error-card" role="alert">{errorMessage}</div>}

          {tab === "ask" && (
            <section className="assistant-pane">
              <label htmlFor="lesson-question">我想问</label>
              <textarea id="lesson-question" value={question} maxLength={500} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：北京人学会用火有什么意义？" />
              <button className="primary" type="button" disabled={loading} onClick={askCustomQuestion}>{loading ? "生成中..." : "向本课 AI 提问"}</button>
              {askAnswer && <div className="assistant-answer">{askAnswer}</div>}
            </section>
          )}

          {tab === "summary" && (
            <section className="assistant-pane">
              <div className="summary-mode-grid">
                {summaryModes.map((item) => (
                  <button className="secondary" type="button" disabled={loading} key={item.mode} onClick={() => generateSummary(item.mode)}>{item.label}</button>
                ))}
              </div>
              {summaryAnswer && <div className="assistant-answer">{summaryAnswer}</div>}
            </section>
          )}

          {tab === "quiz" && (
            <section className="assistant-pane">
              <button className="primary" type="button" disabled={loading} onClick={() => generateQuiz()}>{loading ? "生成中..." : "生成本课自测"}</button>
              <div className="quiz-list">
                {quiz.map((item, index) => {
                  const revealed = Boolean(quizRevealed[item.id]);
                  const selectedAnswer = quizAnswers[item.id] || "";
                  return (
                    <article className="quiz-card" key={item.id}>
                      <strong>{index + 1}. {item.question}</strong>
                      {item.options?.length ? (
                        <div className="quiz-option-list" role="radiogroup" aria-label={`第 ${index + 1} 题选项`}>
                          {item.options.map((option) => (
                            <button
                              className={selectedAnswer === option ? "selected" : ""}
                              type="button"
                              key={option}
                              onClick={() => setQuizAnswers((current) => ({ ...current, [item.id]: option }))}
                              aria-pressed={selectedAnswer === option}
                            >
                              {option}
                            </button>
                          ))}
                        </div>
                      ) : (
                        <textarea
                          value={selectedAnswer}
                          onChange={(event) => setQuizAnswers((current) => ({ ...current, [item.id]: event.target.value }))}
                          placeholder="先写下你的答案，再核对解析。"
                          aria-label={`第 ${index + 1} 题作答区`}
                        />
                      )}
                      <div className="quiz-actions">
                        <button
                          className="secondary"
                          type="button"
                          disabled={!revealed && !selectedAnswer.trim()}
                          onClick={() => setQuizRevealed((current) => ({ ...current, [item.id]: !revealed }))}
                        >
                          {revealed ? "收起答案" : "核对答案"}
                        </button>
                        {!selectedAnswer.trim() && !revealed && <span>请先作答，才能核对答案。</span>}
                      </div>
                      {revealed && (
                        <div className="quiz-feedback">
                          {selectedAnswer && <p><b>我的答案：</b>{selectedAnswer}</p>}
                          <p><b>参考答案：</b>{item.answer}</p>
                          <p><b>解析：</b>{item.explanation}</p>
                        </div>
                      )}
                    </article>
                  );
                })}
                {quizRawText && <div className="assistant-answer">{quizRawText}</div>}
              </div>
            </section>
          )}

          {tab === "notes" && (
            <section className="assistant-pane">
              <div className="note-list">
                {notes.length === 0 && <div className="recommend-empty">还没有本课笔记，可以在知识点卡片中点击“加入笔记”。</div>}
                {notes.map((note) => (
                  <article className="note-card" key={note.id}>
                    <strong>{note.topic}</strong>
                    <p>{note.text}</p>
                    <button className="text-button" type="button" onClick={() => saveNotes(notes.filter((item) => item.id !== note.id))}>删除笔记</button>
                  </article>
                ))}
              </div>
            </section>
          )}

          {sources.length > 0 && (
            <section className="assistant-sources" aria-label="参考资料">
              <h3>参考资料</h3>
              {sources.slice(0, 3).map((source, index) => (
                <article className="source-card" key={`${source.topic || "source"}-${index}`}>
                  <div className="source-card-header">
                    <div>
                      <div className="source-kicker">参考</div>
                      <div className="source-title">{source.topic || "未标注主题"}</div>
                      <div className="source-meta">{[source.grade, source.unit, source.lesson].filter(Boolean).join(" · ") || "知识库材料"}</div>
                    </div>
                    <span className="source-type">{sourceTypeLabel(source.type)}</span>
                  </div>
                  <div className="source-content">{source.content || "暂无内容"}</div>
                </article>
              ))}
            </section>
          )}
        </aside>
      </section>
    </main>
  );
}
