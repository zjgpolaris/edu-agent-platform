import CardGameClient from "./CardGameClient";

export const metadata = {
  title: "时间巨轮 AI 卡牌游戏 | EduAgent",
  description: "通过事件卡排序、AI 讲解和一次修正机会训练历史时间观念。",
};

export default function HistoryCardGamePage() {
  return <CardGameClient />;
}
