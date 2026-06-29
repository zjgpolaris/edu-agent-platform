import Link from "next/link";

const modules = [
  {
    href: "/student/history/chat",
    title: "人物对话馆",
    desc: "与历史人物展开追问，在角色视角中理解人物选择和时代处境。",
    icon: "人",
  },
  {
    href: "/student/history/debate",
    title: "历史辩论场",
    desc: "围绕辩题组织论点、论据和反驳，训练历史思辨与表达能力。",
    icon: "辩",
  },
  {
    href: "/student/history/games",
    title: "历史游戏厅",
    desc: "通过时间线、卡牌和多人模拟，把历史知识放进可挑战的任务里。",
    icon: "弈",
  },
  {
    href: "/student/history/map",
    title: "历史地图",
    desc: "在地图上探索历史事件的地理分布与演变脉络。",
    icon: "图",
  },
];

export default function HistoryHubPage() {
  return (
    <main className="workbench-page">
      <section className="workbench-hero">
        <div className="workbench-hero-copy">
          <p className="workbench-kicker">历史探索中心</p>
          <h1>选择探索方式，深入历史现场</h1>
          <p>四种视角切入历史：对话、辩论、游戏与地图，让历史学习立体起来。</p>
        </div>
      </section>
      <section className="workbench-module-grid" style={{ padding: "0 0 40px" }}>
        {modules.map((m) => (
          <Link key={m.href} href={m.href} className="workbench-module-card">
            <span className="workbench-module-icon">{m.icon}</span>
            <div>
              <h3>{m.title}</h3>
              <p>{m.desc}</p>
            </div>
            <strong>进入</strong>
          </Link>
        ))}
      </section>
    </main>
  );
}
