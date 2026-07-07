"use client";
import { Suspense } from "react";
import ReviewTab from "./ReviewTab";
import WeakpointsTab from "./WeakpointsTab";
import TabShell from "../components/TabShell";

type Tab = "review" | "weakpoints";

function ReviewCenterInner() {
  return (
    <TabShell<Tab>
      ariaLabel="复习中心切换"
      defaultTab="review"
      tabs={[
        { value: "review", label: "今日任务", render: <ReviewTab /> },
        { value: "weakpoints", label: "错题库", render: <WeakpointsTab /> },
      ]}
    />
  );
}

export default function ReviewCenterPage() {
  return (
    <Suspense>
      <ReviewCenterInner />
    </Suspense>
  );
}
