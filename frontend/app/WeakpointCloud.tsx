"use client";

import { useEffect, useState } from "react";

type Weakpoint = {
  knowledge_tag: string;
  wrong_count: number;
  source: string;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

function getStudentId() {
  const key = "edu-agent-student-id";
  const existing = localStorage.getItem(key);
  if (existing) return existing;
  const created = `student-${crypto.randomUUID()}`;
  localStorage.setItem(key, created);
  return created;
}

export default function WeakpointCloud() {
  const [weakpoints, setWeakpoints] = useState<Weakpoint[]>([]);

  useEffect(() => {
    const studentId = getStudentId();
    fetch(`${apiBaseUrl}/api/student/${encodeURIComponent(studentId)}/weakpoints`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => setWeakpoints(data?.weakpoints || []))
      .catch(() => setWeakpoints([]));
  }, []);

  if (!weakpoints.length) return null;

  return (
    <section className="weakpoint-cloud-card" aria-label="薄弱知识点">
      <div>
        <span className="card-label">错题本追踪</span>
        <h2>最近容易混淆的知识点</h2>
        <p>系统会把游戏中的错题转成复习标签，点击后进入历史人物对话继续追问。</p>
      </div>
      <div className="weakpoint-tags">
        {weakpoints.slice(0, 8).map((item) => (
          <a key={item.knowledge_tag} href={`/history-character?message=${encodeURIComponent(`请帮我复习${item.knowledge_tag}`)}`}>
            {item.knowledge_tag}<em>×{item.wrong_count}</em>
          </a>
        ))}
      </div>
    </section>
  );
}
