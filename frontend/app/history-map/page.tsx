"use client";

import dynamic from "next/dynamic";

const HistoryMapClient = dynamic(
  () => import("./HistoryMapClient").then((mod) => mod.default),
  {
    ssr: false,
    loading: () => <div className="p-8 text-center">加载地图中...</div>,
  }
);

export default function HistoryMapPage() {
  return <HistoryMapClient />;
}
