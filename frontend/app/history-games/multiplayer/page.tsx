import MultiplayerGameClient from "./MultiplayerGameClient";

export const metadata = {
  title: "时间巨轮 | EduAgent",
  description: "与 AI 玩家轮流出牌，手牌最先清空者获胜。",
};

export default function MultiplayerGamePage() {
  return <MultiplayerGameClient />;
}
