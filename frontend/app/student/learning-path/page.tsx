"use client"

import { useState, useEffect } from "react"
import Link from "next/link"
import { useAuth } from "@/contexts/AuthContext"
import { authHeaders } from "@/lib/auth"

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"

interface Weakpoint {
  knowledge_tag: string
  wrong_count: number
  last_wrong_at: string
  source: string
}

interface LearningPath {
  student_id: string
  created_at: string
  updated_at: string
  weak_topics: string[]
  strong_topics: string[]
  weakpoints?: Weakpoint[]
  priority_topics?: string[]
  recommended_actions: string[]
  progress: Record<string, number>
  milestones: Array<{ title: string; completed: boolean }>
}

const SOURCE_LABEL: Record<string, string> = {
  homework_grading: "作业批改",
  game: "游戏答题",
  timeline_game: "时间轴游戏",
  card_game: "卡牌游戏",
  multiplayer_game: "多人游戏",
  textbook_guide: "教材问答",
  quiz: "测验练习",
}

export default function LearningPathPage() {
  const { user } = useAuth()
  const [path, setPath] = useState<LearningPath | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!user?.actorId) return
    let cancelled = false

    async function fetchLearningPath() {
      setLoading(true)
      setError(null)
      try {
        const res = await fetch(`${apiBaseUrl}/api/students/${user!.actorId}/learning-path`, {
          headers: authHeaders(user!.token),
        })
        const data = await res.json()
        if (!cancelled) setPath(data)
      } catch (err) {
        if (!cancelled) setError("Failed to fetch learning path")
        console.error(err)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchLearningPath()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.actorId, user?.token])

  const completeMilestone = (index: number) => {
    if (!path) return
    const newMilestones = [...path.milestones]
    newMilestones[index].completed = true
    setPath({ ...path, milestones: newMilestones })
  }

  return (
    <div className="learning-path-page">
      <h1>学习路径</h1>
      {loading && <p className="loading">加载中...</p>}
      {error && <p className="error">{error}</p>}
      {path && (
        <div className="path-container">
          <div className="overview">
            <h2>学习概览</h2>
            <p>更新时间：{new Date(path.updated_at).toLocaleString()}</p>
          </div>

          <div className="weakness-section">
            <h2>薄弱知识点</h2>
            {path.weakpoints && path.weakpoints.length > 0 ? (
              <div className="topic-list">
                {path.weakpoints.map((point) => {
                  const progress = path.progress[point.knowledge_tag] ?? 0.5
                  const sourceLabel = SOURCE_LABEL[point.source] ?? point.source
                  return (
                    <div key={point.knowledge_tag} className="topic-item">
                      <span className="topic-name">{point.knowledge_tag}</span>
                      <span>{sourceLabel} · 出错 {point.wrong_count} 次</span>
                      <span className="topic-progress">{(progress * 100).toFixed(0)}%</span>
                      <Link
                        href={`/learning-assistant?q=${encodeURIComponent(`帮我复习知识点「${point.knowledge_tag}」，先简要解释，再出一道练习题考考我`)}`}
                      >
                        去复习
                      </Link>
                    </div>
                  )
                })}
              </div>
            ) : path.weak_topics.length > 0 ? (
              <div className="topic-list">
                {path.weak_topics.map((topic, i) => (
                  <div key={i} className="topic-item">
                    <span className="topic-name">{topic}</span>
                    <span className="topic-progress">{((path.progress[topic] ?? 0.5) * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty">暂无薄弱知识点</p>
            )}
          </div>

          <div className="strength-section">
            <h2>优势知识点</h2>
            {path.strong_topics.length > 0 ? (
              <div className="topic-list">
                {path.strong_topics.map((topic, i) => (
                  <div key={i} className="topic-item strong">
                    <span className="topic-name">{topic}</span>
                    <span className="topic-progress">掌握</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty">暂无优势知识点</p>
            )}
          </div>

          <div className="recommendations-section">
            <h2>学习建议</h2>
            <ul>
              {path.recommended_actions.map((action, i) => (
                <li key={i}>
                  <input
                    type="checkbox"
                    id={`action-${i}`}
                    checked={path.milestones[i]?.completed || false}
                    onChange={() => completeMilestone(i)}
                  />
                  <label htmlFor={`action-${i}`}>{action}</label>
                </li>
              ))}
            </ul>
          </div>

          <div className="milestones-section">
            <h2>学习里程碑</h2>
            <div className="milestone-list">
              {path.milestones.map((m, i) => (
                <div key={i} className={`milestone ${m.completed ? "completed" : ""}`}>
                  <div className="milestone-marker">{i + 1}</div>
                  <span>{m.title}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
