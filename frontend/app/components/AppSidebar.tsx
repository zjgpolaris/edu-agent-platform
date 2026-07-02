"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type NavItem = {
  label: string;
  href?: string;
  icon: string;
  children?: NavItem[];
  badgeKey?: string;
};

type Badges = Record<string, number>;

const studentNav: NavItem[] = [
  { label: "今日学习", href: "/student", icon: "⌂" },
  { label: "自主辅导", href: "/student/auto-tutor", icon: "辅" },
  {
    label: "学习中心", icon: "◎", children: [
      { label: "教材同步", href: "/student/textbook", icon: "册" },
      { label: "资料学习", href: "/student/materials", icon: "纸" },
      { label: "学习助手", href: "/student/assistant", icon: "问" },
    ],
  },
  {
    label: "历史探索", icon: "宫", children: [
      { label: "人物对话馆", href: "/student/history/chat", icon: "人" },
      { label: "历史辩论场", href: "/student/history/debate", icon: "辩" },
      { label: "历史游戏厅", href: "/student/history/games", icon: "弈" },
      { label: "历史地图", href: "/student/history/map", icon: "图" },
    ],
  },
  {
    label: "我的学情", icon: "析", children: [
      { label: "我的作业", href: "/student/assignments", icon: "业", badgeKey: "pending_assignments" },
      { label: "今日复习", href: "/student/review", icon: "复", badgeKey: "pending_review" },
      { label: "学情分析", href: "/student/dashboard", icon: "析" },
      { label: "学习路径", href: "/student/learning-path", icon: "路" },
      { label: "成长报告", href: "/student/report", icon: "报" },
      { label: "错题本", href: "/student/weakpoints", icon: "错" },
      { label: "智能练习", href: "/student/quiz", icon: "练" },
      { label: "记忆中心", href: "/student/memory", icon: "忆" },
    ],
  },
];

const teacherNav: NavItem[] = [
  { label: "班级总览", href: "/teacher", icon: "班" },
  {
    label: "批改工作台", icon: "批", children: [
      { label: "布置作业", href: "/teacher/assignments", icon: "业", badgeKey: "pending_review" },
      { label: "作文批改", href: "/teacher/grading?tab=essay", icon: "文" },
      { label: "拍照批改", href: "/teacher/grading?tab=homework", icon: "拍" },
    ],
  },
  {
    label: "教学备课", icon: "备", children: [
      { label: "资料生成", href: "/teacher/materials", icon: "生" },
      { label: "资源库", href: "/teacher/resources", icon: "库" },
    ],
  },
  {
    label: "系统运维", icon: "运", children: [
      { label: "Eval Dashboard", href: "/eval", icon: "测" },
      { label: "班级学情", href: "/teacher/class-analytics", icon: "析" },
    ],
  },
];

function navBadgeCount(item: NavItem, badges: Badges): number {
  let n = item.badgeKey ? (badges[item.badgeKey] || 0) : 0;
  if (item.children) {
    for (const c of item.children) n += navBadgeCount(c, badges);
  }
  return n;
}

function Badge({ count, collapsed }: { count: number; collapsed: boolean }) {
  if (count <= 0) return null;
  if (collapsed) return <span className="sidebar-badge-dot" aria-label={`${count} 项待处理`} />;
  return <span className="sidebar-badge">{count > 99 ? "99+" : count}</span>;
}

function NavGroup({ item, collapsed, badges }: { item: NavItem; collapsed: boolean; badges: Badges }) {
  const pathname = usePathname();
  const isChildActive = item.children?.some(
    (c) => c.href && pathname.startsWith(c.href.split("?")[0])
  );
  const storageKey = `sidebar-group-${item.label}`;
  const [open, setOpen] = useState(() => {
    if (isChildActive) return true;
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem(storageKey);
      if (saved !== null) return saved === "1";
    }
    return false;
  });

  function toggleGroup() {
    setOpen((v) => {
      localStorage.setItem(storageKey, v ? "0" : "1");
      return !v;
    });
  }

  if (!item.children) {
    const active = item.href === "/student" || item.href === "/teacher"
      ? pathname === item.href
      : item.href && pathname.startsWith(item.href.split("?")[0]);
    const count = navBadgeCount(item, badges);
    return (
      <Link href={item.href!} className={`sidebar-item${active ? " active" : ""}`} title={collapsed ? item.label : undefined}>
        <span className="sidebar-icon">{item.icon}{collapsed && <Badge count={count} collapsed />}</span>
        {!collapsed && <span className="sidebar-label">{item.label}</span>}
        {!collapsed && <Badge count={count} collapsed={false} />}
      </Link>
    );
  }

  const groupCount = navBadgeCount(item, badges);
  return (
    <div className="sidebar-group">
      <button
        className={`sidebar-item sidebar-group-btn${isChildActive ? " active" : ""}`}
        onClick={toggleGroup}
        title={collapsed ? item.label : undefined}
      >
        <span className="sidebar-icon">{item.icon}{collapsed && <Badge count={groupCount} collapsed />}</span>
        {!collapsed && (
          <>
            <span className="sidebar-label">{item.label}</span>
            {!open && <Badge count={groupCount} collapsed={false} />}
            <span className="sidebar-chevron">{open ? "▾" : "▸"}</span>
          </>
        )}
      </button>
      {open && !collapsed && (
        <div className="sidebar-children">
          {item.children.map((child) => {
            const active = child.href && pathname.startsWith(child.href.split("?")[0]);
            const count = navBadgeCount(child, badges);
            return (
              <Link
                key={child.href}
                href={child.href!}
                className={`sidebar-item sidebar-child${active ? " active" : ""}`}
                title={collapsed ? child.label : undefined}
              >
                <span className="sidebar-icon">{child.icon}</span>
                <span className="sidebar-label">{child.label}</span>
                <Badge count={count} collapsed={false} />
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function AppSidebar({ role }: { role: "student" | "teacher" }) {
  const [collapsed, setCollapsed] = useState(false);
  const [recentTopic, setRecentTopic] = useState("");
  const [badges, setBadges] = useState<Badges>({});
  const { user, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    const saved = localStorage.getItem("sidebar-collapsed");
    if (saved) setCollapsed(saved === "1");
  }, []);

  useEffect(() => {
    if (role !== "student" || !user?.actorId) return;
    fetch(`${API}/api/students/${user.actorId}/profile`, { headers: authHeaders(user.token) })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { const t = d?.profile?.recent_topics?.[0]; if (t) setRecentTopic(t); })
      .catch(() => {});
  }, [role, user?.actorId, user?.token]);

  // 通知徽标：按角色拉取待处理事项数，60s 轮询一次
  useEffect(() => {
    if (!user?.token) return;
    let cancelled = false;
    const url = role === "teacher"
      ? `${API}/api/teacher/badges`
      : (user.actorId ? `${API}/api/student/${user.actorId}/badges` : null);
    if (!url) return;
    const fetchBadges = () => {
      fetch(url, { headers: authHeaders(user.token) })
        .then((r) => r.ok ? r.json() : null)
        .then((d) => { if (!cancelled && d && typeof d === "object") setBadges(d as Badges); })
        .catch(() => {});
    };
    fetchBadges();
    const timer = setInterval(fetchBadges, 60000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [role, user?.actorId, user?.token]);

  function toggle() {
    setCollapsed((v) => {
      localStorage.setItem("sidebar-collapsed", v ? "0" : "1");
      return !v;
    });
  }

  function handleLogout() {
    logout();
    router.push("/");
  }

  const nav = role === "teacher" ? teacherNav : studentNav;
  const roleLabel = role === "teacher" ? "教师工作台" : "学生学习舱";
  const displayName = user?.displayName || user?.actorId || "";
  const initial = displayName.charAt(0).toUpperCase();

  return (
    <aside className={`app-sidebar app-sidebar-${role}${collapsed ? " collapsed" : ""}`}>
      <div className="sidebar-brand-panel">
        <Link href={role === "teacher" ? "/teacher" : "/student"} className="sidebar-brand" title={collapsed ? "EduAgent" : undefined}>
          <span className="sidebar-brand-mark" aria-hidden="true">E</span>
          {!collapsed && (
            <span className="sidebar-brand-copy">
              <strong>EduAgent</strong>
              <small>{roleLabel}</small>
            </span>
          )}
        </Link>
        <button className="sidebar-toggle" onClick={toggle} aria-label="收起/展开侧边栏">
          {collapsed ? "▸" : "◂"}
        </button>
      </div>
      {!collapsed && (
        <div className="sidebar-context-card" aria-label="当前学习主题">
          <span>{role === "teacher" ? "今日批改" : "今日主线"}</span>
          <strong>{role === "teacher" ? "班级学习证据" : (recentTopic || "暂无记录")}</strong>
        </div>
      )}
      <nav className="sidebar-nav" aria-label={roleLabel}>
        {nav.map((item) => (
          <NavGroup key={item.label} item={item} collapsed={collapsed} badges={badges} />
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="sidebar-avatar">{initial}</div>
        {!collapsed && (
          <div className="sidebar-user-info">
            <span className="sidebar-username">{displayName}</span>
            <span className={`sidebar-role-badge ${role}`}>{role === "teacher" ? "教师" : "学生"}</span>
          </div>
        )}
        <button className="sidebar-logout" onClick={handleLogout} title="退出登录">⏻</button>
      </div>
    </aside>
  );
}

type MobileNavItem = { href: string; icon: string; label: string; badgeKey?: string };

const STUDENT_MOBILE_NAV: MobileNavItem[] = [
  { href: "/student", icon: "主", label: "首页" },
  { href: "/student/auto-tutor", icon: "辅", label: "辅导" },
  { href: "/student/assistant", icon: "问", label: "助手" },
  { href: "/student/review", icon: "复", label: "复习", badgeKey: "pending_review" },
];
const STUDENT_MORE_NAV: MobileNavItem[] = [
  { href: "/student/assignments", icon: "业", label: "我的作业" },
  { href: "/student/history/chat", icon: "人", label: "历史对话" },
  { href: "/student/history/games", icon: "弈", label: "历史游戏" },
  { href: "/student/textbook", icon: "册", label: "教材学习" },
  { href: "/student/materials", icon: "纸", label: "资料学习" },
  { href: "/student/weakpoints", icon: "错", label: "错题本" },
  { href: "/student/report", icon: "报", label: "成长报告" },
  { href: "/student/learning-path", icon: "路", label: "学习路径" },
  { href: "/student/memory", icon: "忆", label: "记忆中心" },
  { href: "/student/quiz", icon: "练", label: "智能练习" },
];
const TEACHER_MOBILE_NAV: MobileNavItem[] = [
  { href: "/teacher", icon: "班", label: "总览" },
  { href: "/teacher/grading", icon: "批", label: "批改" },
  { href: "/teacher/class-analytics", icon: "析", label: "学情" },
];
const TEACHER_MORE_NAV: MobileNavItem[] = [
  { href: "/teacher/assignments", icon: "业", label: "布置作业", badgeKey: "pending_review" },
  { href: "/teacher/materials", icon: "生", label: "资料生成" },
  { href: "/teacher/resources", icon: "库", label: "资源库" },
  { href: "/eval", icon: "测", label: "Eval" },
];

function badgeOf(badges: Badges, item: { badgeKey?: string }): number {
  return item.badgeKey ? (badges[item.badgeKey] || 0) : 0;
}

export function MobileBottomNav({ role }: { role: "student" | "teacher" }) {
  const pathname = usePathname();
  const { user } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [badges, setBadges] = useState<Badges>({});
  const items = role === "teacher" ? TEACHER_MOBILE_NAV : STUDENT_MOBILE_NAV;
  const moreItems = role === "teacher" ? TEACHER_MORE_NAV : STUDENT_MORE_NAV;

  useEffect(() => {
    if (!user?.token) return;
    let cancelled = false;
    const url = role === "teacher"
      ? `${API}/api/teacher/badges`
      : (user.actorId ? `${API}/api/student/${user.actorId}/badges` : null);
    if (!url) return;
    const run = () => {
      fetch(url, { headers: authHeaders(user.token) })
        .then((r) => r.ok ? r.json() : null)
        .then((d) => { if (!cancelled && d && typeof d === "object") setBadges(d as Badges); })
        .catch(() => {});
    };
    run();
    const timer = setInterval(run, 60000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [role, user?.actorId, user?.token]);

  const moreCount = moreItems.reduce((s, it) => s + badgeOf(badges, it), 0);

  return (
    <>
      {menuOpen && (
        <div className="mbn-overlay" onClick={() => setMenuOpen(false)}>
          <div className="mbn-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="mbn-drawer-grid">
              {[...items, ...moreItems].map((item) => (
                <Link key={item.href} href={item.href} className="mbn-drawer-item" onClick={() => setMenuOpen(false)}>
                  <span className="mbn-icon">{item.icon}</span>
                  <span className="mbn-label">{item.label}</span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}
      <nav className="mobile-bottom-nav" aria-label="移动端导航">
        {items.map((item) => {
          const active = item.href === "/student" || item.href === "/teacher"
            ? pathname === item.href
            : pathname.startsWith(item.href);
          const count = badgeOf(badges, item);
          return (
            <Link key={item.href} href={item.href} className={`mbn-item${active ? " active" : ""}`}>
              <span className="mbn-icon">{item.icon}{count > 0 && <span className="sidebar-badge-dot" />}</span>
              <span className="mbn-label">{item.label}</span>
            </Link>
          );
        })}
        <button type="button" className="mbn-item" onClick={() => setMenuOpen(true)}>
          <span className="mbn-icon">≡{moreCount > 0 && <span className="sidebar-badge-dot" />}</span>
          <span className="mbn-label">更多</span>
        </button>
      </nav>
    </>
  );
}