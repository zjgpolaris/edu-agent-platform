const GAMES = [
  {
    id: "multiplayer",
    title: "时间巨轮",
    subtitle: "多人 · 对战模式",
    description: "与 AI 玩家轮流出牌，把手牌插入时间轴正确位置。手牌最先清空者获胜。",
    href: "/history-games/multiplayer",
    seal: "战",
  },
  {
    id: "card-game",
    title: "AI 卡牌游戏",
    subtitle: "单人 · AI 判题",
    description: "抽取历史事件卡，把它们放进横向时间轴。系统按真实年份判定顺序，并对错误卡给出讲解和追问。",
    href: "/history-games/card-game",
    seal: "轮",
  },
];

export default function HistoryGamesClient() {
  return (
    <main className="academy-shell history-games-shell game-hall-shell">
      <section className="game-hall-grid" aria-label="历史小游戏列表">
        {GAMES.map((game) => (
          <a className="game-hall-card available" href={game.href} key={game.id}>
            <div className="game-hall-card-topline">
              <span>已开放</span>
              <div className="game-hall-card-seal" aria-hidden="true">{game.seal}</div>
            </div>
            <div className="game-hall-card-body">
              <strong>{game.title}</strong>
              <small>{game.subtitle}</small>
              <p>{game.description}</p>
            </div>
            <div className="game-hall-card-action">进入游戏</div>
          </a>
        ))}
      </section>
    </main>
  );
}
