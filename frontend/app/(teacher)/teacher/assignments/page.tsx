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
};
type GradedAnswer = { question_index: number; student_answer: unknown; is_correct: boolean | null; correct_answer: unknown };
type Submission = { student_id: string; score: number | null; status: string; submitted_at: string; answers: GradedAnswer[] };
type AssignmentDetail = {
  assignment: { id: string; title: string; subject: string | null; questions: Array<{ prompt: string; type: string; knowledge_tag: string | null }> };
  submissions: Submission[];
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
  const [aiGenerating, setAiGenerating] = useState(false);
  const [aiError, setAiError] = useState("");

  // 作业详情下钻
  const [detail, setDetail] = useState<AssignmentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

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
        body: JSON.stringify({ knowledge_points: kps, difficulty: aiDifficulty, subject }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const generated: Array<{
        knowledge_tag: string; prompt: string;
        options: string[]; answer: string; explanation: string;
      }> = await res.json();
      const newQs: DraftQuestion[] = generated.map((q) => ({
        type: "single_choice",
        prompt: q.prompt,
        options: q.options.length === 4 ? q.options : [...q.options, ...Array(4 - q.options.length).fill("")],
        answer: q.answer,
        knowledge_tag: q.knowledge_tag,
      }));
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
                            {q?.knowledge_tag && <span className="tasg-ans-tag">{q.knowledge_tag}</span>}
                          </div>
                        );
                      })}
                    </div>
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
                {q.type === "subjective" && <p className="tasg-hint">主观题由老师提交后人工评阅</p>}
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
/* 列表行可点击 */
.tasg-row-link { cursor:pointer; transition:border-color .15s, transform .1s; }
.tasg-row-link:hover { border-color:var(--cinnabar,#b7422b); transform:translateX(2px); }
.tasg-row-arrow { font-size:12px; font-weight:600; color:var(--cinnabar,#b7422b); white-space:nowrap; margin-left:8px; }
.tasg-back { background:none; border:none; color:var(--muted,#7a7068); font-size:13px; cursor:pointer; padding:0 0 16px; display:block; }
/* 详情面板 */
.tasg-detail { margin-top:24px; border-top:1px solid #e5e0d5; padding-top:20px; }
.tasg-detail-title { font-size:20px; font-weight:700; margin:0 0 4px; }
.tasg-detail-sub { font-size:13px; color:var(--muted,#7a7068); margin:0 0 16px; }
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
`;
