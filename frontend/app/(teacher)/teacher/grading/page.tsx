"use client";

import { useEffect, useState } from "react";
import { authHeaders } from "@/lib/auth";
import { useAuth } from "@/contexts/AuthContext";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type HomeworkGradedItem = {
  item_id: string;
  question: string;
  student_answer: string;
  score: number;
  max_score: number;
  grade_level: string;
  is_correct: boolean;
  strengths: string[];
  issues: string[];
  missing_points: string[];
  knowledge_tags: string[];
  correct_answer?: string | null;
  explanation?: string;
  revision_suggestion: string;
};

type HomeworkGradeResponse = {
  total_score: number;
  max_score: number;
  normalized_score: number;
  grade_level: string;
  items: HomeworkGradedItem[];
  overall_feedback: string;
  weak_points: string[];
  follow_up_quiz: { question: string; answer: string }[];
  needs_human_review: boolean;
  review_reason?: string | null;
  event_id?: string | null;
  warnings: string[];
};

type ExtractedHomeworkItem = {
  item_id: string;
  question: string;
  student_answer: string;
  reference_context: string;
  question_type: string;
  options: string[];
  correct_answer?: string | null;
  knowledge_tags: string[];
  confidence: string;
  warnings: string[];
};

type HomeworkGradeRequest = {
  task_type: string;
  grade?: string | null;
  subject?: string | null;
  student_id?: string | null;
  items: ExtractedHomeworkItem[];
};

type Review = {
  id: string;
  student_id: string | null;
  actor_id: string;
  grade_request: HomeworkGradeRequest;
  grade_result: HomeworkGradeResponse;
  needs_human_review: boolean;
  decision: string;
  teacher_id: string | null;
  teacher_note: string | null;
  teacher_score: number | null;
  created_at: string;
  reviewed_at: string | null;
};

type TabType = "pending" | "history" | "all";

function formatDate(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function scorePercent(score: number, max: number): number {
  if (!max || max === 0) return 0;
  return Math.round((score / max) * 100);
}

export default function TeacherGradingPage() {
  const { user } = useAuth();
  const [reviews, setReviews] = useState<Review[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<TabType>("pending");
  const [selectedReview, setSelectedReview] = useState<Review | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [rejectModal, setRejectModal] = useState<{ reviewId: string; reason: string; addToEval: boolean } | null>(null);
  const [editModal, setEditModal] = useState<{ reviewId: string; score: string; note: string } | null>(null);

  useEffect(() => {
    if (user?.role !== "teacher" && user?.role !== "admin") {
      setError("仅教师可访问此页面");
      setLoading(false);
      return;
    }
    fetchReviews();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, activeTab]);

  async function fetchReviews() {
    if (!user?.token) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError("");

    try {
      const decision = activeTab === "pending" ? "pending" : activeTab === "history" ? null : undefined;
      const response = await fetch(
        `${apiBaseUrl}/api/teacher/homework-reviews?decision=${decision || ""}&limit=50`,
        {
          headers: authHeaders(user.token),
        }
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "获取审核列表失败");
      setReviews(data.reviews || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "获取审核列表失败");
    } finally {
      setLoading(false);
    }
  }

  async function applyDecision(reviewId: string, decision: "accepted" | "rejected" | "edited", teacherNote?: string, teacherScore?: number) {
    if (!user?.token) return;

    setSubmitting(true);
    try {
      const response = await fetch(`${apiBaseUrl}/api/teacher/homework-reviews/${reviewId}/decision`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(user.token),
        },
        body: JSON.stringify({
          decision,
          teacher_note: teacherNote,
          teacher_score: teacherScore,
        }),
      });
      if (!response.ok) throw new Error("操作失败");
      await fetchReviews();
      setSelectedReview(null);
      setRejectModal(null);
      setEditModal(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function addToEvalCase(review: Review) {
    if (!user?.token) return;

    try {
      const response = await fetch(`${apiBaseUrl}/api/eval/save-case`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(user.token),
        },
        body: JSON.stringify({
          suite: "homework_grading_smoke",
          name: `review-${review.id}`,
          case: {
            grade_request: review.grade_request,
            grade_result: review.grade_result,
            teacher_decision: review.decision,
            _saved_from_review: true,
          },
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "保存失败");
      alert("已加入回归测试集");
    } catch (err) {
      alert(err instanceof Error ? err.message : "保存失败");
    }
  }

  const pendingCount = reviews.filter((r) => r.decision === "pending").length;
  const acceptedCount = reviews.filter((r) => r.decision === "accepted").length;
  const rejectedCount = reviews.filter((r) => r.decision === "rejected").length;

  if (loading) {
    return (
      <main className="academy-shell">
        <section className="panel">
          <div className="panel-heading-row">
            <div>
              <p className="section-kicker">教师工作台</p>
              <h2>作业审核</h2>
            </div>
          </div>
          <p className="empty-hint">加载中...</p>
        </section>
      </main>
    );
  }

  if ((user?.role !== "teacher" && user?.role !== "admin") || error) {
    return (
      <main className="academy-shell">
        <section className="panel">
          <div className="panel-heading-row">
            <div>
              <p className="section-kicker">教师工作台</p>
              <h2>作业审核</h2>
            </div>
          </div>
          {error && <div className="error-card"><p>{error}</p></div>}
        </section>
      </main>
    );
  }

  return (
    <main className="academy-shell">
      <section className="panel">
        <div className="panel-heading-row">
          <div>
            <p className="section-kicker">教师工作台</p>
            <h2>作业审核</h2>
          </div>
        </div>

        <div className="grading-tabs">
          <button
            className={activeTab === "pending" ? "active" : ""}
            onClick={() => setActiveTab("pending")}
          >
            待审核 ({pendingCount})
          </button>
          <button
            className={activeTab === "history" ? "active" : ""}
            onClick={() => setActiveTab("history")}
          >
            历史记录
          </button>
          <button
            className={activeTab === "all" ? "active" : ""}
            onClick={() => setActiveTab("all")}
          >
            全部
          </button>
        </div>

        {error && <div className="error-card"><p>{error}</p></div>}

        {selectedReview ? (
          <div className="review-detail">
            <button className="back-button" onClick={() => setSelectedReview(null)}>
              ← 返回列表
            </button>

            <div className="review-header">
              <div>
                <h3>学生: {selectedReview.student_id || "匿名"}</h3>
                <p>提交时间: {formatDate(selectedReview.created_at)}</p>
                <p>题型: {selectedReview.grade_request.task_type}</p>
              </div>
              <div className="ai-score">
                <span>AI 评分</span>
                <strong>{selectedReview.grade_result.total_score} / {selectedReview.grade_result.max_score}</strong>
                <span className="grade-badge">{selectedReview.grade_result.grade_level}</span>
              </div>
            </div>

            {selectedReview.grade_result.needs_human_review && (
              <div className="warning-card">
                <strong>⚠️ 需要人工复核</strong>
                <p>{selectedReview.grade_result.review_reason || "题目、答案或 OCR 置信度不足"}</p>
              </div>
            )}

            <div className="review-content">
              <section>
                <h4>原始题目与答案</h4>
                {selectedReview.grade_request.items.map((item, index) => (
                  <div key={item.item_id} className="review-item">
                    <strong>题目 {index + 1}</strong>
                    <p>{item.question}</p>
                    {item.reference_context && (
                      <div className="reference-context">
                        <span>材料:</span>
                        <p>{item.reference_context}</p>
                      </div>
                    )}
                    {item.options && item.options.length > 0 && (
                      <div className="options-list">
                        <span>选项:</span>
                        <ul>
                          {item.options.map((opt, i) => (
                            <li key={i}>{opt}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <div className="student-answer">
                      <span>学生答案:</span>
                      <p>{item.student_answer || "（未作答）"}</p>
                    </div>
                  </div>
                ))}
              </section>

              <section>
                <h4>AI 批改结果</h4>
                <div className="ai-feedback">
                  <p><strong>总体评价:</strong> {selectedReview.grade_result.overall_feedback}</p>
                  {selectedReview.grade_result.weak_points.length > 0 && (
                    <div className="weak-points">
                      <span>薄弱点:</span>
                      <div>
                        {selectedReview.grade_result.weak_points.map((wp) => (
                          <span key={wp} className="weak-point-tag">{wp}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {selectedReview.grade_result.items.map((item, index) => (
                  <div key={item.item_id} className="graded-item">
                    <div className="graded-item-header">
                      <strong>题目 {index + 1}</strong>
                      <span className={`score-badge ${item.is_correct ? "correct" : "incorrect"}`}>
                        {item.score}/{item.max_score}
                      </span>
                    </div>
                    {item.strengths.length > 0 && (
                      <div className="feedback-section">
                        <span>优点:</span>
                        <ul>{item.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
                      </div>
                    )}
                    {item.issues.length > 0 && (
                      <div className="feedback-section">
                        <span>问题:</span>
                        <ul>{item.issues.map((i, idx) => <li key={idx}>{i}</li>)}</ul>
                      </div>
                    )}
                    {item.missing_points.length > 0 && (
                      <div className="feedback-section">
                        <span>缺失要点:</span>
                        <ul>{item.missing_points.map((m, idx) => <li key={idx}>{m}</li>)}</ul>
                      </div>
                    )}
                    {item.explanation && (
                      <div className="feedback-section">
                        <span>解析:</span>
                        <p>{item.explanation}</p>
                      </div>
                    )}
                    <div className="feedback-section">
                      <span>修改建议:</span>
                      <p>{item.revision_suggestion}</p>
                    </div>
                  </div>
                ))}
              </section>
            </div>

            <div className="review-actions">
              <button
                className="primary"
                onClick={() => applyDecision(selectedReview.id, "accepted")}
                disabled={submitting}
              >
                {submitting ? "处理中..." : "确认 AI 批改"}
              </button>
              <button
                className="soft"
                onClick={() => setEditModal({ reviewId: selectedReview.id, score: String(selectedReview.grade_result.total_score), note: "" })}
                disabled={submitting}
              >
                修改分数
              </button>
              <button
                className="soft danger"
                onClick={() => setRejectModal({ reviewId: selectedReview.id, reason: "", addToEval: false })}
                disabled={submitting}
              >
                拒绝
              </button>
              <button
                className="soft"
                onClick={() => addToEvalCase(selectedReview)}
              >
                加入回归测试
              </button>
            </div>
          </div>
        ) : (
          <div className="review-list">
            {reviews.length === 0 ? (
              <p className="empty-hint">
                {activeTab === "pending" ? "暂无待审核的作业" : "暂无审核记录"}
              </p>
            ) : (
              reviews.map((review) => (
                <article
                  key={review.id}
                  className="review-card"
                  onClick={() => setSelectedReview(review)}
                >
                  <div className="review-card-header">
                    <strong>{review.student_id || "匿名学生"}</strong>
                    <span className={`decision-badge ${review.decision}`}>
                      {review.decision === "pending" ? "待审核" : review.decision === "accepted" ? "已确认" : "已拒绝"}
                    </span>
                  </div>
                  <div className="review-card-meta">
                    <span>{formatDate(review.created_at)}</span>
                    <span>{review.grade_request.task_type}</span>
                  </div>
                  <div className="review-card-score">
                    <span>AI 评分:</span>
                    <strong>{review.grade_result.total_score} / {review.grade_result.max_score}</strong>
                    <span className="grade-badge">{review.grade_result.grade_level}</span>
                  </div>
                  {review.needs_human_review && (
                    <div className="review-card-warning">
                      ⚠️ 需要人工复核
                    </div>
                  )}
                </article>
              ))
            )}
          </div>
        )}
      </section>

      {rejectModal && (
        <div className="modal-overlay" onClick={() => setRejectModal(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>拒绝批改结果</h3>
            <p>请说明拒绝原因（可选）:</p>
            <textarea
              value={rejectModal.reason}
              onChange={(e) => setRejectModal({ ...rejectModal, reason: e.target.value })}
              placeholder="例如：评分偏低、解析不准确等"
            />
            <label className="modal-checkbox">
              <input
                type="checkbox"
                checked={rejectModal.addToEval}
                onChange={(e) => setRejectModal({ ...rejectModal, addToEval: e.target.checked })}
              />
              <span>加入回归测试集</span>
            </label>
            <div className="modal-actions">
              <button
                className="soft"
                onClick={() => setRejectModal(null)}
              >
                取消
              </button>
              <button
                className="danger"
                onClick={() => {
                  applyDecision(rejectModal.reviewId, "rejected", rejectModal.reason || undefined);
                  if (rejectModal.addToEval) {
                    const review = reviews.find((r) => r.id === rejectModal.reviewId);
                    if (review) addToEvalCase(review);
                  }
                }}
                disabled={submitting}
              >
                {submitting ? "处理中..." : "确认拒绝"}
              </button>
            </div>
          </div>
        </div>
      )}

      {editModal && (
        <div className="modal-overlay" onClick={() => setEditModal(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>修改分数</h3>
            <label>
              <span>新分数:</span>
              <input
                type="number"
                value={editModal.score}
                onChange={(e) => setEditModal({ ...editModal, score: e.target.value })}
                min="0"
                max={selectedReview?.grade_result.max_score || 100}
              />
            </label>
            <label>
              <span>备注:</span>
              <textarea
                value={editModal.note}
                onChange={(e) => setEditModal({ ...editModal, note: e.target.value })}
                placeholder="修改原因（可选）"
              />
            </label>
            <div className="modal-actions">
              <button
                className="soft"
                onClick={() => setEditModal(null)}
              >
                取消
              </button>
              <button
                className="primary"
                onClick={() => {
                  const newScore = parseFloat(editModal.score);
                  if (isNaN(newScore)) {
                    alert("请输入有效的分数");
                    return;
                  }
                  applyDecision(editModal.reviewId, "edited", editModal.note || undefined, newScore);
                }}
                disabled={submitting}
              >
                {submitting ? "处理中..." : "确认修改"}
              </button>
            </div>
          </div>
        </div>
      )}

      <style jsx>{`
        .grading-tabs {
          display: flex;
          gap: 8px;
          margin-bottom: 24px;
          padding-bottom: 16px;
          border-bottom: 1px solid var(--border, #e5e7eb);
        }

        .grading-tabs button {
          padding: 8px 16px;
          border: 1px solid var(--border, #e5e7eb);
          background: var(--bg, #ffffff);
          border-radius: 6px;
          cursor: pointer;
          font-size: 0.9rem;
          color: var(--text, #1f2937);
          transition: all 0.2s;
        }

        .grading-tabs button:hover {
          border-color: var(--accent, #4b9560);
        }

        .grading-tabs button.active {
          background: var(--accent, #4b9560);
          color: white;
          border-color: var(--accent, #4b9560);
        }

        .review-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .review-card {
          padding: 16px;
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 8px;
          background: var(--bg, #ffffff);
          cursor: pointer;
          transition: all 0.2s;
        }

        .review-card:hover {
          border-color: var(--accent, #4b9560);
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        }

        .review-card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
        }

        .review-card-header strong {
          font-size: 1rem;
        }

        .decision-badge {
          padding: 4px 8px;
          border-radius: 4px;
          font-size: 0.8rem;
          font-weight: 500;
        }

        .decision-badge.pending {
          background: var(--warning-bg, #fef3c7);
          color: var(--warning-text, #92400e);
        }

        .decision-badge.accepted {
          background: var(--success-bg, #d1fae5);
          color: var(--success-text, #065f46);
        }

        .decision-badge.rejected {
          background: var(--danger-bg, #fee2e2);
          color: var(--danger-text, #991b1b);
        }

        .review-card-meta {
          display: flex;
          gap: 16px;
          font-size: 0.85rem;
          color: var(--text-muted, #6b7280);
          margin-bottom: 8px;
        }

        .review-card-score {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.9rem;
        }

        .review-card-score strong {
          color: var(--accent, #4b9560);
        }

        .grade-badge {
          padding: 2px 8px;
          background: var(--bg-muted, #f3f4f6);
          border-radius: 4px;
          font-size: 0.8rem;
        }

        .review-card-warning {
          margin-top: 8px;
          padding: 8px;
          background: var(--warning-bg, #fef3c7);
          border-radius: 4px;
          font-size: 0.85rem;
          color: var(--warning-text, #92400e);
        }

        .review-detail {
          padding: 24px;
        }

        .back-button {
          padding: 8px 16px;
          border: 1px solid var(--border, #e5e7eb);
          background: var(--bg, #ffffff);
          border-radius: 6px;
          cursor: pointer;
          margin-bottom: 24px;
        }

        .review-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          padding: 16px;
          background: var(--bg-muted, #f3f4f6);
          border-radius: 8px;
          margin-bottom: 24px;
        }

        .review-header h3 {
          margin: 0 0 8px 0;
        }

        .review-header p {
          margin: 4px 0;
          color: var(--text-muted, #6b7280);
          font-size: 0.9rem;
        }

        .ai-score {
          text-align: right;
        }

        .ai-score span {
          display: block;
          font-size: 0.85rem;
          color: var(--text-muted, #6b7280);
        }

        .ai-score strong {
          display: block;
          font-size: 1.5rem;
          color: var(--accent, #4b9560);
        }

        .warning-card {
          padding: 12px 16px;
          background: var(--warning-bg, #fef3c7);
          border-radius: 8px;
          margin-bottom: 24px;
        }

        .warning-card strong {
          display: block;
          margin-bottom: 4px;
          color: var(--warning-text, #92400e);
        }

        .warning-card p {
          margin: 0;
          color: var(--warning-text, #92400e);
        }

        .review-content {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 24px;
          margin-bottom: 24px;
        }

        @media (max-width: 768px) {
          .review-content {
            grid-template-columns: 1fr;
          }
        }

        .review-content section {
          padding: 16px;
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 8px;
        }

        .review-content h4 {
          margin: 0 0 16px 0;
          padding-bottom: 8px;
          border-bottom: 1px solid var(--border, #e5e7eb);
        }

        .review-item {
          padding: 12px;
          background: var(--bg-muted, #f3f4f6);
          border-radius: 6px;
          margin-bottom: 12px;
        }

        .review-item strong {
          display: block;
          margin-bottom: 8px;
        }

        .reference-context,
        .options-list,
        .student-answer {
          margin-top: 8px;
        }

        .reference-context span,
        .options-list span,
        .student-answer span {
          display: block;
          font-size: 0.85rem;
          color: var(--text-muted, #6b7280);
          margin-bottom: 4px;
        }

        .options-list ul {
          margin: 4px 0 0 0;
          padding-left: 20px;
        }

        .student-answer p {
          margin: 4px 0 0 0;
          padding: 8px;
          background: var(--bg, #ffffff);
          border-radius: 4px;
        }

        .ai-feedback {
          padding: 12px;
          background: var(--accent-light, #f0fdf4);
          border-radius: 6px;
          margin-bottom: 16px;
        }

        .weak-points {
          margin-top: 12px;
        }

        .weak-points span {
          display: block;
          font-size: 0.85rem;
          color: var(--text-muted, #6b7280);
          margin-bottom: 4px;
        }

        .weak-points div {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .weak-point-tag {
          padding: 4px 8px;
          background: var(--danger-bg, #fee2e2);
          color: var(--danger-text, #991b1b);
          border-radius: 4px;
          font-size: 0.85rem;
        }

        .graded-item {
          padding: 12px;
          background: var(--bg-muted, #f3f4f6);
          border-radius: 6px;
          margin-bottom: 12px;
        }

        .graded-item-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
        }

        .score-badge {
          padding: 4px 8px;
          border-radius: 4px;
          font-size: 0.85rem;
          font-weight: 500;
        }

        .score-badge.correct {
          background: var(--success-bg, #d1fae5);
          color: var(--success-text, #065f46);
        }

        .score-badge.incorrect {
          background: var(--danger-bg, #fee2e2);
          color: var(--danger-text, #991b1b);
        }

        .feedback-section {
          margin-top: 8px;
        }

        .feedback-section span {
          display: block;
          font-size: 0.85rem;
          color: var(--text-muted, #6b7280);
          margin-bottom: 4px;
        }

        .feedback-section ul {
          margin: 4px 0 0 0;
          padding-left: 20px;
        }

        .feedback-section p {
          margin: 4px 0 0 0;
        }

        .review-actions {
          display: flex;
          gap: 12px;
          padding-top: 16px;
          border-top: 1px solid var(--border, #e5e7eb);
        }

        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.5);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
        }

        .modal-content {
          background: var(--bg, #ffffff);
          padding: 24px;
          border-radius: 8px;
          max-width: 400px;
          width: 90%;
        }

        .modal-content h3 {
          margin: 0 0 16px 0;
        }

        .modal-content textarea {
          width: 100%;
          min-height: 80px;
          padding: 8px;
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 4px;
          margin-bottom: 16px;
          resize: vertical;
        }

        .modal-content label {
          display: block;
          margin-bottom: 16px;
        }

        .modal-content label span {
          display: block;
      margin-bottom: 4px;
      font-size: 0.9rem;
    }

    .modal-content input {
      width: 100%;
      padding: 8px;
      border: 1px solid var(--border, #e5e7eb);
      border-radius: 4px;
    }

    .modal-checkbox {
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
    }

    .modal-checkbox input {
      width: auto;
    }

    .modal-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
    }
      `}</style>
    </main>
  );
}
