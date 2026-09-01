export type DemoNavNode = {
  label: string;
  href?: string;
  icon: string;
  primary?: boolean;
  badgeKey?: string;
  badgeKeys?: string[];
  children?: DemoNavNode[];
};

export const DEMO_NAVIGATION: Record<"student" | "teacher", DemoNavNode[]> = {
  student: [
    { label: "今日主线", href: "/student", icon: "home", primary: true },
    { label: "Agent 辅导", href: "/student/auto-tutor", icon: "bot", primary: true },
    { label: "学习证据", href: "/student/review", icon: "evidence", primary: true, badgeKey: "pending_review" },
    {
      label: "更多能力",
      icon: "more",
      children: [
        { label: "随问", href: "/student/assistant", icon: "assistant" },
        { label: "我的作业", href: "/student/assignments", icon: "assignment", badgeKey: "pending_assignments" },
        { label: "学习资料", href: "/student/materials", icon: "materials" },
        { label: "能力展厅", href: "/student/history", icon: "showcase" },
      ],
    },
  ],
  teacher: [
    { label: "教师总览", href: "/teacher", icon: "dashboard", primary: true },
    { label: "班级证据", href: "/teacher/class-analytics", icon: "evidence", primary: true },
    { label: "Pilot 作业", href: "/teacher/assignments", icon: "assignment", primary: true, badgeKeys: ["pending_review", "blind_spots_to_review"] },
    {
      label: "更多能力",
      icon: "more",
      children: [
        { label: "作文与作业批改", href: "/teacher/grading", icon: "grading" },
        { label: "命题质量", href: "/teacher/quality-dashboard", icon: "quality" },
        { label: "资料生成", href: "/teacher/materials", icon: "materials" },
        { label: "资源库", href: "/teacher/resources", icon: "resources" },
      ],
    },
  ],
};

export function demoPrimaryDestinations(role: "student" | "teacher"): DemoNavNode[] {
  return DEMO_NAVIGATION[role].filter((item) => item.primary && item.href);
}

export function demoMoreDestinations(role: "student" | "teacher"): DemoNavNode[] {
  return DEMO_NAVIGATION[role].flatMap((item) => item.children || []);
}
