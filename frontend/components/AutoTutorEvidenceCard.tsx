export type AutoTutorEvidence = {
  session_id: string;
  student_id: string;
  status: string;
  knowledge_points: string[];
  replans: number;
  reflection_count: number;
  exit_ticket: { recorded: boolean; knowledge_point: string; passed: boolean | null };
  mastery: { status: "verified" | "not_yet_verified" };
  evidence: {
    learning_event_recorded: boolean;
    weakpoint_action: string;
    tutor_effectiveness_ready: boolean;
  };
};

function yesNo(value: boolean): string {
  return value ? "是" : "否";
}

export function AutoTutorEvidenceCard({ data }: { data: AutoTutorEvidence }) {
  const completed = data.status === "completed";
  return (
    <section className="panel" aria-label="AutoTutor 会话证据" style={{ padding: 20 }}>
      <div className="panel-kicker">Session Evidence</div>
      <h2 style={{ marginBottom: 6 }}>AutoTutor 会话证据</h2>
      <p style={{ color: "var(--muted)", marginTop: 0 }}>
        学生 {data.student_id} · 会话 {data.session_id}
      </p>
      {!completed ? <p role="status">该课程尚未完成，以下仅展示当前已产生的证据。</p> : null}
      <div className="eval-ops-grid" style={{ marginTop: 16 }}>
        <div className="eval-ops-card"><span>学习目标</span><strong>{data.knowledge_points.join("、") || "暂无"}</strong><small>本次会话</small></div>
        <div className="eval-ops-card"><span>反思 / 重规划</span><strong>{data.reflection_count} / {data.replans}</strong><small>Agent 策略调整</small></div>
        <div className="eval-ops-card"><span>退出票</span><strong>{data.exit_ticket.passed == null ? "未完成" : data.exit_ticket.passed ? "通过" : "未通过"}</strong><small>{data.exit_ticket.knowledge_point || "独立检验"}</small></div>
        <div className="eval-ops-card"><span>验证掌握</span><strong>{data.mastery.status === "verified" ? "已验证" : "尚未验证"}</strong><small>不以练习题代替退出票</small></div>
      </div>
      <div className="learning-runtime-chips" style={{ marginTop: 16 }}>
        <small>学习事件记录：{yesNo(data.evidence.learning_event_recorded)}</small>
        <small>教师效果聚合：{data.evidence.tutor_effectiveness_ready ? "已就绪" : "等待同步"}</small>
        <small>薄弱点动作：{data.evidence.weakpoint_action || "无"}</small>
      </div>
    </section>
  );
}
