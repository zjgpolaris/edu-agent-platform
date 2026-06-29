"use client";

import Link from "next/link";
import { useState, useEffect } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Profile = {
  student_id: string; grade: string | null;
  recent_topics: string[]; weak_topics: string[]; strong_topics: string[];
  character_interests: string[];
  quiz_stats: { attempts?: number; average_score?: number };
  game_stats: { attempts?: number; average_score?: number };
  updated_at: string;
};
type Weakpoint = { knowledge_tag: string; wrong_count: number; last_wrong_at: string; source: string };
type ReviewPlan = {
  weak_topics: string[];
  recent_topics: string[];
  recommended_actions: string[];
  next_questions: string[];
  weakpoints?: Weakpoint[];
  priority_topics?: string[];
};

const MOCK_PROFILE: Profile = {
  student_id: "student_001",
  grade: "初二",
  recent_topics: ["秦统一六国", "汉朝丝绸之路", "唐朝科举制度"],
  weak_topics: ["魏晋南北朝政权更迭", "隋朝灭亡原因", "五代十国"],
  strong_topics: ["先秦诸子百家", "汉武帝改革", "丝绸之路", "贞观之治"],
  character_interests: ["诸葛亮", "武则天", "岳飞"],
  quiz_stats: { attempts: 24, average_score: 0.78 },
  game_stats: { attempts: 11, average_score: 0.84 },
  updated_at: new Date().toISOString(),
};
const MOCK_PLAN: ReviewPlan = {
  weak_topics: ["魏晋南北朝", "隋朝"],
  recent_topics: ["秦统一"],
  recommended_actions: [
    "重点复习魏晋南北朝的政权更迭顺序，建议结合时间轴游戏加深记忆",
    "整理隋朝灭亡的多重原因，与秦朝二世而亡进行横向比较",
    "五代十国可借助地图工具理解各政权地理分布",
    "继续保持先秦和汉代知识点的复习频率",
  ],
  next_questions: [
    "为什么隋朝和秦朝都是短命王朝？它们有哪些共同之处？",
    "魏晋南北朝时期，哪个政权对后世影响最深远？",
    "五代十国结束的标志是什么？",
  ],
};

export default function StudentDashboardPage() {
  const { user } = useAuth();
  const [input, setInput] = useState("");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [plan, setPlan] = useState<ReviewPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeView, setActiveView] = useState<"overview" | "weak" | "strong" | "plan" | "errors">("overview");
  const [weakpoints, setWeakpoints] = useState<Weakpoint[]>([]);

  useEffect(() => {
    if (user?.role === "student" && user.actorId) load(user.actorId, user.token);
  }, [user?.role, user?.actorId, user?.token]);

  async function load(id: string, token: string | undefined) {
    setLoading(true); setError(""); setProfile(null); setPlan(null); setWeakpoints([]);
    try {
      const headers = token ? authHeaders(token) : {};
      const [pRes, rRes, wRes] = await Promise.all([
        fetch(`${API}/api/students/${id}/profile`, { headers }),
        fetch(`${API}/api/students/${id}/review-plan`, { headers }),
        fetch(`${API}/api/student/${id}/weakpoints`, { headers }),
      ]);
      if (!pRes.ok) {
        setProfile(MOCK_PROFILE);
        setPlan(MOCK_PLAN);
        return;
      }
      const pData = await pRes.json();
      const rData = rRes.ok ? await rRes.json() : null;
      const wData = wRes.ok ? await wRes.json() : null;
      setProfile(pData.profile);
      if (rData) setPlan(rData.review_plan);
      if (wData?.weakpoints) setWeakpoints(wData.weakpoints);
    } catch {
      setProfile(MOCK_PROFILE);
      setPlan(MOCK_PLAN);
    } finally { setLoading(false); }
  }

  const quizScore = profile?.quiz_stats?.average_score;
  const gameScore = profile?.game_stats?.average_score;
  const priorityWeakpoints = plan?.weakpoints ?? weakpoints;
  const priorityTopics = plan?.priority_topics ?? priorityWeakpoints.map((point) => point.knowledge_tag);

  const quizPct = quizScore != null ? Math.round(quizScore * 100) : null;
  const gamePct = gameScore != null ? Math.round(gameScore * 100) : null;
  const masteryPct = profile
    ? Math.round((profile.strong_topics.length / Math.max(profile.strong_topics.length + profile.weak_topics.length, 1)) * 100)
    : null;

  return (
    <div className="dv2-shell">
      {/* Background texture */}
      <div className="dv2-bg" aria-hidden />

      {/* Top bar */}
      <div className="dv2-topbar">
<span className="dv2-topbar-title">学情分析中心</span>
        <span className="dv2-topbar-sub">Student Analytics</span>
      </div>

      {/* Search hero */}
      <header className="dv2-hero">
        <div className="dv2-hero-seal" aria-hidden>档</div>
        <div className="dv2-hero-text">
          <p className="dv2-eyebrow">STUDENT DASHBOARD · 学情档案</p>
          <h1 className="dv2-title">查阅学习档案</h1>
          <p className="dv2-subtitle">输入学号，获取学习轨迹、知识掌握分析与个性化复习方案</p>
        </div>
        {user?.role !== "student" && (
          <form
            className="dv2-search"
            onSubmit={(e) => { e.preventDefault(); const id = input.trim(); if (id) load(id, user?.token); }}
          >
            <div className="dv2-search-inner">
              <span className="dv2-search-glyph">学</span>
              <input
                className="dv2-search-field"
                placeholder="输入学生 ID，如 student_001"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                autoFocus
              />
              <button className="dv2-search-submit" type="submit" disabled={loading}>
                {loading ? <span className="dv2-loader" /> : <span>查询 →</span>}
              </button>
            </div>
            {!profile && (
              <button
                type="button"
                className="dv2-demo-btn"
                onClick={() => { setInput("student_001"); setProfile(MOCK_PROFILE); setPlan(MOCK_PLAN); setLoading(false); setError(""); }}
              >
                演示模式 · 加载示例数据
              </button>
            )}
          </form>
        )}
        {error && <p className="dv2-error">{error}</p>}
      </header>

      {/* Dashboard content */}
      {profile && (
        <main className="dv2-content" key={profile.student_id}>

          {/* Identity strip */}
          <div className="dv2-identity">
            <div className="dv2-identity-stamp">
              <span>{profile.student_id.slice(0, 2).toUpperCase()}</span>
            </div>
            <div className="dv2-identity-info">
              <h2 className="dv2-identity-id">{profile.student_id}</h2>
              <p className="dv2-identity-meta">
                {profile.grade && <span className="dv2-grade-pill">{profile.grade}</span>}
                历史学习档案 · 最近更新于今日
              </p>
            </div>
            <div className="dv2-identity-scores">
              {quizPct != null && (
                <div className="dv2-score-orb" data-level={quizPct >= 80 ? "high" : quizPct >= 60 ? "mid" : "low"}>
                  <span className="dv2-score-val">{quizPct}<sup>%</sup></span>
                  <span className="dv2-score-lbl">练习均分</span>
                </div>
              )}
              {gamePct != null && (
                <div className="dv2-score-orb" data-level={gamePct >= 80 ? "high" : gamePct >= 60 ? "mid" : "low"}>
                  <span className="dv2-score-val">{gamePct}<sup>%</sup></span>
                  <span className="dv2-score-lbl">游戏均分</span>
                </div>
              )}
              {masteryPct != null && (
                <div className="dv2-score-orb" data-level={masteryPct >= 70 ? "high" : masteryPct >= 40 ? "mid" : "low"}>
                  <span className="dv2-score-val">{masteryPct}<sup>%</sup></span>
                  <span className="dv2-score-lbl">掌握率</span>
                </div>
              )}
              <div className="dv2-score-orb" data-level="mid">
                <span className="dv2-score-val">{profile.quiz_stats?.attempts ?? 0}</span>
                <span className="dv2-score-lbl">练习次数</span>
              </div>
            </div>
          </div>

          {/* Nav rail */}
          <nav className="dv2-nav">
            {(["overview", "weak", "strong", "plan", "errors"] as const).map((v) => {
              const labels = { overview: "全览", weak: "薄弱点", strong: "已掌握", plan: "复习方案", errors: "错题本" };
              const counts: Record<string, number | null> = {
                overview: null,
                weak: priorityTopics.length || profile.weak_topics.length,
                strong: profile.strong_topics.length,
                plan: plan?.recommended_actions.length ?? 0,
                errors: priorityWeakpoints.length,
              };
              return (
                <button
                  key={v}
                  className={`dv2-nav-btn${activeView === v ? " active" : ""}`}
                  onClick={() => setActiveView(v)}
                >
                  {labels[v]}
                  {counts[v] != null && <span className="dv2-nav-count">{counts[v]}</span>}
                </button>
              );
            })}
          </nav>

          {/* Panels */}
          {activeView === "overview" && (
            <div className="dv2-panel dv2-overview">
              <OverviewColumn title="优先复习" items={priorityTopics.length > 0 ? priorityTopics : profile.weak_topics} variant="weak" empty="暂无记录" />
              <OverviewColumn title="近期学习" items={profile.recent_topics} variant="recent" empty="暂无记录" />
              <OverviewColumn title="感兴趣人物" items={profile.character_interests} variant="interest" empty="暂无记录" />
            </div>
          )}

          {activeView === "weak" && (
            <div className="dv2-panel dv2-weak-panel">
              <div className="dv2-panel-header">
                <span className="dv2-panel-eyebrow">需要加强</span>
                <h3 className="dv2-panel-title">优先复习知识点</h3>
                <p className="dv2-panel-desc">以下知识点综合错题本出错次数和学习画像排序，建议优先复习。</p>
              </div>
              {priorityTopics.length === 0 && profile.weak_topics.length === 0 ? (
                <p className="dv2-empty">暂无薄弱知识点，继续保持！</p>
              ) : (
                <div className="dv2-topic-bricks">
                  {(priorityTopics.length > 0 ? priorityTopics : profile.weak_topics).map((t, i) => {
                    const point = priorityWeakpoints.find((item) => item.knowledge_tag === t);
                    return (
                      <Link
                        key={t}
                        className="dv2-brick dv2-brick-weak"
                        style={{ animationDelay: `${i * 50}ms`, textDecoration: "none" }}
                        href={`/learning-assistant?q=${encodeURIComponent(`帮我复习知识点「${t}」`)}`}
                      >
                        <span className="dv2-brick-rank">{point ? `×${point.wrong_count}` : String(i + 1).padStart(2, "0")}</span>
                        <span className="dv2-brick-text">{t}</span>
                        <span className="dv2-brick-arrow">复习 →</span>
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {activeView === "strong" && (
            <div className="dv2-panel dv2-strong-panel">
              <div className="dv2-panel-header">
                <span className="dv2-panel-eyebrow">掌握良好</span>
                <h3 className="dv2-panel-title">已掌握知识点</h3>
                <p className="dv2-panel-desc">这些知识点表现稳定，继续保持。</p>
              </div>
              {profile.strong_topics.length === 0 ? (
                <p className="dv2-empty">还没有掌握的知识点，加油！</p>
              ) : (
                <div className="dv2-strong-grid">
                  {profile.strong_topics.map((t, i) => (
                    <div key={t} className="dv2-strong-chip" style={{ animationDelay: `${i * 40}ms` }}>
                      <span className="dv2-strong-dot" />
                      {t}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeView === "plan" && (
            <div className="dv2-panel dv2-plan-panel">
              <div className="dv2-panel-header">
                <span className="dv2-panel-eyebrow">AI 生成</span>
                <h3 className="dv2-panel-title">个性化复习方案</h3>
                <p className="dv2-panel-desc">根据你的学习轨迹和薄弱点，AI 为你制定以下复习路径。</p>
              </div>
              {!plan ? (
                <p className="dv2-empty">暂无复习建议，先完成一些练习或对话吧。</p>
              ) : (
                <>
                  <ol className="dv2-actions">
                    {plan.recommended_actions.map((a, i) => (
                      <li key={i} className="dv2-action-row" style={{ animationDelay: `${i * 70}ms` }}>
                        <span className="dv2-action-num">{i + 1}</span>
                        <p className="dv2-action-text">{a}</p>
                      </li>
                    ))}
                  </ol>
                  {priorityWeakpoints.length > 0 && (
                    <div className="dv2-questions">
                      <p className="dv2-questions-label">错题本优先级</p>
                      {priorityWeakpoints.slice(0, 3).map((point, i) => (
                        <div key={point.knowledge_tag} className="dv2-question" style={{ animationDelay: `${(plan.recommended_actions.length + i) * 60}ms` }}>
                          <span className="dv2-q-mark">错</span>
                          <span>{point.knowledge_tag} · 出错 {point.wrong_count} 次</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {plan.next_questions.length > 0 && (
                    <div className="dv2-questions">
                      <p className="dv2-questions-label">推荐追问</p>
                      {plan.next_questions.map((q, i) => (
                        <div key={i} className="dv2-question" style={{ animationDelay: `${(plan.recommended_actions.length + i) * 60}ms` }}>
                          <span className="dv2-q-mark">？</span>
                          <span>{q}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
          {activeView === "errors" && (
            <div className="dv2-panel dv2-weak-panel">
              <div className="dv2-panel-header">
                <span className="dv2-panel-eyebrow">错题追踪</span>
                <h3 className="dv2-panel-title">错题本</h3>
                <p className="dv2-panel-desc">来自作业批改和游戏答题的错误知识点，按出错次数排序。</p>
              </div>
              {priorityWeakpoints.length === 0 ? (
                <p className="dv2-empty">还没有错题记录，完成一次拍照批改或游戏练习后会自动记入。</p>
              ) : (
                <div className="dv2-topic-bricks">
                  {priorityWeakpoints.map((wp, i) => (
                    <a key={wp.knowledge_tag} className="dv2-brick dv2-brick-weak" style={{ animationDelay: `${i * 40}ms`, textDecoration: "none", cursor: "pointer" }}
                      href={`/learning-assistant?q=${encodeURIComponent(`帮我复习知识点「${wp.knowledge_tag}」`)}`}>
                      <span className="dv2-brick-rank">×{wp.wrong_count}</span>
                      <span className="dv2-brick-text">{wp.knowledge_tag}</span>
                      <span className="dv2-brick-arrow" title={wp.source}>复习 →</span>
                    </a>
                  ))}
                </div>
              )}
            </div>
          )}
        </main>
      )}
    </div>
  );
}

function OverviewColumn({ title, items, variant, empty }: { title: string; items: string[]; variant: string; empty: string }) {
  return (
    <div className={`dv2-ov-col dv2-ov-${variant}`}>
      <p className="dv2-ov-label">{title}</p>
      {items.length === 0 ? (
        <p className="dv2-ov-empty">{empty}</p>
      ) : (
        <div className="dv2-ov-tags">
          {items.map((t) => <span key={t} className="dv2-ov-tag">{t}</span>)}
        </div>
      )}
    </div>
  );
}
