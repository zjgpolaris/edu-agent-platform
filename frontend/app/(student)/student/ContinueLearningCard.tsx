"use client";
import Link from "next/link";
import type { TodayPlan } from "./useStudentWorkbenchData";

type ContinueCopy = {
  tone: "urgent" | "assignment" | "review" | "weakpoint" | "clear" | "quiet";
  mark: string;
  eyebrow: string;
  title: string;
  description: string;
  reason: string;
  primaryHref: string;
  primaryLabel: string;
  secondaryHref?: string;
  secondaryLabel?: string;
  meta?: string;
};

type SummaryChip = { label: string; value: string; tone: "danger" | "gold" | "jade" | "muted" };

function buildSummaryChips(plan: TodayPlan | null): SummaryChip[] {
  const summary = plan?.summary;
  if (!summary) return [];
  const chips: SummaryChip[] = [];
  if (summary.pending_assignments > 0) {
    chips.push({
      label: summary.overdue_assignments > 0 ? "待交/逾期" : "待交作业",
      value: summary.overdue_assignments > 0 ? `${summary.pending_assignments} / ${summary.overdue_assignments}` : `${summary.pending_assignments}`,
      tone: summary.overdue_assignments > 0 ? "danger" : "gold",
    });
  }
  if (summary.review_total > 0 || summary.review_remaining > 0) {
    chips.push({ label: "今日复习", value: `${summary.review_remaining}/${summary.review_total || summary.review_remaining}`, tone: "jade" });
  }
  if (summary.weakpoint_count > 0) {
    chips.push({ label: "薄弱点", value: `${summary.weakpoint_count}`, tone: "gold" });
  }
  if (!chips.length && summary.all_clear) {
    chips.push({ label: "今日状态", value: "已清空", tone: "jade" });
  }
  return chips.slice(0, 3);
}

function buildContinueCopy(plan: TodayPlan | null): ContinueCopy {
  const task = plan?.tasks?.[0];
  if (!task) {
    return {
      tone: "clear",
      mark: "闲",
      eyebrow: "CONTINUE · 今日无硬性待办",
      title: "今天任务已清空",
      description: "作业、复习和错题任务都已清理。可以继续读一课教材，或找历史人物聊聊拓展知识。",
      reason: "系统没有发现必须立即处理的作业、复习或薄弱点任务，适合做拓展学习。",
      primaryHref: "/student/materials?tab=textbook",
      primaryLabel: "读教材",
      secondaryHref: "/student/history/chat",
      secondaryLabel: "历史人物对话",
      meta: plan?.date,
    };
  }

  if (task.kind === "assignment") {
    const urgent = task.priority === "urgent";
    return {
      tone: urgent ? "urgent" : "assignment",
      mark: urgent ? "急" : "业",
      eyebrow: urgent ? "URGENT · 先处理逾期" : "NEXT · 作业优先",
      title: urgent ? "先补交逾期作业" : "继续完成作业",
      description: `${task.title}：${task.detail}。提交后系统会根据错题安排后续复习。`,
      reason: urgent ? "这项作业已经逾期，先补交才能让错题回流到后续复习。" : "这项作业优先级最高，完成后系统会根据答题结果更新今日计划。",
      primaryHref: task.href,
      primaryLabel: "继续作业",
      secondaryHref: "/student/review",
      secondaryLabel: "查看复习",
      meta: task.priority === "high" ? "今天截止" : task.priority === "urgent" ? "已逾期" : "待完成",
    };
  }

  if (task.kind === "review") {
    return {
      tone: "review",
      mark: "复",
      eyebrow: "REVIEW · 间隔复习",
      title: "继续今日复习",
      description: `${task.detail}。完成后，系统会更新你的掌握度和下次复习时间。`,
      reason: "间隔复习窗口已经到了，现在完成最能巩固最近的错题记忆。",
      primaryHref: task.href,
      primaryLabel: "开始复习",
      secondaryHref: "/student/review?tab=weakpoints",
      secondaryLabel: "查看错题库",
      meta: task.count ? `${task.count} 个待复习` : undefined,
    };
  }

  return {
    tone: "weakpoint",
    mark: "弱",
    eyebrow: "FOCUS · 薄弱点攻克",
    title: "攻克薄弱点",
    description: `${task.title}。建议先进入 AutoTutor 精讲，再做变式题巩固。`,
    reason: "这是错题本当前最需要攻克的知识点；点击进入 AutoTutor 后才会开始针对性规划。",
    primaryHref: task.href,
    primaryLabel: "进入精讲",
    secondaryHref: "/student/review?tab=weakpoints",
    secondaryLabel: "查看错题库",
    meta: task.ref_id || "错题本推荐",
  };
}

type ContinueLearningCardProps = {
  plan: TodayPlan | null;
  loading: boolean;
  failed?: boolean;
};

/** 学生首页「继续学习」主卡：把今日计划中最高优先级任务转成一个明确下一步。 */
export default function ContinueLearningCard({ plan, loading, failed = false }: ContinueLearningCardProps) {
  if (loading) return (
    <section className="cl-card cl-loading" aria-label="继续学习加载中" aria-busy="true">
      <style>{CSS}</style>
      <div className="cl-orbit" aria-hidden="true" />
      <div className="cl-skel-kicker" />
      <div className="cl-skel-title" />
      <div className="cl-skel-line" />
      <div className="cl-skel-actions"><span /><span /></div>
    </section>
  );

  if (failed) return (
    <section className="cl-card quiet" aria-label="继续学习加载失败">
      <style>{CSS}</style>
      <span className="cl-mark" aria-hidden="true">候</span>
      <p className="cl-eyebrow">CONTINUE · 暂不可用</p>
      <h2 className="cl-title">暂时无法生成下一步建议</h2>
      <p className="cl-desc">今日计划加载失败，但学习记录仍会正常保存。你可以先进入复习中心或教材目录继续学习。</p>
      <p className="cl-reason"><strong>推荐理由：</strong>先选择确定入口继续学习，稍后刷新即可恢复个性化建议。</p>
      <div className="cl-actions">
        <Link href="/student/review" className="cl-primary">去复习中心</Link>
        <Link href="/student/materials?tab=textbook" className="cl-secondary">读教材</Link>
      </div>
    </section>
  );

  const copy = buildContinueCopy(plan);
  const chips = buildSummaryChips(plan);
  return (
    <section className={`cl-card ${copy.tone}`} aria-label="继续学习建议">
      <style>{CSS}</style>
      <span className="cl-mark" aria-hidden="true">{copy.mark}</span>
      <div className="cl-copy">
        <p className="cl-eyebrow">{copy.eyebrow}</p>
        <h2 className="cl-title">{copy.title}</h2>
        <p className="cl-desc">{copy.description}</p>
        <p className="cl-reason"><strong>推荐理由：</strong>{copy.reason}</p>
        {chips.length > 0 && (
          <div className="cl-chips" aria-label="今日计划摘要">
            {chips.map((chip) => (
              <span key={chip.label} className={`cl-chip ${chip.tone}`}>
                <small>{chip.label}</small><b>{chip.value}</b>
              </span>
            ))}
          </div>
        )}
        <div className="cl-actions">
          <Link href={copy.primaryHref} className="cl-primary">{copy.primaryLabel}<span aria-hidden="true"> →</span></Link>
          {copy.secondaryHref && copy.secondaryLabel && (
            <Link href={copy.secondaryHref} className="cl-secondary">{copy.secondaryLabel}</Link>
          )}
        </div>
      </div>
      {copy.meta && <span className="cl-meta">{copy.meta}</span>}
    </section>
  );
}

const CSS = `
.cl-card { position:relative; overflow:hidden; border:1px solid rgba(96,72,44,.18); border-radius:24px; padding:24px 26px; margin:0 0 24px; background:radial-gradient(circle at 88% 16%, rgba(183,66,43,.12), transparent 180px), linear-gradient(145deg, rgba(255,252,244,.96), rgba(246,238,219,.84)); box-shadow:var(--shadow-md); isolation:isolate; }
.cl-card::before { content:""; position:absolute; inset:10px; border:1px solid rgba(255,255,255,.42); border-radius:20px; pointer-events:none; }
.cl-card::after { content:""; position:absolute; width:240px; height:240px; right:-92px; bottom:-132px; border-radius:999px; background:radial-gradient(circle, rgba(184,139,62,.16), rgba(184,139,62,0) 68%); z-index:-1; }
.cl-card.urgent { border-color:rgba(183,66,43,.36); background:radial-gradient(circle at 88% 16%, rgba(183,66,43,.2), transparent 190px), linear-gradient(145deg, #fff8ec, #f7e5d8); }
.cl-card.review { background:radial-gradient(circle at 88% 16%, rgba(15,107,95,.16), transparent 190px), linear-gradient(145deg, #fffdf4, #eaf3ec); }
.cl-card.weakpoint { background:radial-gradient(circle at 88% 16%, rgba(184,139,62,.18), transparent 190px), linear-gradient(145deg, #fffaf0, #f3ead6); }
.cl-card.clear { background:radial-gradient(circle at 88% 16%, rgba(15,107,95,.11), transparent 190px), linear-gradient(145deg, #fffdf7, #eef5ea); }
.cl-card.quiet { background:linear-gradient(145deg, rgba(255,252,244,.92), rgba(241,234,221,.76)); }
.cl-mark { position:absolute; right:28px; top:18px; width:58px; height:58px; display:grid; place-items:center; border:1px solid rgba(183,66,43,.24); border-radius:18px; color:rgba(183,66,43,.82); background:rgba(255,255,255,.38); box-shadow:inset 0 0 0 6px rgba(255,250,240,.5); font-family:var(--font-display-family); font-size:28px; }
.cl-copy { max-width:720px; padding-right:86px; }
.cl-eyebrow { margin:0 0 7px; color:var(--cinnabar,#b7422b); font-size:11px; font-weight:900; letter-spacing:.22em; }
.cl-title { margin:0; font-size:clamp(21px, 3vw, 28px); color:var(--ink,#1a1612); letter-spacing:.05em; }
.cl-desc { max-width:680px; margin:10px 0 0; color:var(--ink-soft,#66584b); line-height:1.78; font-size:14px; }
.cl-reason { max-width:680px; margin:10px 0 0; color:var(--muted,#887967); line-height:1.7; font-size:13px; }
.cl-reason strong { color:var(--ink,#1a1612); }
.cl-chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }
.cl-chip { display:inline-flex; align-items:center; gap:7px; border-radius:999px; padding:6px 10px; border:1px solid rgba(96,72,44,.12); background:rgba(255,252,244,.66); }
.cl-chip small { color:var(--muted,#887967); font-size:11px; font-weight:800; }
.cl-chip b { color:var(--ink,#1a1612); font-size:12px; }
.cl-chip.danger { background:#fee2e2; border-color:#fecaca; }
.cl-chip.gold { background:#fef3c7; border-color:#fde68a; }
.cl-chip.jade { background:#dff3eb; border-color:#bfe4d7; }
.cl-chip.muted { background:rgba(241,234,221,.7); }
.cl-actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:18px; }
.cl-primary,.cl-secondary { display:inline-flex; align-items:center; justify-content:center; min-height:38px; padding:9px 16px; border-radius:999px; font-size:13px; font-weight:850; text-decoration:none; transition:transform var(--ease), box-shadow var(--ease), background var(--ease); }
.cl-primary { color:#fffaf0; background:linear-gradient(135deg, var(--cinnabar,#b7422b), var(--cinnabar-dark,#8d2d1c)); box-shadow:0 12px 26px rgba(183,66,43,.2); }
.cl-secondary { color:var(--jade-dark,#0b4f48); background:rgba(15,107,95,.08); border:1px solid rgba(15,107,95,.18); }
.cl-primary:hover,.cl-secondary:hover { transform:translateY(-2px); box-shadow:0 14px 30px rgba(59,39,19,.12); }
.cl-meta { position:absolute; right:26px; bottom:22px; max-width:180px; border:1px solid rgba(96,72,44,.14); border-radius:999px; padding:5px 10px; background:rgba(255,252,244,.68); color:var(--muted,#887967); font-size:12px; font-weight:800; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.cl-loading { min-height:172px; }
.cl-orbit { position:absolute; right:30px; top:24px; width:54px; height:54px; border-radius:18px; background:linear-gradient(90deg,#f2eadc 0%,#fffaf0 48%,#f2eadc 100%); background-size:220% 100%; animation:clShimmer 1.2s ease-in-out infinite; }
.cl-skel-kicker,.cl-skel-title,.cl-skel-line,.cl-skel-actions span { display:block; border-radius:999px; background:linear-gradient(90deg,#f2eadc 0%,#fffaf0 48%,#f2eadc 100%); background-size:220% 100%; animation:clShimmer 1.2s ease-in-out infinite; }
.cl-skel-kicker { width:210px; height:12px; margin-bottom:16px; }
.cl-skel-title { width:min(420px, 70%); height:30px; margin-bottom:14px; }
.cl-skel-line { width:min(620px, 84%); height:14px; }
.cl-skel-actions { display:flex; gap:10px; margin-top:24px; }
.cl-skel-actions span { width:108px; height:38px; }
@keyframes clShimmer { 0%{background-position:120% 0} 100%{background-position:-120% 0} }
@media (max-width: 620px) { .cl-card { padding:20px 18px; border-radius:20px; } .cl-copy { padding-right:0; } .cl-mark { position:relative; right:auto; top:auto; margin-bottom:12px; width:50px; height:50px; } .cl-meta { position:static; display:inline-flex; margin-top:12px; } }
`;
