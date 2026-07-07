"use client";
import { Suspense } from "react";
import dynamic from "next/dynamic";
import TabShell from "../components/TabShell";

// 两个子页面体积较大，懒加载避免首屏 bundle 膨胀
const DashboardTab = dynamic(() => import("@/app/student-dashboard/page"), { ssr: false });
const ReportTab    = dynamic(() => import("@/app/(student)/student/report/page"), { ssr: false });

type Tab = "dashboard" | "report";

function LearningOverviewInner() {
  return (
    <TabShell<Tab>
      ariaLabel="学情总览切换"
      defaultTab="dashboard"
      tabs={[
        { value: "dashboard", label: "学情速览", render: <DashboardTab /> },
        { value: "report", label: "成长报告", render: <ReportTab /> },
      ]}
    />
  );
}

export default function LearningOverviewPage() {
  return (
    <Suspense>
      <LearningOverviewInner />
    </Suspense>
  );
}
