"use client";

import { FormEvent, useState, useEffect, useRef } from "react";
import { useAuth } from "@/contexts/AuthContext";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type EssayGradeRequest = {
  essay: string;
  student_id: string;
};

type EssayGradeResponse = {
  student_id: string;
  comments: string;
  needs_human_review: boolean;
  review_reason?: string;
  session_id?: string;
};

type ReviewState = {
  approved: boolean | null;
  teacherComments: string;
  submitted: boolean;
};

export default function EssayGradePage() {
  const { user } = useAuth();
  const studentId = user?.actorId ?? "";
  const [essay, setEssay] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<EssayGradeResponse | null>(null);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [review, setReview] = useState<ReviewState>({
    approved: null,
    teacherComments: "",
    submitted: false,
  });
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (result && resultRef.current) {
      resultRef.current.classList.add("visible");
    }
  }, [result]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!essay.trim()) {
      setError("请输入作文内容");
      return;
    }
    if (!studentId.trim()) {
      setError("请输入学生 ID");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);
    setSubmitted(true);
    setReview({ approved: null, teacherComments: "", submitted: false });

    try {
      const response = await fetch(`${apiBaseUrl}/api/chinese/essay/grade`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ essay, student_id: studentId }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = (await response.json()) as EssayGradeResponse;
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "批改失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  }

  async function submitReview(approved: boolean) {
    if (!result?.session_id) {
      setError("缺少会话 ID，无法提交复核");
      return;
    }
    try {
      const response = await fetch(`${apiBaseUrl}/api/chinese/essay/review-result`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: result.session_id,
          approved,
          teacher_comments: review.teacherComments,
        }),
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      setReview({ ...review, approved, submitted: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交复核失败");
    }
  }

  const charCount = essay.length;
  const maxChars = 2000;

  return (
    <div className="essay-shell">
      {/* 背景装饰 */}
      <div className="essay-bg-pattern" />
      <div className="essay-bg-ink" />

      {/* 顶部标题区 */}
      <header className="essay-header">
        <div className="essay-header-deco">
          <span className="deco-line" />
          <span className="deco-circle" />
        </div>
        <div className="essay-title-group">
          <h1 className="essay-title">作文批改</h1>
          <p className="essay-subtitle">AI 辅助批改 · 智能评分 · 精准点评</p>
        </div>
        <div className="essay-header-deco essay-header-deco-right">
          <span className="deco-circle" />
          <span className="deco-line" />
        </div>
      </header>

      {/* 主内容区 */}
      <main className="essay-main">
        <div className="essay-paper">
          {/* 纸张顶部装饰 */}
          <div className="paper-stripe" />
          <div className="paper-corner paper-corner-tl" />
          <div className="paper-corner paper-corner-tr" />

          <form onSubmit={handleSubmit} className="essay-form">
            {/* 作文输入区 */}
            <div className="form-row form-row-essay">
              <div className="essay-input-header">
                <label className="form-label">
                  <span className="label-icon">✍️</span>
                  作文内容
                </label>
                <span className="char-counter">
                  {charCount}/{maxChars}
                </span>
              </div>
              <div className="essay-textarea-wrapper">
                <textarea
                  value={essay}
                  onChange={(e) => {
                    if (e.target.value.length <= maxChars) {
                      setEssay(e.target.value);
                    }
                  }}
                  placeholder="请在此处输入作文内容..."
                  rows={12}
                  className="essay-textarea"
                  disabled={loading}
                />
                {/* 米字格背景 */}
                <div className="grid-background" aria-hidden="true">
                  {[...Array(12)].map((_, i) => (
                    <div key={i} className="grid-line" />
                  ))}
                </div>
              </div>
            </div>

            {/* 提交按钮 */}
            <button
              type="submit"
              className={`submit-btn ${loading ? "loading" : ""}`}
              disabled={loading || !essay.trim()}
            >
              {loading ? (
                <>
                  <span className="btn-spinner" />
                  批改中...
                </>
              ) : (
                <>
                  <span className="btn-icon">🖋️</span>
                  开始批改
                </>
              )}
            </button>
          </form>

          {/* 错误提示 */}
          {error && (
            <div className="error-banner">
              <span className="error-icon">⚠️</span>
              <span>{error}</span>
            </div>
          )}

          {/* 批改结果 */}
          {result && (
            <div className="result-scroll" ref={resultRef}>
              <div className="result-paper">
                {/* 结果纸张装饰 */}
                <div className="result-stripe" />
                <div className="result-corner result-corner-tl" />
                <div className="result-corner result-corner-tr" />
                <div className="result-corner result-corner-bl" />
                <div className="result-corner result-corner-br" />

                {/* 印章 */}
                <div className="result-seal">
                  <div className="seal-inner">
                    <span className="seal-text">批改</span>
                    <span className="seal-sub">完成</span>
                  </div>
                </div>

                {/* 结果内容 */}
                <div className="result-content">
                  <div className="result-header">
                    <h2>批改评语</h2>
                    {result.needs_human_review && (
                      <div className="review-badge">
                        <span className="badge-icon">👁️</span>
                        <span>建议教师复核</span>
                      </div>
                    )}
                  </div>

                  {result.needs_human_review && result.review_reason && (
                    <div className="review-reason">
                      <span className="reason-label">复核原因：</span>
                      <span>{result.review_reason}</span>
                    </div>
                  )}

                  {result.needs_human_review && !review.submitted && (
                    <div className="review-actions">
                      <div className="review-teacher-comment">
                        <label className="review-label">教师评语（可选）：</label>
                        <textarea
                          value={review.teacherComments}
                          onChange={(e) => setReview({ ...review, teacherComments: e.target.value })}
                          placeholder="请输入您的补充评语..."
                          rows={2}
                          className="review-textarea"
                        />
                      </div>
                      <div className="review-buttons">
                        <button
                          type="button"
                          onClick={() => submitReview(true)}
                          className="review-btn review-btn-approve"
                        >
                          确认通过
                        </button>
                        <button
                          type="button"
                          onClick={() => submitReview(false)}
                          className="review-btn review-btn-reject"
                        >
                          需修改
                        </button>
                      </div>
                    </div>
                  )}

                  {result.needs_human_review && review.submitted && (
                    <div className="review-submitted">
                      <span className="review-submitted-icon">✓</span>
                      <span>复核结果已提交</span>
                    </div>
                  )}

                  <div className="result-comments">
                    {result.comments.split("\n").filter(Boolean).map((line, i) => (
                      <p key={i}>{line}</p>
                    ))}
                  </div>
                </div>

                {/* 底部装饰 */}
                <div className="result-footer">
                  <span className="footer-seal">AI批改助手</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* 底部装饰 */}
      <footer className="essay-footer">
        <div className="footer-pattern" />
        <p>智慧教育 · 精准批改</p>
      </footer>

      <style jsx>{`
        .essay-shell {
          min-height: 100vh;
          min-height: 100dvh;
          padding: 32px 20px 48px;
          position: relative;
          overflow-x: hidden;
          font-family: "Kaiti", "STKaiti", "KaiTi", "楷体", "SimSun", serif;
          contain: layout style;
        }

        /* 背景图案 */
        .essay-bg-pattern {
          position: fixed;
          inset: 0;
          background:
            radial-gradient(circle at 8% 12%, rgba(183, 66, 43, 0.08), transparent 30rem),
            radial-gradient(circle at 92% 18%, rgba(15, 107, 95, 0.08), transparent 28rem),
            linear-gradient(90deg, rgba(96, 72, 44, 0.03) 1px, transparent 1px),
            linear-gradient(0deg, rgba(96, 72, 44, 0.03) 1px, transparent 1px),
            linear-gradient(135deg, #f8f0e0 0%, #ede4d0 100%);
          background-size: auto, auto, 32px 32px, 32px 32px, auto;
          z-index: -2;
          pointer-events: none;
        }

        .essay-bg-ink {
          position: fixed;
          inset: 0;
          opacity: 0.15;
          background-image:
            radial-gradient(circle, rgba(60, 42, 23, 0.15) 1px, transparent 1px),
            linear-gradient(135deg, rgba(255, 255, 255, 0.3), transparent 40%);
          background-size: 16px 16px, auto;
          mix-blend-mode: multiply;
          z-index: -1;
        }

        /* 顶部标题 */
        .essay-header {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 32px;
          margin-bottom: 32px;
          position: relative;
        }

        .essay-header-deco {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .essay-header-deco-right {
          flex-direction: row-reverse;
        }

        .deco-line {
          width: 48px;
          height: 2px;
          background: linear-gradient(90deg, transparent, rgba(183, 66, 43, 0.4), transparent);
        }

        .deco-circle {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: rgba(183, 66, 43, 0.5);
        }

        .essay-title-group {
          text-align: center;
        }

        .essay-title {
          font-size: clamp(28px, 5vw, 42px);
          font-weight: 700;
          margin: 0 0 8px;
          color: #2a1a0e;
          letter-spacing: 8px;
          text-shadow: 0 2px 4px rgba(42, 26, 14, 0.1);
        }

        .essay-subtitle {
          font-size: 14px;
          color: #6b5a4a;
          margin: 0;
          letter-spacing: 4px;
        }

        /* 主内容 */
        .essay-main {
          max-width: 720px;
          margin: 0 auto;
        }

        .essay-paper {
          position: relative;
          background:
            linear-gradient(180deg, rgba(255, 252, 244, 0.98), rgba(247, 238, 217, 0.94)),
            radial-gradient(circle at 92% 8%, rgba(184, 139, 62, 0.12), transparent 12rem);
          border: 1px solid rgba(140, 100, 50, 0.25);
          border-radius: 4px;
          padding: 36px 40px 40px;
          box-shadow:
            0 8px 32px rgba(58, 43, 26, 0.12),
            inset 0 0 0 1px rgba(255, 255, 255, 0.5);
        }

        .paper-stripe {
          position: absolute;
          top: 0;
          left: 50%;
          transform: translateX(-50%);
          width: 60%;
          height: 4px;
          background: linear-gradient(90deg, transparent, rgba(183, 66, 43, 0.3), transparent);
          border-radius: 0 0 2px 2px;
        }

        .paper-corner {
          position: absolute;
          width: 24px;
          height: 24px;
          border: 2px solid rgba(140, 100, 50, 0.2);
        }

        .paper-corner-tl {
          top: 8px;
          left: 8px;
          border-right: none;
          border-bottom: none;
        }

        .paper-corner-tr {
          top: 8px;
          right: 8px;
          border-left: none;
          border-bottom: none;
        }

        /* 表单 */
        .essay-form {
          display: grid;
          gap: 24px;
        }

        .form-row {
          display: grid;
          gap: 10px;
        }

        .form-row-essay {
          gap: 12px;
        }

        .form-label {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 15px;
          font-weight: 600;
          color: #3a2a1a;
        }

        .label-icon {
          font-size: 18px;
        }

        .form-input {
          width: 100%;
          padding: 12px 16px;
          border: 1px solid rgba(140, 100, 50, 0.25);
          border-radius: 4px;
          background: rgba(255, 252, 244, 0.8);
          font-size: 15px;
          font-family: inherit;
          color: #2a1a0e;
          outline: none;
          transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
        }

        .form-input:focus {
          border-color: rgba(183, 66, 43, 0.5);
          background: #fff;
          box-shadow: 0 0 0 3px rgba(183, 66, 43, 0.1);
        }

        .form-input:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .essay-input-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .char-counter {
          font-size: 12px;
          color: #8b7a6a;
          font-weight: 500;
        }

        .essay-textarea-wrapper {
          position: relative;
        }

        .essay-textarea {
          width: 100%;
          padding: 16px;
          border: 1px solid rgba(140, 100, 50, 0.25);
          border-radius: 4px;
          background: rgba(255, 252, 244, 0.9);
          font-size: 16px;
          font-family: inherit;
          line-height: 1.8;
          color: #2a1a0e;
          outline: none;
          resize: vertical;
          min-height: 240px;
          transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
        }

        .essay-textarea:focus {
          border-color: rgba(183, 66, 43, 0.5);
          background: #fff;
          box-shadow: 0 0 0 3px rgba(183, 66, 43, 0.1);
        }

        .essay-textarea:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .grid-background {
          position: absolute;
          inset: 0;
          pointer-events: none;
          opacity: 0.4;
          background-image:
            linear-gradient(0deg, rgba(140, 100, 50, 0.15) 1px, transparent 1px),
            linear-gradient(90deg, rgba(140, 100, 50, 0.08) 1px, transparent 1px);
          background-size: 100% 24px, 100% 100%;
          border-radius: 4px;
        }

        .grid-line {
          height: 1px;
          background: rgba(140, 100, 50, 0.1);
          margin-top: 24px;
        }

        /* 提交按钮 */
        .submit-btn {
          width: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          padding: 14px 24px;
          border: none;
          border-radius: 4px;
          background: linear-gradient(135deg, #b7422b, #8d2d1c);
          color: #fff8ed;
          font-size: 16px;
          font-weight: 600;
          font-family: inherit;
          cursor: pointer;
          transition: transform 0.2s, box-shadow 0.2s, filter 0.2s;
          box-shadow: 0 4px 16px rgba(183, 66, 43, 0.3);
        }

        .submit-btn:hover:not(:disabled) {
          transform: translateY(-2px);
          box-shadow: 0 6px 24px rgba(183, 66, 43, 0.4);
          filter: brightness(1.05);
        }

        .submit-btn:active:not(:disabled) {
          transform: translateY(0);
        }

        .submit-btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .btn-icon {
          font-size: 18px;
        }

        .btn-spinner {
          width: 18px;
          height: 18px;
          border: 2px solid rgba(255, 248, 237, 0.3);
          border-top-color: #fff8ed;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
          to { transform: rotate(360deg); }
        }

        /* 错误提示 */
        .error-banner {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-top: 16px;
          padding: 12px 16px;
          background: rgba(255, 238, 232, 0.9);
          border: 1px solid rgba(183, 66, 43, 0.3);
          border-left: 4px solid #b7422b;
          border-radius: 4px;
          color: #8d2d1c;
          font-size: 14px;
          animation: slideDown 0.3s ease;
        }

        .error-icon {
          font-size: 18px;
        }

        @keyframes slideDown {
          from {
            opacity: 0;
            transform: translateY(-8px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        /* 结果区域 */
        .result-scroll {
          margin-top: 32px;
          opacity: 0;
          transform: translateY(16px);
        }

        .result-scroll.visible {
          animation: fadeIn 0.5s ease forwards;
        }

        @keyframes fadeIn {
          from {
            opacity: 0;
            transform: translateY(16px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .result-paper {
          position: relative;
          background:
            linear-gradient(180deg, rgba(255, 252, 244, 0.96), rgba(242, 225, 190, 0.88)),
            radial-gradient(circle at 8% 92%, rgba(15, 107, 95, 0.1), transparent 10rem);
          border: 1px solid rgba(140, 100, 50, 0.25);
          border-radius: 4px;
          padding: 36px 40px 40px;
          box-shadow:
            0 8px 32px rgba(58, 43, 26, 0.12),
            inset 0 0 0 1px rgba(255, 255, 255, 0.5);
        }

        .result-stripe {
          position: absolute;
          top: 0;
          left: 50%;
          transform: translateX(-50%);
          width: 60%;
          height: 4px;
          background: linear-gradient(90deg, transparent, rgba(15, 107, 95, 0.3), transparent);
          border-radius: 0 0 2px 2px;
        }

        .result-corner {
          position: absolute;
          width: 24px;
          height: 24px;
          border: 2px solid rgba(140, 100, 50, 0.2);
        }

        .result-corner-tl {
          top: 8px;
          left: 8px;
          border-right: none;
          border-bottom: none;
        }

        .result-corner-tr {
          top: 8px;
          right: 8px;
          border-left: none;
          border-bottom: none;
        }

        .result-corner-bl {
          bottom: 8px;
          left: 8px;
          border-right: none;
          border-top: none;
        }

        .result-corner-br {
          bottom: 8px;
          right: 8px;
          border-left: none;
          border-top: none;
        }

        /* 印章 */
        .result-seal {
          position: absolute;
          top: 20px;
          right: 20px;
          width: 64px;
          height: 64px;
          border: 3px solid #b7422b;
          border-radius: 8px;
          transform: rotate(-8deg);
          background: rgba(183, 66, 43, 0.05);
          display: grid;
          place-items: center;
          box-shadow: 0 4px 12px rgba(183, 66, 43, 0.2);
        }

        .seal-inner {
          display: grid;
          gap: 2px;
          text-align: center;
        }

        .seal-text {
          font-size: 22px;
          font-weight: 700;
          color: #b7422b;
          letter-spacing: 4px;
        }

        .seal-sub {
          font-size: 12px;
          color: #b7422b;
          letter-spacing: 2px;
        }

        /* 结果内容 */
        .result-content {
          position: relative;
          z-index: 1;
        }

        .result-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          margin-bottom: 20px;
          padding-bottom: 16px;
          border-bottom: 1px dashed rgba(140, 100, 50, 0.2);
        }

        .result-header h2 {
          margin: 0;
          font-size: 24px;
          color: #2a1a0e;
          letter-spacing: 4px;
        }

        .review-badge {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          background: rgba(255, 238, 232, 0.8);
          border: 1px solid rgba(183, 66, 43, 0.3);
          border-radius: 999px;
          color: #8d2d1c;
          font-size: 13px;
          font-weight: 600;
        }

        .badge-icon {
          font-size: 14px;
        }

        .review-reason {
          display: flex;
          align-items: baseline;
          gap: 8px;
          padding: 12px 16px;
          margin-bottom: 16px;
          background: rgba(255, 248, 235, 0.8);
          border: 1px solid rgba(184, 139, 62, 0.25);
          border-radius: 4px;
          font-size: 14px;
          line-height: 1.6;
        }

        .reason-label {
          color: #7a5524;
          font-weight: 600;
          white-space: nowrap;
        }

        .result-comments {
          color: #3a2a1a;
          line-height: 2;
          font-size: 15px;
        }

        .result-comments p {
          margin: 0 0 8px;
          text-indent: 2em;
        }

        .result-comments p:last-child {
          margin-bottom: 0;
        }

        /* 复核操作区 */
        .review-actions {
          margin-bottom: 20px;
          padding: 16px;
          background: rgba(255, 248, 235, 0.6);
          border: 1px solid rgba(184, 139, 62, 0.2);
          border-radius: 4px;
        }

        .review-teacher-comment {
          margin-bottom: 12px;
        }

        .review-label {
          display: block;
          font-size: 13px;
          color: #7a5524;
          font-weight: 600;
          margin-bottom: 6px;
        }

        .review-textarea {
          width: 100%;
          padding: 10px 12px;
          border: 1px solid rgba(140, 100, 50, 0.25);
          border-radius: 4px;
          background: rgba(255, 252, 244, 0.9);
          font-size: 14px;
          font-family: inherit;
          line-height: 1.5;
          color: #2a1a0e;
          outline: none;
          resize: vertical;
          min-height: 60px;
        }

        .review-textarea:focus {
          border-color: rgba(183, 66, 43, 0.4);
          background: #fff;
        }

        .review-buttons {
          display: flex;
          gap: 10px;
        }

        .review-btn {
          flex: 1;
          padding: 10px 16px;
          border: none;
          border-radius: 4px;
          font-size: 14px;
          font-weight: 600;
          font-family: inherit;
          cursor: pointer;
          transition: transform 0.2s, box-shadow 0.2s;
        }

        .review-btn-approve {
          background: linear-gradient(135deg, #0f6b5f, #0a5046);
          color: #fff8ed;
          box-shadow: 0 2px 8px rgba(15, 107, 95, 0.3);
        }

        .review-btn-approve:hover {
          transform: translateY(-1px);
          box-shadow: 0 4px 12px rgba(15, 107, 95, 0.4);
        }

        .review-btn-reject {
          background: linear-gradient(135deg, #b7422b, #8d2d1c);
          color: #fff8ed;
          box-shadow: 0 2px 8px rgba(183, 66, 43, 0.3);
        }

        .review-btn-reject:hover {
          transform: translateY(-1px);
          box-shadow: 0 4px 12px rgba(183, 66, 43, 0.4);
        }

        .review-submitted {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 16px;
          margin-bottom: 16px;
          background: rgba(15, 107, 95, 0.1);
          border: 1px solid rgba(15, 107, 95, 0.3);
          border-radius: 4px;
          color: #0a5046;
          font-size: 14px;
          font-weight: 600;
        }

        .review-submitted-icon {
          font-size: 16px;
        }

        /* 结果底部 */
        .result-footer {
          margin-top: 24px;
          padding-top: 16px;
          border-top: 1px dashed rgba(140, 100, 50, 0.2);
          text-align: center;
        }

        .footer-seal {
          display: inline-block;
          padding: 4px 12px;
          border: 1px solid rgba(140, 100, 50, 0.2);
          border-radius: 999px;
          font-size: 12px;
          color: #6b5a4a;
          letter-spacing: 2px;
        }

        /* 底部 */
        .essay-footer {
          margin-top: 40px;
          text-align: center;
          position: relative;
        }

        .footer-pattern {
          position: absolute;
          top: -20px;
          left: 50%;
          transform: translateX(-50%);
          width: 200px;
          height: 2px;
          background: linear-gradient(90deg, transparent, rgba(140, 100, 50, 0.3), transparent);
        }

        .essay-footer p {
          margin: 0;
          font-size: 13px;
          color: #6b5a4a;
          letter-spacing: 4px;
        }

        /* 响应式 */
        @media (max-width: 640px) {
          .essay-shell {
            padding: 20px 16px 32px;
          }

          .essay-header {
            flex-direction: column;
            gap: 16px;
          }

          .essay-header-deco,
          .essay-header-deco-right {
            flex-direction: row;
          }

          .essay-paper,
          .result-paper {
            padding: 24px 20px 28px;
          }

          .essay-title {
            letter-spacing: 4px;
          }

          .essay-subtitle {
            letter-spacing: 2px;
          }

          .result-seal {
            width: 52px;
            height: 52px;
            top: 16px;
            right: 16px;
          }

          .seal-text {
            font-size: 18px;
          }

          .seal-sub {
            font-size: 10px;
          }

          .result-header {
            flex-direction: column;
            align-items: flex-start;
            gap: 12px;
          }
        }
      `}</style>
    </div>
  );
}
