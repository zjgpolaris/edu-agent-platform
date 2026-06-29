"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";

const HIDDEN_PATHS = ["/", "/login"];

const STUDENT_NAV_LINKS = [
  { href: "/student-home", label: "学习中心" },
  { href: "/textbook-learning", label: "教材同步" },
  { href: "/material-upload", label: "资料上传" },
  { href: "/materials", label: "我的资料" },
  { href: "/homework-grading", label: "拍照批改" },
  { href: "/history-character", label: "人物对话" },
  { href: "/history-games", label: "游戏大厅" },
  { href: "/quiz-practice", label: "智能练习" },
  { href: "/student-dashboard", label: "学情分析" },
];

const TEACHER_NAV_LINKS = [
  { href: "/teacher-home", label: "班级管理" },
  { href: "/teacher/dashboard", label: "学情总览" },
  { href: "/essay-grading", label: "作文批改" },
  { href: "/homework-grading", label: "拍照批改" },
  { href: "/material-upload", label: "资料生成" },
  { href: "/materials", label: "资料库" },
  { href: "/textbook-learning", label: "教学资源" },
];

export default function GlobalHeader() {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  if (!user || HIDDEN_PATHS.includes(pathname)) return null;

  function handleLogout() {
    logout();
    router.push("/login");
  }

  const isTeacherLike = user.role === "teacher" || user.role === "admin";
  const navLinks = isTeacherLike ? TEACHER_NAV_LINKS : STUDENT_NAV_LINKS;
  const homeHref = isTeacherLike ? "/teacher-home" : "/student-home";
  const homeLabel = isTeacherLike ? "教师工作台" : "学习中心";

  return (
    <header className="global-header">
      <Link href={homeHref} className="global-header-brand">{homeLabel}</Link>
      <nav className="global-header-nav">
        {navLinks.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            className={`global-header-nav-link${pathname === href || (href !== homeHref && pathname.startsWith(href)) ? " active" : ""}`}
          >
            {label}
          </Link>
        ))}
      </nav>
      <div className="global-header-user">
        <div className="global-header-avatar">
          {user.displayName ? user.displayName.charAt(0).toUpperCase() : user.actorId.charAt(0).toUpperCase()}
        </div>
        <span className="global-header-username">{user.displayName || user.actorId}</span>
        <span className={`global-header-role-badge ${user.role === "teacher" ? "teacher" : "student"}`}>
          {user.role === "teacher" ? "教师" : "学生"}
        </span>
        <button className="global-header-logout" onClick={handleLogout}>退出</button>
      </div>
    </header>
  );
}
