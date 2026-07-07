"use client";
import { Suspense } from "react";
import dynamic from "next/dynamic";
import TextbookTab from "./TextbookTab";
import TabShell from "../components/TabShell";

// 资料库页面体积大，懒加载避免首屏 bundle 膨胀
const MaterialsTab = dynamic(() => import("@/app/material-upload/page"), { ssr: false });

type Tab = "materials" | "textbook";

function LearningResourcesInner() {
  return (
    <TabShell<Tab>
      ariaLabel="学习资源切换"
      defaultTab="materials"
      tabs={[
        { value: "materials", label: "我的资料", render: <MaterialsTab /> },
        { value: "textbook", label: "教材目录", render: <TextbookTab /> },
      ]}
    />
  );
}

export default function LearningResourcesPage() {
  return (
    <Suspense>
      <LearningResourcesInner />
    </Suspense>
  );
}
