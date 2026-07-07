"use client";
import { useCallback, useEffect, useState } from "react";
import { fetchApiJson, normalizeError } from "@/lib/api";

export type Profile = { recent_topics: string[]; weak_topics: string[]; grade?: string | null };
export type Weakpoint = { knowledge_tag: string; wrong_count: number; last_wrong_at: string; source: string };
export type ReviewPlan = { recommended_actions?: string[]; weakpoints?: Weakpoint[]; priority_topics?: string[] };
export type TodayTask = {
  kind: "assignment" | "review" | "weakpoint";
  priority: "urgent" | "high" | "normal";
  title: string;
  detail: string;
  href: string;
  count?: number;
  ref_id?: string | null;
};
export type TodayPlan = {
  date: string;
  tasks: TodayTask[];
  summary: {
    pending_assignments: number;
    overdue_assignments: number;
    review_remaining: number;
    weakpoint_count: number;
    all_clear: boolean;
  };
};

type ProfileResponse = { profile?: Profile };
type ReviewPlanResponse = { review_plan?: ReviewPlan };

export function useStudentWorkbenchData(studentId?: string, token?: string) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [reviewPlan, setReviewPlan] = useState<ReviewPlan | null>(null);
  const [todayPlan, setTodayPlan] = useState<TodayPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refreshTodayPlan = useCallback(async () => {
    if (!studentId || !token) return null;
    const data = await fetchApiJson<TodayPlan>(`/api/students/${studentId}/today`, {
      token,
      fallbackMessage: "今日计划加载失败",
    });
    setTodayPlan(data);
    return data;
  }, [studentId, token]);

  const load = useCallback(async () => {
    if (!studentId || !token) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    const [profileResult, reviewPlanResult, todayResult] = await Promise.allSettled([
      fetchApiJson<ProfileResponse>(`/api/students/${studentId}/profile`, { token, fallbackMessage: "学生画像加载失败" }),
      fetchApiJson<ReviewPlanResponse>(`/api/students/${studentId}/review-plan`, { token, fallbackMessage: "复习计划加载失败" }),
      fetchApiJson<TodayPlan>(`/api/students/${studentId}/today`, { token, fallbackMessage: "今日计划加载失败" }),
    ]);

    if (profileResult.status === "fulfilled" && profileResult.value.profile) {
      setProfile(profileResult.value.profile);
    }
    if (reviewPlanResult.status === "fulfilled" && reviewPlanResult.value.review_plan) {
      setReviewPlan(reviewPlanResult.value.review_plan);
    }
    if (todayResult.status === "fulfilled") {
      setTodayPlan(todayResult.value);
    } else {
      setTodayPlan(null);
      setError(normalizeError(todayResult.reason, "今日计划加载失败"));
    }
    setLoading(false);
  }, [studentId, token]);

  useEffect(() => {
    void load();
  }, [load]);

  return { profile, reviewPlan, todayPlan, loading, error, refreshTodayPlan };
}
