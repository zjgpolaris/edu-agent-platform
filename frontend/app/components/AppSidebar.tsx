"use client";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";
import {
  Home, Bot, BookOpen, MessageSquare, Sword, Gamepad2, Map,
  ClipboardList, RotateCcw, BrainCircuit, BarChart3, Route,
  Sparkles, Award, BookMarked, HelpCircle, Users, FileText,
  Camera, TrendingUp, Library, Settings, LogOut,
  ChevronDown, ChevronRight, LayoutDashboard, CalendarDays,
  Pencil, Database, Star, Bell, Layers
} from "lucide-react";
import { useAuth as _useAuth } from "@/contexts/AuthContext";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type NavItem = {
  label: string;
  href?: string;
  LucideIcon?: React.ElementType;
  children?: NavItem[];
  badgeKey?: string;
  badgeKeys?: string[];
};

type Badges = Record<string, number>;

const studentNav: NavItem[] = [
  { label: "今日学习", href: "/student", LucideIcon: Home },
  { label: "随问", href: "/student/assistant", LucideIcon: HelpCircle },
  { label: "自主辅导", href: "/student/auto-tutor", LucideIcon: Bot },
  {
    label: "学习资源", LucideIcon: BookOpen, children: [
      { label: "学习资料", href: "/student/materials", LucideIcon: Library },
    ],
  },
  {
    label: "历史探索", LucideIcon: Layers, children: [
      { label: "人物对话馆", href: "/student/history/chat", LucideIcon: MessageSquare },
      { label: "历史辩论场", href: "/student/history/debate", LucideIcon: Sword },
      { label: "历史游戏厅", href: "/student/history/games", LucideIcon: Gamepad2 },
      { label: "历史地图", href: "/student/history/map", LucideIcon: Map },
    ],
  },
  {
    label: "练习复习", LucideIcon: RotateCcw, children: [
      { label: "我的作业", href: "/student/assignments", LucideIcon: ClipboardList, badgeKey: "pending_assignments" },
      { label: "复习中心", href: "/student/review", LucideIcon: RotateCcw, badgeKey: "pending_review" },
      { label: "智能练习", href: "/student/quiz", LucideIcon: BrainCircuit },
    ],
  },
  {
    label: "我的成长", LucideIcon: TrendingUp, children: [
      { label: "学情总览", href: "/student/dashboard", LucideIcon: BarChart3 },
      { label: "学习路径", href: "/student/learning-path", LucideIcon: Route },
      { label: "记忆中心", href: "/student/memory", LucideIcon: Sparkles },
      { label: "学习日历", href: "/student/calendar", LucideIcon: CalendarDays },
      { label: "我的成就", href: "/student/achievements", LucideIcon: Award },
    ],
  },
];

const teacherNav: NavItem[] = [
  { label: "班级总览", href: "/teacher", LucideIcon: LayoutDashboard },
  {
    label: "批改工作台", LucideIcon: Pencil, children: [
      { label: "布置作业", href: "/teacher/assignments", LucideIcon: ClipboardList, badgeKeys: ["pending_review", "blind_spots_to_review"] },
      { label: "作文批改", href: "/teacher/grading?tab=essay", LucideIcon: FileText },
      { label: "拍照批改", href: "/teacher/grading?tab=homework", LucideIcon: Camera },
    ],
  },
  {
    label: "教学分析", LucideIcon: BarChart3, children: [
      { label: "班级学情", href: "/teacher/class-analytics", LucideIcon: TrendingUp },
      { label: "命题质量", href: "/teacher/quality-dashboard", LucideIcon: Star },
    ],
  },
  {
    label: "教学备课", LucideIcon: BookMarked, children: [
      { label: "资料生成", href: "/teacher/materials", LucideIcon: Database },
      { label: "资源库", href: "/teacher/resources", LucideIcon: Library },
    ],
  },
];

function navBadgeCount(item: NavItem, badges: Badges): number {
  let n = item.badgeKey ? (badges[item.badgeKey] || 0) : 0;
  if (item.badgeKeys) {
    for (const k of item.badgeKeys) n += badges[k] || 0;
  }
  if (item.children) {
    for (const c of item.children) n += navBadgeCount(c, badges);
  }
  return n;
}

function isActivePath(pathname: string, href: string, currentSearch?: string): boolean {
  const [path, query] = href.split("?");
  const pathActive = path === "/student" || path === "/teacher" ? pathname === path : pathname.startsWith(path);
  if (!pathActive) return false;
  return query && currentSearch !== undefined ? currentSearch === query : true;
}

function isPreciseMobileActive(pathname: string, href: string, currentSearch: string, siblings: MobileNavItem[]): boolean {
  const [path, query] = href.split("?");
  if (!isActivePath(pathname, href, currentSearch)) return false;
  if (query) return true;
  return !siblings.some((item) => item.href !== href && item.href.startsWith(`${path}?`) && isActivePath(pathname, item.href, currentSearch));
}

function Badge({ count, collapsed }: { count: number; collapsed: boolean }) {
  if (count <= 0) return null;
  if (collapsed) return <span className="sidebar-badge-dot" aria-label={`${count} 项待处理`} />;
  return <span className="sidebar-badge">{count > 99 ? "99+" : count}</span>;
}

function NavGroup({ item, collapsed, badges }: { item: NavItem; collapsed: boolean; badges: Badges }) {
  const pathname = usePathname();
  const isChildActive = item.children?.some((c) => c.href && isActivePath(pathname, c.href));
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

  const Icon = item.LucideIcon;

  if (!item.children) {
    const active = item.href ? isActivePath(pathname, item.href) : false;
    const count = navBadgeCount(item, badges);
    return (
      <Link href={item.href!} className={`sidebar-item${active ? " active" : ""}`} title={collapsed ? item.label : undefined}>
        <span className="sidebar-icon">
          {Icon && <Icon size={15} strokeWidth={2.2} />}
          {collapsed && <Badge count={count} collapsed />}
        </span>
        {!collapsed && <span className="sidebar-label">{item.label}</span>}
        {!collapsed && <Badge count={count} collapsed={false} />}
      </Link>
    );
  }

  const groupCount = navBadgeCount(item, badges);
  return (
    <div className="sidebar-group">
      <button
        type="button"
        className={`sidebar-item sidebar-group-btn${isChildActive ? " active" : ""}`}
        onClick={toggleGroup}
        title={collapsed ? item.label : undefined}
        aria-expanded={open}
      >
        <span className="sidebar-icon">
          {Icon && <Icon size={15} strokeWidth={2.2} />}
          {collapsed && <Badge count={groupCount} collapsed />}
        </span>
        {!collapsed && (
          <>
            <span className="sidebar-label">{item.label}</span>
            {!open && <Badge count={groupCount} collapsed={false} />}
            <span className="sidebar-chevron">
              {open
                ? <ChevronDown size={13} strokeWidth={2.5} />
                : <ChevronRight size={13} strokeWidth={2.5} />}
            </span>
          </>
        )}
      </button>
      {open && !collapsed && (
        <div className="sidebar-children">
          {item.children.map((child) => {
            const active = child.href ? isActivePath(pathname, child.href) : false;
            const count = navBadgeCount(child, badges);
            const ChildIcon = child.LucideIcon;
            return (
              <Link
                key={child.href}
                href={child.href!}
                className={`sidebar-item sidebar-child${active ? " active" : ""}`}
              >
                <span className="sidebar-icon">
                  {ChildIcon && <ChildIcon size={13} strokeWidth={2.2} />}
                </span>
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
          {collapsed
            ? <ChevronRight size={13} strokeWidth={2.8} />
            : <ChevronRight size={13} strokeWidth={2.8} style={{ transform: "rotate(180deg)" }} />}
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
        {role === "student" && (
          <Link href="/student/settings" className="sidebar-footer-link" title="偏好设置">
            <Settings size={14} strokeWidth={2} />
          </Link>
        )}
        <button className="sidebar-logout" onClick={handleLogout} title="退出登录">
          <LogOut size={14} strokeWidth={2} />
        </button>
      </div>
    </aside>
  );
}

type MobileNavItem = { href: string; LucideIcon: React.ElementType; label: string; badgeKey?: string; badgeKeys?: string[] };

const STUDENT_MOBILE_NAV: MobileNavItem[] = [
  { href: "/student", LucideIcon: Home, label: "首页" },
  { href: "/student/assistant", LucideIcon: HelpCircle, label: "随问" },
  { href: "/student/auto-tutor", LucideIcon: Bot, label: "辅导" },
  { href: "/student/review", LucideIcon: RotateCcw, label: "复习", badgeKey: "pending_review" },
];
const STUDENT_MORE_NAV: MobileNavItem[] = [
  { href: "/student/assignments", LucideIcon: ClipboardList, label: "作业", badgeKey: "pending_assignments" },
  { href: "/student/materials", LucideIcon: Library, label: "学习资料" },
  { href: "/student/materials?tab=textbook", LucideIcon: BookOpen, label: "教材目录" },
  { href: "/student/history/chat", LucideIcon: MessageSquare, label: "历史对话" },
  { href: "/student/history/games", LucideIcon: Gamepad2, label: "历史游戏" },
  { href: "/student/review?tab=weakpoints", LucideIcon: BrainCircuit, label: "错题库" },
  { href: "/student/quiz", LucideIcon: BrainCircuit, label: "智能练习" },
  { href: "/student/dashboard", LucideIcon: BarChart3, label: "学情总览" },
  { href: "/student/dashboard?tab=report", LucideIcon: TrendingUp, label: "成长报告" },
  { href: "/student/memory", LucideIcon: Sparkles, label: "记忆中心" },
  { href: "/student/settings", LucideIcon: Settings, label: "偏好设置" },
];

const TEACHER_MOBILE_NAV: MobileNavItem[] = [
  { href: "/teacher", LucideIcon: LayoutDashboard, label: "总览" },
  { href: "/teacher/assignments", LucideIcon: ClipboardList, label: "作业", badgeKeys: ["pending_review", "blind_spots_to_review"] },
  { href: "/teacher/grading", LucideIcon: Pencil, label: "批改" },
  { href: "/teacher/class-analytics", LucideIcon: TrendingUp, label: "学情" },
];
const TEACHER_MORE_NAV: MobileNavItem[] = [
  { href: "/teacher/quality-dashboard", LucideIcon: Star, label: "命题质量" },
  { href: "/teacher/materials", LucideIcon: Database, label: "资料生成" },
  { href: "/teacher/resources", LucideIcon: Library, label: "资源库" },
];

function badgeOf(badges: Badges, item: { badgeKey?: string; badgeKeys?: string[] }): number {
  let n = item.badgeKey ? (badges[item.badgeKey] || 0) : 0;
  if (item.badgeKeys) {
    for (const k of item.badgeKeys) n += badges[k] || 0;
  }
  return n;
}

function MobileBottomNavInner({ role }: { role: "student" | "teacher" }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const currentSearch = searchParams.toString();
  const { user } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [badges, setBadges] = useState<Badges>({});
  const items = role === "teacher" ? TEACHER_MOBILE_NAV : STUDENT_MOBILE_NAV;
  const moreItems = role === "teacher" ? TEACHER_MORE_NAV : STUDENT_MORE_NAV;
  const allItems = [...items, ...moreItems];

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
  const activeMoreItem = moreItems.find((item) => isPreciseMobileActive(pathname, item.href, currentSearch, allItems));

  return (
    <>
      {menuOpen && (
        <div className="mbn-overlay" onClick={() => setMenuOpen(false)}>
          <div className="mbn-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="mbn-drawer-header">
              <span>{role === "teacher" ? "教师工具箱" : "学习工具箱"}</span>
              <button type="button" onClick={() => setMenuOpen(false)} aria-label="关闭更多菜单">×</button>
            </div>
            <div className="mbn-drawer-grid">
              {allItems.map((item) => {
                const active = isPreciseMobileActive(pathname, item.href, currentSearch, allItems);
                const count = badgeOf(badges, item);
                const ItemIcon = item.LucideIcon;
                return (
                  <Link key={item.href} href={item.href} className={`mbn-drawer-item${active ? " active" : ""}`} onClick={() => setMenuOpen(false)}>
                    <span className="mbn-icon">
                      <ItemIcon size={18} strokeWidth={2} />
                      {count > 0 && <span className="sidebar-badge-dot" />}
                    </span>
                    <span className="mbn-label">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        </div>
      )}
      <nav className="mobile-bottom-nav" aria-label="移动端导航">
        {items.map((item) => {
          const active = isPreciseMobileActive(pathname, item.href, currentSearch, allItems);
          const count = badgeOf(badges, item);
          const ItemIcon = item.LucideIcon;
          return (
            <Link key={item.href} href={item.href} className={`mbn-item${active ? " active" : ""}`}>
              <span className="mbn-icon">
                <ItemIcon size={20} strokeWidth={active ? 2.5 : 1.8} />
                {count > 0 && <span className="sidebar-badge-dot" />}
              </span>
              <span className="mbn-label">{item.label}</span>
            </Link>
          );
        })}
        <button type="button" className={`mbn-item${activeMoreItem ? " active" : ""}`} onClick={() => setMenuOpen(true)} aria-expanded={menuOpen}>
          <span className="mbn-icon">
            <Layers size={20} strokeWidth={activeMoreItem ? 2.5 : 1.8} />
            {moreCount > 0 && <span className="sidebar-badge-dot" />}
          </span>
          <span className="mbn-label">{activeMoreItem?.label || "更多"}</span>
        </button>
      </nav>
    </>
  );
}

export function MobileBottomNav({ role }: { role: "student" | "teacher" }) {
  return (
    <Suspense fallback={null}>
      <MobileBottomNavInner role={role} />
    </Suspense>
  );
}
