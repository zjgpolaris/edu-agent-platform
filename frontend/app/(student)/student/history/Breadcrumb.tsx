"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const labels: Record<string, string> = {
  "/student/history/chat": "人物对话馆",
  "/student/history/debate": "历史辩论场",
  "/student/history/games": "历史游戏厅",
  "/student/history/map": "历史地图",
};

export default function HistoryBreadcrumb() {
  const pathname = usePathname();
  const label = labels[pathname];
  if (!label) return null;
  return (
    <nav className="history-breadcrumb" aria-label="面包屑">
      <Link href="/student/history">历史探索</Link>
      <span className="history-breadcrumb-sep" aria-hidden="true">/</span>
      <span>{label}</span>
    </nav>
  );
}
