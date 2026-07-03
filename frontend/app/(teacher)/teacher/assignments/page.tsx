"use client";
import { useState, useEffect } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Student = { actor_id: string; display_name: string | null };
type DraftQuestion = {
  type: string;
  prompt: string;
  options: string[];
  answer: string;
  knowledge_tag: string;
  reference_answer?: string;
  quality?: { level: string; issues: string[] };
};
type WeakTag = { knowledge_tag: string; wrong_count?: number; student_count: number; question_indices?: number[]; sources?: string[] };
type LowAccuracyQuestion = {
  question_index: number; prompt: string; type: string; knowledge_tag?: string | null;
  attempts: number; correct: number; wrong: number; accuracy: number;
  predicted_level?: string | null;
  common_wrong_answers?: Array<{ answer: string; count: number }>;
};
type QualityBlindSpot = { question_index: number; prompt: string; accuracy: number; attempts: number; predicted_level?: string | null };
type AssignmentInsights = {
  submission_rate: { submitted: number; assignee_count: number; percent: number; missing_student_ids: string[] };
  average_score: number | null;
  graded_average_score: number | null;
  pending_review_count: number;
  lowest_accuracy_questions: LowAccuracyQuestion[];
  quality_blind_spots?: QualityBlindSpot[];
  top_weak_tags: WeakTag[];
  below_threshold_students: Array<{ student_id: string; score: number; status: string; missed_tags: string[]; needs_review: boolean }>;
  suggested_reteach_focus: Array<{ knowledge_tag: string; student_count: number; question_indices: number[]; reason: string }>;
};
type AssignmentSummary = {
  id: string;
  title: string;
  subject: string | null;
  assignee_count: number;
  submitted_count: number;
  completion_rate: number;
  average_score: number | null;
  created_at: string;
  pending_review_count?: number;
  top_weak_tags?: WeakTag[];
  lowest_accuracy_question?: LowAccuracyQuestion | null;
  below_threshold_count?: number;
};
type GradedAnswer = { question_index: number; student_answer: unknown; is_correct: boolean | null; correct_answer: unknown };
type Submission = { student_id: string; score: number | null; status: string; submitted_at: string; answers: GradedAnswer[]; teacher_feedback?: string | null; reviewed_at?: string | null };
type ReviewFlag = { verdict: string; note?: string | null; created_at: string };
type AssignmentDetail = {
  assignment: { id: string; title: string; subject: string | null; questions: Array<{ prompt: string; type: string; knowledge_tag: string | null; reference_answer?: string | null }> };
  submissions: Submission[];
  insights?: AssignmentInsights;
  review_flags?: Record<string, ReviewFlag>;
  open_blind_spot_count?: number;
};

const blankQuestion = (): DraftQuestion => ({
  type: "single_choice", prompt: "", options: ["", "", "", ""], answer: "A", knowledge_tag: "",
});

export default function TeacherAssignmentsPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<"create" | "list">("list");
  const [students, setStudents] = useState<Student[]>([]);
  const [assignments, setAssignments] = useState<AssignmentSummary[]>([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  // create form
  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState("历史");
  const [dueDate, setDueDate] = useState("");
  const [questions, setQuestions] = useState<DraftQuestion[]>([blankQuestion()]);
  const [assignees, setAssignees] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  // AI 出题
  const [aiKps, setAiKps] = useState("");
  const [aiDifficulty, setAiDifficulty] = useState("medium");
  const [aiType, setAiType] = useState("single_choice");
  const [aiSemantic, setAiSemantic] = useState(false);
  const [aiGenerating, setAiGenerating] = useState(false);
  const [aiError, setAiError] = useState("");

  // 讲评课 AI 辅助
  type LectureTopic = {
    tag: string; error_count: number; student_count: number; accuracy: number;
    wrong_options: Array<{ option: string; count: number }>;
    lecture_tip: string; board_keywords: string; sample_exercise: string;
  };
  type LectureReview = { topics: LectureTopic[]; generated_at: string; assignments_analyzed: number };
  const [lectureReview, setLectureReview] = useState<LectureReview | null>(null);
  const [lectureLoading, setLectureLoading] = useState(false);
  const [lectureCopied, setLectureCopied] = useState(false);

  // 作业详情下钻
  const [detail, setDetail] = useState<AssignmentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [reviewDrafts, setReviewDrafts] = useState<Record<string, { score: string; feedback: string }>>({});
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [flagging, setFlagging] = useState<number | null>(null);

  useEffect(() => {
    if (user?.role !== "teacher" && user?.role !== "admin") {
      if (user) setError("仅教师可访问");
      return;
    }
    loadStudents();
    loadAssignments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  async function loadStudents() {
    if (!user?.token) return;
    const res = await fetch(`${API}/api/teacher/students`, { headers: authHeaders(user.token) });
    if (res.ok) setStudents(await res.json());
  }
  async function loadAssignments() {
    if (!user?.token) return;
    const res = await fetch(`${API}/api/teacher/assignments`, { headers: authHeaders(user.token) });
    if (res.ok) setAssignments((await res.json()).assignments || []);
  }
  async function loadDetail(id: string) {
    if (!user?.token) return;
    setDetailLoading(true);
    try {
      const res = await fetch(`${API}/api/teacher/assignments/${id}/submissions`, { headers: authHeaders(user.token) });
      if (res.ok) setDetail(await res.json());
      else setError(`加载详情失败 HTTP ${res.status}`);
    } finally { setDetailLoading(false); }
  }
  async function submitReview(studentId: string) {
    if (!user?.token || !detail) return;
    const draft = reviewDrafts[studentId] || { score: "", feedback: "" };
    const score = Number(draft.score);
    if (!Number.isFinite(score) || score < 0 || score > 100) { setError("请输入 0-100 的分数"); return; }
    setReviewing(studentId); setError("");
    try {
      const res = await fetch(`${API}/api/teacher/assignments/${detail.assignment.id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(user.token) },
        body: JSON.stringify({ student_id: studentId, score, feedback: draft.feedback }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      await loadDetail(detail.assignment.id);
      loadAssignments();
      setMsg("评阅已保存 ✓");
    } catch (e) {
      setError(e instanceof Error ? e.message : "评阅失败");
    } finally { setReviewing(null); }
  }
  async function flagQuestion(questionIndex: number, verdict: "bad_question" | "not_mastered") {
    if (!user?.token || !detail) return;
    setFlagging(questionIndex); setError("");
    try {
      const res = await fetch(`${API}/api/teacher/assignments/${detail.assignment.id}/questions/${questionIndex}/review-flag`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(user.token) },
        body: JSON.stringify({ verdict }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      await loadDetail(detail.assignment.id);
      setMsg(verdict === "bad_question" ? "已标记题目问题 ✓" : "已确认学生未掌握 ✓");
    } catch (e) {
      setError(e instanceof Error ? e.message : "标记失败");
    } finally { setFlagging(null); }
  }
  async function generateLectureReview() {
    if (!user?.token || lectureLoading) return;
    setLectureLoading(true);
    try {
      const res = await fetch(`${API}/api/teacher/lecture-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(user.token) },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setLectureReview(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成讲评稿失败");
    } finally {
      setLectureLoading(false);
    }
  }

  function copyLectureReview() {
    if (!lectureReview) return;
    const lines: string[] = ["===== AI 讲评稿 =====", ""];
    for (const t of lectureReview.topics) {
      lines.push(`【${t.tag}】  错误率 ${100 - t.accuracy}%  (${t.student_count}人答错)`);
      lines.push(`讲解提示：${t.lecture_tip}`);
      lines.push(`板书关键词：${t.board_keywords}`);
      lines.push(`巩固练习：${t.sample_exercise}`);
      lines.push("");
    }
    void navigator.clipboard.writeText(lines.join("\n")).then(() => {
      setLectureCopied(true);
      setTimeout(() => setLectureCopied(false), 2000);
    });
  }

  async function copyInsightOutline() {
    if (!detail?.insights) return;
    const i = detail.insights;
    const lines = [
      `作业讲评提纲：${detail.assignment.title}`,
      `提交情况：${i.submission_rate.submitted}/${i.submission_rate.assignee_count}（${i.submission_rate.percent}%），均分 ${i.average_score ?? "—"}`,
      `待评阅：${i.pending_review_count}，低分学生：${i.below_threshold_students.length}`,
      "",
      "讲评重点：",
      ...(i.suggested_reteach_focus.length ? i.suggested_reteach_focus.map((x, idx) => `${idx + 1}. ${x.knowledge_tag}：${x.reason}`) : ["暂无明显集中薄弱点"]),
      "",
      "低正确率题：",
      ...(i.lowest_accuracy_questions.slice(0, 3).map((q) => `第${q.question_index + 1}题（${q.accuracy}%）：${q.prompt}`)),
      "",
      "需关注学生：",
      ...(i.below_threshold_students.length ? i.below_threshold_students.map((s) => `${s.student_id}：${s.score}分，薄弱点 ${s.missed_tags.join("、") || "—"}`) : ["暂无"]),
    ];
    await navigator.clipboard?.writeText(lines.join("\n"));
    setMsg("讲评提纲已复制 ✓");
  }

  async function generateWithAI() {
    setAiError("");
    const kps = aiKps.split(/[\n,，]+/).map((s) => s.trim()).filter(Boolean);
    if (kps.length === 0) { setAiError("请输入至少一个知识点"); return; }
    if (kps.length > 20) { setAiError("最多 20 个知识点"); return; }
    setAiGenerating(true);
    try {
      const res = await fetch(`${API}/api/teacher/assignments/generate-questions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(user!.token!) },
        body: JSON.stringify({ knowledge_points: kps, difficulty: aiDifficulty, question_type: aiType, subject, semantic_check: aiSemantic }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const generated: Array<{
        knowledge_tag: string; type: string; prompt: string;
        options: string[]; answer: string; explanation: string;
        quality?: { level: string; issues: string[] };
      }> = await res.json();
      const newQs: DraftQuestion[] = generated.map((q) => {
        if (q.type === "true_false") {
          return { type: "true_false", prompt: q.prompt, options: [], answer: q.answer || "正确", knowledge_tag: q.knowledge_tag, quality: q.quality };
        }
        if (q.type === "subjective") {
          return { type: "subjective", prompt: q.prompt, options: [], answer: "", knowledge_tag: q.knowledge_tag, reference_answer: q.explanation || "", quality: q.quality };
        }
        return {
          type: "single_choice",
          prompt: q.prompt,
          options: q.options.length === 4 ? q.options : [...q.options, ...Array(4 - q.options.length).fill("")],
          answer: q.answer,
          knowledge_tag: q.knowledge_tag,
          quality: q.quality,
        };
      });
      // 追加到现有题目后（去掉全空占位题）
      setQuestions((prev) => {
        const nonEmpty = prev.filter((q) => q.prompt.trim());
        return [...nonEmpty, ...newQs];
      });
      setAiKps("");
    } catch (e) {
      setAiError(e instanceof Error ? e.message : "生成失败");
    } finally {
      setAiGenerating(false);
    }
  }

  function updateQuestion(i: number, patch: Partial<DraftQuestion>) {
    setQuestions((qs) => qs.map((q, qi) => (qi === i ? { ...q, ...patch } : q)));
  }
  function updateOption(qi: number, oi: number, val: string) {
    setQuestions((qs) => qs.map((q, i) => i === qi ? { ...q, options: q.options.map((o, j) => j === oi ? val : o) } : q));
  }

  async function save() {
    setError(""); setMsg("");
    if (!title.trim()) { setError("请填写作业标题"); return; }
    if (assignees.length === 0) { setError("请至少选择一名学生"); return; }
    const payloadQuestions = questions
      .filter((q) => q.prompt.trim())
      .map((q) => ({
        type: q.type,
        prompt: q.prompt.trim(),
        options: q.type === "single_choice" ? q.options.filter((o) => o.trim()) : null,
        answer: q.type === "subjective" ? null : q.answer,
        knowledge_tag: q.knowledge_tag.trim() || null,
        reference_answer: q.reference_answer?.trim() || null,
        quality: q.quality ?? null,
      }));
    if (payloadQuestions.length === 0) { setError("请至少填写一道题"); return; }

    setSaving(true);
    try {
      const res = await fetch(`${API}/api/teacher/assignments`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders(user!.token!) },
        body: JSON.stringify({
          title: title.trim(), subject, grade: null, due_date: dueDate || null,
          questions: payloadQuestions, assignee_ids: assignees,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      setMsg("作业已发布 ✓");
      setTitle(""); setDueDate(""); setQuestions([blankQuestion()]); setAssignees([]);
      loadAssignments();
      setTab("list");
    } catch (e) {
      setError(e instanceof Error ? e.message : "发布失败");
    } finally { setSaving(false); }
  }

  return (
    <div className="tasg">
      <style>{CSS}</style>
      <div className="tasg-inner">
        <header className="tasg-head">
          <p className="tasg-eyebrow">ASSIGNMENTS · 布置作业</p>
          <h1 className="tasg-title">作业管理</h1>
        </header>

        <div className="tasg-tabs">
          <button className={`tasg-tab${tab === "list" ? " on" : ""}`} onClick={() => setTab("list")}>作业列表</button>
          <button className={`tasg-tab${tab === "create" ? " on" : ""}`} onClick={() => setTab("create")}>+ 新建作业</button>
        </div>

        {error && <p className="tasg-error">{error}</p>}
        {msg && <p className="tasg-msg">{msg}</p>}

        {tab === "list" && (
          <section>
            {assignments.length === 0 ? (
              <p className="tasg-empty">还没有布置作业，点「新建作业」开始。</p>
            ) : assignments.map((a) => (
              <div key={a.id} className="tasg-row tasg-row-link" onClick={() => { setDetail(null); loadDetail(a.id); }}>
                <div className="tasg-row-main">
                  <span className="tasg-row-title">{a.title}</span>
                  <span className="tasg-row-meta">{a.subject || "—"} · {a.assignee_count} 名学生</span>
                  <div className="tasg-row-insights">
                    {!!a.pending_review_count && <span className="tasg-chip warn">待评阅 {a.pending_review_count}</span>}
                    {(a.top_weak_tags || []).slice(0, 2).map((t) => <span key={t.knowledge_tag} className="tasg-chip">{t.knowledge_tag} {t.student_count}人</span>)}
                    {a.lowest_accuracy_question && <span className="tasg-chip">第{a.lowest_accuracy_question.question_index + 1}题 {a.lowest_accuracy_question.accuracy}%</span>}
                    {!!a.below_threshold_count && <span className="tasg-chip danger">低分 {a.below_threshold_count}人</span>}
                  </div>
                </div>
                <div className="tasg-row-stats">
                  <div className="tasg-stat">
                    <span className="tasg-stat-val">{a.completion_rate}%</span>
                    <span className="tasg-stat-lbl">完成率</span>
                  </div>
                  <div className="tasg-stat">
                    <span className="tasg-stat-val">{a.submitted_count}/{a.assignee_count}</span>
                    <span className="tasg-stat-lbl">已交</span>
                  </div>
                  <div className="tasg-stat">
                    <span className="tasg-stat-val">{a.average_score != null ? a.average_score : "—"}</span>
                    <span className="tasg-stat-lbl">均分</span>
                  </div>
                  <span className="tasg-row-arrow">详情 →</span>
                </div>
              </div>
            ))}
          </section>
        )}

        {/* 作业详情下钻面板 */}
        {tab === "list" && (detail || detailLoading) && (
          <section className="tasg-detail">
            <button className="tasg-back" onClick={() => setDetail(null)}>← 返回列表</button>
            {detailLoading && <p className="tasg-empty">加载中…</p>}
            {detail && (
              <>
                <h2 className="tasg-detail-title">{detail.assignment.title}</h2>
                <p className="tasg-detail-sub">{detail.submissions.length} 人已提交</p>
                {detail.insights && (
                  <div className="tasg-insight-panel">
                    <div className="tasg-insight-head">
                      <span className="tasg-label">讲评洞察</span>
                      <button className="tasg-copy-btn" onClick={copyInsightOutline}>复制讲评提纲</button>
                    </div>
                    <div className="tasg-insight-metrics">
                      <div className="tasg-insight-metric"><b>{detail.insights.submission_rate.percent}%</b><span>提交率</span></div>
                      <div className="tasg-insight-metric"><b>{detail.insights.average_score ?? "—"}</b><span>均分</span></div>
                      <div className="tasg-insight-metric"><b>{detail.insights.pending_review_count}</b><span>待评阅</span></div>
                      <div className="tasg-insight-metric"><b>{detail.insights.below_threshold_students.length}</b><span>低分学生</span></div>
                    </div>
                    <div className="tasg-insight-grid">
                      <div className="tasg-insight-card">
                        <span className="tasg-insight-title">讲评优先级</span>
                        {detail.insights.suggested_reteach_focus.length === 0 ? <p className="tasg-empty compact">暂无集中薄弱点</p> : detail.insights.suggested_reteach_focus.map((x) => (
                          <p key={x.knowledge_tag} className="tasg-insight-line"><b>{x.knowledge_tag}</b>：{x.reason}</p>
                        ))}
                      </div>
                      <div className="tasg-insight-card">
                        <span className="tasg-insight-title">低正确率题</span>
                        {detail.insights.lowest_accuracy_questions.length === 0 ? <p className="tasg-empty compact">暂无客观题统计</p> : (() => {
                          const blindIdx = new Set((detail.insights.quality_blind_spots || []).map((b) => b.question_index));
                          const flags = detail.review_flags || {};
                          return detail.insights.lowest_accuracy_questions.slice(0, 3).map((q) => {
                            const topWrong = q.common_wrong_answers?.[0];
                            const isBlind = blindIdx.has(q.question_index);
                            const flag = flags[String(q.question_index)];
                            return (
                              <div key={q.question_index} className="tasg-insight-qitem">
                                <p className="tasg-insight-line">
                                  第{q.question_index + 1}题 · {q.accuracy}%：{q.prompt.slice(0, 34)}
                                  {isBlind && !flag && <span className="tasg-blindspot" title="AI 质检判为合格，但真实正确率异常低，建议复核题目本身">⚠ 质检盲区</span>}
                                  {flag?.verdict === "bad_question" && <span className="tasg-blindspot done" title="教师已标记：题目本身有问题">已标记题目问题</span>}
                                  {flag?.verdict === "not_mastered" && <span className="tasg-blindspot muted" title="教师已确认：题目无误，学生未掌握">学生未掌握</span>}
                                </p>
                                {topWrong && (
                                  <p className="tasg-insight-wrong">最多错选「{topWrong.answer}」· {topWrong.count}人</p>
                                )}
                                {isBlind && !flag && (
                                  <div className="tasg-blindspot-actions">
                                    <button type="button" disabled={flagging === q.question_index}
                                      onClick={() => flagQuestion(q.question_index, "bad_question")}>题目有问题</button>
                                    <button type="button" disabled={flagging === q.question_index}
                                      onClick={() => flagQuestion(q.question_index, "not_mastered")}>学生没掌握</button>
                                  </div>
                                )}
                              </div>
                            );
                          });
                        })()}
                      </div>
                    </div>
                    {detail.insights.below_threshold_students.length > 0 && (
                      <div className="tasg-focus-students">
                        <span className="tasg-insight-title">需关注学生</span>
                        {detail.insights.below_threshold_students.slice(0, 5).map((s) => (
                          <span key={s.student_id} className="tasg-focus-chip">{s.student_id} · {s.score}分{s.missed_tags.length ? ` · ${s.missed_tags.join("、")}` : ""}</span>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* AI 讲评稿面板 */}
                <div className="tasg-lecture-panel">
                  <div className="tasg-lecture-head">
                    <span className="tasg-label">AI 讲评稿</span>
                    <div className="tasg-lecture-actions">
                      <button className="tasg-copy-btn" onClick={generateLectureReview} disabled={lectureLoading}>
                        {lectureLoading ? "生成中…" : lectureReview ? "重新生成" : "✦ 生成讲评稿"}
                      </button>
                      {lectureReview && lectureReview.topics.length > 0 && (
                        <button className="tasg-copy-btn" onClick={copyLectureReview}>
                          {lectureCopied ? "已复制 ✓" : "复制全文"}
                        </button>
                      )}
                    </div>
                  </div>
                  {lectureReview && lectureReview.topics.length === 0 && (
                    <p className="tasg-empty compact" style={{ marginTop: 6 }}>暂无足够答题数据，请在学生完成作业后再生成。</p>
                  )}
                  {lectureReview && lectureReview.topics.length > 0 && (
                    <div className="tasg-lecture-topics">
                      {lectureReview.topics.map((t) => (
                        <div key={t.tag} className="tasg-lecture-topic">
                          <div className="tasg-lecture-topic-head">
                            <span className="tasg-lecture-tag">{t.tag}</span>
                            <span className="tasg-lecture-stat">{t.student_count} 人答错 · 正确率 {t.accuracy}%</span>
                          </div>
                          <p className="tasg-lecture-tip"><span className="tasg-lecture-label">讲解提示</span>{t.lecture_tip}</p>
                          <p className="tasg-lecture-keywords"><span className="tasg-lecture-label">板书关键词</span>{t.board_keywords}</p>
                          <p className="tasg-lecture-exercise"><span className="tasg-lecture-label">即时练习</span>{t.sample_exercise}</p>
                        </div>
                      ))}
                    </div>
                  )}
                  {lectureReview && (
                    <p className="tasg-lecture-footer">基于近 {lectureReview.assignments_analyzed} 份作业数据 · {new Date(lectureReview.generated_at).toLocaleString("zh-CN")}</p>
                  )}
                </div>

                {detail.submissions.length === 0 ? (
                  <p className="tasg-empty">暂无学生提交</p>
                ) : detail.submissions.map((sub) => (
                  <div key={sub.student_id} className="tasg-sub-card">
                    <div className="tasg-sub-head">
                      <span className="tasg-sub-student">{sub.student_id}</span>
                      <span className={`tasg-sub-score ${sub.score != null && sub.score >= 60 ? "pass" : "fail"}`}>
                        {sub.score != null ? `${sub.score}分` : "待评阅"}
                      </span>
                    </div>
                    <div className="tasg-sub-answers">
                      {sub.answers.map((ans, i) => {
                        const q = detail.assignment.questions[ans.question_index];
                        return (
                          <div key={i} className={`tasg-ans-row ${ans.is_correct === true ? "ok" : ans.is_correct === false ? "ng" : "subjective"}`}>
                            <span className="tasg-ans-icon">{ans.is_correct === true ? "✓" : ans.is_correct === false ? "✗" : "—"}</span>
                            <span className="tasg-ans-prompt">{q?.prompt?.slice(0, 40) || `第${ans.question_index + 1}题`}</span>
                            {ans.is_correct === false && (
                              <span className="tasg-ans-detail">
                                答：{String(ans.student_answer)} · 正确：{String(ans.correct_answer)}
                              </span>
                            )}
                            {ans.is_correct == null && ans.student_answer != null && (
                              <span className="tasg-ans-detail subjective-answer">答：{String(ans.student_answer).slice(0, 60)}</span>
                            )}
                            {q?.reference_answer && <span className="tasg-ans-detail subjective-answer">参考：{q.reference_answer.slice(0, 60)}</span>}
                            {q?.knowledge_tag && <span className="tasg-ans-tag">{q.knowledge_tag}</span>}
                          </div>
                        );
                      })}
                    </div>
                    {sub.teacher_feedback && <p className="tasg-review-saved">教师反馈：{sub.teacher_feedback}</p>}
                    {sub.status !== "graded" && (
                      <div className="tasg-review-box">
                        <div className="tasg-label">人工评阅</div>
                        <div className="tasg-review-row">
                          <input
                            className="tasg-input tasg-review-score"
                            type="number"
                            min="0"
                            max="100"
                            placeholder="分数"
                            value={reviewDrafts[sub.student_id]?.score ?? ""}
                            onChange={(e) => setReviewDrafts((d) => ({ ...d, [sub.student_id]: { ...(d[sub.student_id] || { feedback: "" }), score: e.target.value } }))}
                          />
                          <input
                            className="tasg-input"
                            placeholder="反馈（可选，如：论述完整，但缺少史实依据）"
                            value={reviewDrafts[sub.student_id]?.feedback ?? ""}
                            onChange={(e) => setReviewDrafts((d) => ({ ...d, [sub.student_id]: { ...(d[sub.student_id] || { score: "" }), feedback: e.target.value } }))}
                          />
                          <button className="tasg-review-btn" onClick={() => submitReview(sub.student_id)} disabled={reviewing === sub.student_id}>
                            {reviewing === sub.student_id ? "保存中…" : "保存评阅"}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </>
            )}
          </section>
        )}

        {tab === "create" && (
          <section className="tasg-form">
            <label className="tasg-field">
              <span className="tasg-label">作业标题</span>
              <input className="tasg-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="如：第三单元 明清史 随堂测" />
            </label>
            <div className="tasg-field-row">
              <label className="tasg-field">
                <span className="tasg-label">学科</span>
                <input className="tasg-input" value={subject} onChange={(e) => setSubject(e.target.value)} />
              </label>
              <label className="tasg-field">
                <span className="tasg-label">截止日期（可选）</span>
                <input className="tasg-input" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
              </label>
            </div>

            {/* AI 出题区 */}
            <div className="tasg-ai-box">
              <div className="tasg-label">✨ AI 出题</div>
              <p className="tasg-ai-hint">输入知识点，AI 自动 RAG 取材并出题，生成后可逐题编辑修改</p>
              <textarea
                className="tasg-input tasg-ai-textarea"
                placeholder={"每行一个知识点，如：\n鸦片战争\n洋务运动\n戊戌变法"}
                value={aiKps}
                onChange={(e) => setAiKps(e.target.value)}
                rows={3}
              />
              <div className="tasg-ai-row">
                <label className="tasg-answer">
                  题型
                  <select className="tasg-select" value={aiType} onChange={(e) => setAiType(e.target.value)}>
                    <option value="single_choice">单选题</option>
                    <option value="true_false">判断题</option>
                    <option value="subjective">简答题</option>
                  </select>
                </label>
                <label className="tasg-answer">
                  难度
                  <select className="tasg-select" value={aiDifficulty} onChange={(e) => setAiDifficulty(e.target.value)}>
                    <option value="easy">简单</option>
                    <option value="medium">适中</option>
                    <option value="hard">较难</option>
                  </select>
                </label>
                <button className="tasg-ai-btn" onClick={generateWithAI} disabled={aiGenerating}>
                  {aiGenerating ? "AI 出题中…" : "生成题目"}
                </button>
              </div>
              <label className="tasg-ai-semantic">
                <input type="checkbox" checked={aiSemantic} onChange={(e) => setAiSemantic(e.target.checked)} />
                <span>深度质检（AI 复核题目语义，较慢）</span>
              </label>
              {aiError && <p className="tasg-error">{aiError}</p>}
            </div>

            <div className="tasg-label">题目</div>
            {questions.map((q, i) => (
              <div key={i} className="tasg-qcard">
                <div className="tasg-qhead">
                  <span className="tasg-qnum">第 {i + 1} 题</span>
                  <select className="tasg-select" value={q.type} onChange={(e) => updateQuestion(i, { type: e.target.value })}>
                    <option value="single_choice">单选题</option>
                    <option value="true_false">判断题</option>
                    <option value="subjective">主观题</option>
                  </select>
                  {questions.length > 1 && (
                    <button className="tasg-del" onClick={() => setQuestions((qs) => qs.filter((_, j) => j !== i))}>✕</button>
                  )}
                </div>
                <input className="tasg-input" placeholder="题干" value={q.prompt} onChange={(e) => updateQuestion(i, { prompt: e.target.value })} />
                {q.quality && q.quality.level !== "ok" && (
                  <div className={`tasg-quality tasg-quality-${q.quality.level}`}>
                    <span className="tasg-quality-tag">
                      {q.quality.level === "error" ? "⚠ 需修正" : "可优化"}
                    </span>
                    <span className="tasg-quality-issues">{q.quality.issues.join("；")}</span>
                  </div>
                )}
                {q.type === "single_choice" && (
                  <div className="tasg-opts">
                    {q.options.map((opt, oi) => (
                      <div key={oi} className="tasg-opt-row">
                        <span className="tasg-opt-key">{String.fromCharCode(65 + oi)}</span>
                        <input className="tasg-input" placeholder={`选项 ${String.fromCharCode(65 + oi)}`} value={opt}
                          onChange={(e) => updateOption(i, oi, e.target.value)} />
                      </div>
                    ))}
                    <label className="tasg-answer">
                      正确答案
                      <select className="tasg-select" value={q.answer} onChange={(e) => updateQuestion(i, { answer: e.target.value })}>
                        {["A", "B", "C", "D"].map((k) => <option key={k} value={k}>{k}</option>)}
                      </select>
                    </label>
                  </div>
                )}
                {q.type === "true_false" && (
                  <label className="tasg-answer">
                    正确答案
                    <select className="tasg-select" value={q.answer} onChange={(e) => updateQuestion(i, { answer: e.target.value })}>
                      <option value="正确">正确</option>
                      <option value="错误">错误</option>
                    </select>
                  </label>
                )}
                {q.type === "subjective" && (
                  <div className="tasg-opts">
                    <p className="tasg-hint">主观题由老师提交后人工评阅</p>
                    <textarea className="tasg-input tasg-ref-answer" placeholder="参考答案要点（可选，仅教师端可见）"
                      value={q.reference_answer || ""}
                      onChange={(e) => updateQuestion(i, { reference_answer: e.target.value })} />
                  </div>
                )}
              </div>
            ))}
            <button className="tasg-add" onClick={() => setQuestions((qs) => [...qs, blankQuestion()])}>+ 添加题目</button>

            <div className="tasg-label">分配学生 <span className="tasg-count">{assignees.length}</span></div>
            <div className="tasg-students">
              <button className="tasg-selall" onClick={() => setAssignees(assignees.length === students.length ? [] : students.map((s) => s.actor_id))}>
                {assignees.length === students.length ? "取消全选" : "全选"}
              </button>
              {students.map((s) => (
                <label key={s.actor_id} className={`tasg-student${assignees.includes(s.actor_id) ? " on" : ""}`}>
                  <input type="checkbox" checked={assignees.includes(s.actor_id)}
                    onChange={(e) => setAssignees((a) => e.target.checked ? [...a, s.actor_id] : a.filter((x) => x !== s.actor_id))} />
                  {s.display_name || s.actor_id}
                </label>
              ))}
            </div>

            <button className="tasg-publish" onClick={save} disabled={saving}>
              {saving ? "发布中…" : "发布作业"}
            </button>
          </section>
        )}
      </div>
    </div>
  );
}

const CSS = `
.tasg { min-height:100vh; color:var(--ink,#1a1612); }
.tasg-inner { max-width:760px; margin:0 auto; padding:36px 22px 100px; }
.tasg-eyebrow { font-size:10px; letter-spacing:.24em; color:var(--cinnabar,#b7422b); margin:0 0 6px; }
.tasg-title { font-size:26px; font-weight:700; margin:0 0 20px; }
.tasg-tabs { display:flex; gap:8px; margin-bottom:20px; border-bottom:1px solid #e5e0d5; }
.tasg-tab { background:none; border:none; padding:10px 4px; margin-right:16px; font-size:14px; font-weight:600;
  color:var(--muted,#7a7068); cursor:pointer; border-bottom:2px solid transparent; }
.tasg-tab.on { color:var(--cinnabar,#b7422b); border-bottom-color:var(--cinnabar,#b7422b); }
.tasg-error { font-size:13px; color:#c0392b; margin:8px 0; }
.tasg-msg { font-size:13px; color:var(--jade,#2d6a4f); margin:8px 0; }
.tasg-empty { font-size:13px; color:var(--muted,#7a7068); padding:20px 0; }
.tasg-row { display:flex; justify-content:space-between; align-items:center; gap:12px; background:#fff;
  border:1px solid #e5e0d5; border-radius:10px; padding:14px 16px; margin-bottom:10px; }
.tasg-row-main { display:flex; flex-direction:column; gap:4px; }
.tasg-row-title { font-size:15px; font-weight:600; }
.tasg-row-meta { font-size:12px; color:var(--muted,#7a7068); }
.tasg-row-insights { display:flex; flex-wrap:wrap; gap:6px; margin-top:4px; }
.tasg-chip { font-size:11px; background:#f0ebe0; color:var(--muted,#7a7068); border-radius:12px; padding:2px 8px; }
.tasg-chip.warn { background:#fff3d8; color:#8a5a00; }
.tasg-chip.danger { background:#fdf1ee; color:var(--cinnabar,#b7422b); }
.tasg-row-stats { display:flex; gap:18px; }
.tasg-stat { display:flex; flex-direction:column; align-items:center; }
.tasg-stat-val { font-size:17px; font-weight:700; }
.tasg-stat-lbl { font-size:10px; color:var(--muted,#7a7068); }
.tasg-form { display:flex; flex-direction:column; gap:14px; }
.tasg-field { display:flex; flex-direction:column; gap:5px; flex:1; }
.tasg-field-row { display:flex; gap:12px; }
.tasg-label { font-size:13px; font-weight:600; display:flex; align-items:center; gap:8px; }
.tasg-count { font-size:11px; background:var(--cinnabar,#b7422b); color:#fff; border-radius:10px; padding:1px 7px; }
.tasg-input { border:1px solid #e5e0d5; border-radius:7px; padding:9px 11px; font-size:14px; font-family:inherit; width:100%; }
.tasg-select { border:1px solid #e5e0d5; border-radius:7px; padding:7px 9px; font-size:13px; font-family:inherit; }
.tasg-qcard { background:#fff; border:1px solid #e5e0d5; border-radius:10px; padding:14px 16px; display:flex; flex-direction:column; gap:10px; }
.tasg-qhead { display:flex; align-items:center; gap:12px; }
.tasg-qnum { font-size:13px; font-weight:700; }
.tasg-del { margin-left:auto; background:none; border:none; color:#c0392b; cursor:pointer; font-size:14px; }
.tasg-opts { display:flex; flex-direction:column; gap:7px; }
.tasg-opt-row { display:flex; align-items:center; gap:8px; }
.tasg-opt-key { font-weight:700; color:var(--cinnabar,#b7422b); width:18px; }
.tasg-answer { display:flex; align-items:center; gap:8px; font-size:13px; font-weight:600; }
.tasg-hint { font-size:12px; color:var(--muted,#7a7068); margin:0; }
.tasg-quality { display:flex; align-items:baseline; gap:8px; font-size:12px; padding:6px 10px; border-radius:7px; flex-wrap:wrap; }
.tasg-quality-error { background:#fdecea; border:1px solid #f5c2bc; }
.tasg-quality-warn { background:#fdf6e3; border:1px solid #efdca6; }
.tasg-quality-tag { font-weight:700; white-space:nowrap; }
.tasg-quality-error .tasg-quality-tag { color:#c0392b; }
.tasg-quality-warn .tasg-quality-tag { color:#b0862b; }
.tasg-quality-issues { color:var(--ink,#4a4038); }
.tasg-ref-answer { min-height:64px; resize:vertical; }
.tasg-add { align-self:flex-start; background:#f0ebe0; border:1px dashed #c8b89a; border-radius:7px;
  padding:8px 16px; font-size:13px; cursor:pointer; color:var(--ink,#1a1612); }
.tasg-students { display:flex; flex-wrap:wrap; gap:8px; }
.tasg-selall { background:none; border:1px solid #e5e0d5; border-radius:14px; padding:5px 12px; font-size:12px; cursor:pointer; }
.tasg-student { display:flex; align-items:center; gap:5px; border:1px solid #e5e0d5; border-radius:14px;
  padding:5px 12px; font-size:13px; cursor:pointer; }
.tasg-student.on { background:#f0ebe0; border-color:var(--cinnabar,#b7422b); }
.tasg-publish { background:var(--cinnabar,#b7422b); color:#fff; border:none; border-radius:9px; padding:13px;
  font-size:15px; font-weight:600; cursor:pointer; margin-top:8px; }
.tasg-publish:disabled { opacity:.6; cursor:not-allowed; }
.tasg-ai-box { background:#f8f4ef; border:1px solid #e5e0d5; border-radius:10px; padding:16px; display:flex; flex-direction:column; gap:10px; }
.tasg-ai-hint { font-size:12px; color:var(--muted,#7a7068); margin:0; }
.tasg-ai-textarea { resize:vertical; min-height:72px; }
.tasg-ai-row { display:flex; align-items:center; gap:12px; }
.tasg-ai-btn { margin-left:auto; background:var(--cinnabar,#b7422b); color:#fff; border:none; border-radius:8px;
  padding:9px 20px; font-size:14px; font-weight:600; cursor:pointer; white-space:nowrap; }
.tasg-ai-btn:disabled { opacity:.6; cursor:not-allowed; }
.tasg-ai-semantic { display:flex; align-items:center; gap:6px; margin-top:8px; font-size:12px; color:var(--muted,#7a7068); cursor:pointer; }
.tasg-ai-semantic input { cursor:pointer; }
/* 列表行可点击 */
.tasg-row-link { cursor:pointer; transition:border-color .15s, transform .1s; }
.tasg-row-link:hover { border-color:var(--cinnabar,#b7422b); transform:translateX(2px); }
.tasg-row-arrow { font-size:12px; font-weight:600; color:var(--cinnabar,#b7422b); white-space:nowrap; margin-left:8px; }
.tasg-back { background:none; border:none; color:var(--muted,#7a7068); font-size:13px; cursor:pointer; padding:0 0 16px; display:block; }
/* 详情面板 */
.tasg-detail { margin-top:24px; border-top:1px solid #e5e0d5; padding-top:20px; }
.tasg-detail-title { font-size:20px; font-weight:700; margin:0 0 4px; }
.tasg-detail-sub { font-size:13px; color:var(--muted,#7a7068); margin:0 0 16px; }
.tasg-insight-panel { background:#fffaf3; border:1px solid #e5d4b8; border-radius:12px; padding:14px 16px; margin:0 0 16px; display:flex; flex-direction:column; gap:12px; }
.tasg-insight-head { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.tasg-copy-btn { border:1px solid #d8c5a5; background:#fff; border-radius:7px; padding:6px 10px; font-size:12px; cursor:pointer; color:var(--ink,#1a1612); }
.tasg-insight-metrics { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }
.tasg-insight-metric { background:#fff; border:1px solid #efe4d2; border-radius:9px; padding:10px; display:flex; flex-direction:column; align-items:center; gap:2px; }
.tasg-insight-metric b { font-size:18px; }
.tasg-insight-metric span { font-size:11px; color:var(--muted,#7a7068); }
.tasg-insight-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.tasg-insight-card { background:#fff; border:1px solid #efe4d2; border-radius:9px; padding:10px 12px; }
.tasg-insight-title { display:block; font-size:12px; font-weight:700; margin-bottom:6px; color:var(--cinnabar,#b7422b); }
.tasg-insight-line { font-size:12px; line-height:1.55; margin:4px 0; color:var(--ink,#1a1612); }
.tasg-insight-qitem { margin:5px 0; }
.tasg-insight-wrong { font-size:11px; color:var(--cinnabar,#b7422b); margin:1px 0 4px 10px; opacity:.85; }
.tasg-blindspot { display:inline-block; margin-left:6px; padding:0 6px; font-size:10px; font-weight:700; line-height:16px; border-radius:8px; color:#fff; background:var(--cinnabar,#b7422b); vertical-align:middle; }
.tasg-blindspot.done { background:#8a5a2b; }
.tasg-blindspot.muted { background:transparent; color:var(--muted,#8a8178); font-weight:600; border:1px solid var(--border,#e0d8cc); }
.tasg-blindspot-actions { display:flex; gap:8px; margin:2px 0 6px 10px; }
.tasg-blindspot-actions button { font-size:11px; padding:3px 10px; border-radius:6px; border:1px solid var(--border,#e0d8cc); background:var(--paper,#fff); color:var(--ink,#1a1612); cursor:pointer; }
.tasg-blindspot-actions button:hover:not(:disabled) { border-color:var(--cinnabar,#b7422b); color:var(--cinnabar,#b7422b); }
.tasg-blindspot-actions button:disabled { opacity:.5; cursor:default; }
.tasg-empty.compact { padding:0; margin:0; }
.tasg-focus-students { display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
.tasg-focus-chip { font-size:11px; background:#fdf1ee; color:var(--cinnabar,#b7422b); border-radius:12px; padding:3px 8px; }
.tasg-sub-card { background:#fff; border:1px solid #e5e0d5; border-radius:10px; padding:14px 16px; margin-bottom:12px; }
.tasg-sub-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
.tasg-sub-student { font-size:14px; font-weight:600; }
.tasg-sub-score { font-size:16px; font-weight:700; }
.tasg-sub-score.pass { color:var(--jade,#2d6a4f); }
.tasg-sub-score.fail { color:var(--cinnabar,#b7422b); }
.tasg-sub-answers { display:flex; flex-direction:column; gap:6px; }
.tasg-ans-row { display:flex; align-items:baseline; gap:8px; font-size:13px; padding:6px 8px; border-radius:6px; }
.tasg-ans-row.ok { background:#f0faf5; }
.tasg-ans-row.ng { background:#fdf1ee; }
.tasg-ans-row.subjective { background:#f8f6f2; }
.tasg-ans-icon { font-size:12px; font-weight:700; width:14px; flex-shrink:0; }
.tasg-ans-row.ok .tasg-ans-icon { color:var(--jade,#2d6a4f); }
.tasg-ans-row.ng .tasg-ans-icon { color:var(--cinnabar,#b7422b); }
.tasg-ans-prompt { flex:1; color:var(--ink,#1a1612); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:240px; }
.tasg-ans-detail { font-size:12px; color:var(--cinnabar,#b7422b); white-space:nowrap; }
.tasg-ans-tag { font-size:11px; background:#f0ebe0; border-radius:4px; padding:1px 6px; white-space:nowrap; margin-left:auto; }
.tasg-ans-detail.subjective-answer { color:var(--muted,#7a7068); white-space:normal; }
.tasg-review-saved { font-size:12px; color:var(--jade,#2d6a4f); background:#f0faf5; border-radius:6px; padding:7px 9px; margin:10px 0 0; }
.tasg-review-box { margin-top:12px; padding-top:12px; border-top:1px dashed #e5e0d5; display:flex; flex-direction:column; gap:8px; }
.tasg-review-row { display:flex; gap:8px; align-items:center; }
.tasg-review-score { width:92px; flex:none; }
.tasg-review-btn { background:var(--jade,#2d6a4f); color:#fff; border:none; border-radius:7px; padding:9px 14px; font-size:13px; font-weight:600; cursor:pointer; white-space:nowrap; }
.tasg-review-btn:disabled { opacity:.6; cursor:not-allowed; }
/* 讲评稿面板 */
.tasg-lecture-panel { background:#f3f8f2; border:1px solid #c5ddc0; border-radius:12px; padding:14px 16px; margin:0 0 16px; display:flex; flex-direction:column; gap:10px; }
.tasg-lecture-head { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
.tasg-lecture-actions { display:flex; gap:8px; flex-wrap:wrap; }
.tasg-lecture-topics { display:flex; flex-direction:column; gap:10px; }
.tasg-lecture-topic { background:#fff; border:1px solid #d5e9d0; border-radius:9px; padding:12px 14px; }
.tasg-lecture-topic-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; gap:10px; }
.tasg-lecture-tag { font-size:13px; font-weight:700; color:#2d6a2d; background:#eaf4e7; border-radius:5px; padding:2px 10px; }
.tasg-lecture-stat { font-size:11px; color:var(--muted,#7a7068); }
.tasg-lecture-tip, .tasg-lecture-keywords, .tasg-lecture-exercise { font-size:13px; line-height:1.7; margin:3px 0; color:var(--ink,#1a1612); }
.tasg-lecture-label { font-size:11px; font-weight:700; color:#4a7a3c; margin-right:6px; background:#e8f5e4; border-radius:3px; padding:1px 5px; white-space:nowrap; }
.tasg-lecture-footer { font-size:11px; color:var(--muted,#7a7068); margin:2px 0 0; }
`;
