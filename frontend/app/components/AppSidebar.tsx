"use client";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type NavItem = {
  label: string;
  href?: string;
  icon: string;
  children?: NavItem[];
  badgeKey?: string;
  badgeKeys?: string[];
};

type Badges = Record<string, number>;

// 学生侧边栏：5 组，最多 6 子项/组
const studentNav: NavItem[] = [
  { label: "今日学习", href: "/student", icon: "⌂" },
  { label: "自主辅导", href: "/student/auto-tutor", icon: "辅" },
  {
    // 教材同步+资料库合并为"学习资源"，用 tab 切换；学习助手独立保留
    label: "学习资源", icon: "◎", children: [
      { label: "学习资料", href: "/student/materials", icon: "册" },
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
    // 作业→复习中心（今日任务+错题库 合并）→智能练习 闭环链路
    label: "练习复习", icon: "练", children: [
      { label: "我的作业", href: "/student/assignments", icon: "业", badgeKey: "pending_assignments" },
      { label: "复习中心", href: "/student/review", icon: "复", badgeKey: "pending_review" },
      { label: "智能练习", href: "/student/quiz", icon: "练" },
    ],
  },
  {
    // 学情速览+成长报告已合并到 dashboard（2 tabs），移除独立成长报告入口
    label: "我的成长", icon: "报", children: [
      { label: "学情总览", href: "/student/dashboard", icon: "析" },
      { label: "学习路径", href: "/student/learning-path", icon: "路" },
      { label: "记忆中心", href: "/student/memory", icon: "忆" },
      { label: "学习日历", href: "/student/calendar", icon: "历" },
      { label: "我的成就", href: "/student/achievements", icon: "奖" },
    ],
  },
];

// 教师侧边栏：系统运维→教学分析，Eval 移至 footer
const teacherNav: NavItem[] = [
  { label: "班级总览", href: "/teacher", icon: "班" },
  {
    label: "批改工作台", icon: "批", children: [
      { label: "布置作业", href: "/teacher/assignments", icon: "业", badgeKeys: ["pending_review", "blind_spots_to_review"] },
      { label: "作文批改", href: "/teacher/grading?tab=essay", icon: "文" },
      { label: "拍照批改", href: "/teacher/grading?tab=homework", icon: "拍" },
    ],
  },
  {
    // 班级学情/命题质量 是教学核心分析，不是"运维"
    label: "教学分析", icon: "析", children: [
      { label: "班级学情", href: "/teacher/class-analytics", icon: "析" },
      { label: "命题质量", href: "/teacher/quality-dashboard", icon: "质" },
    ],
  },
  {
    label: "教学备课", icon: "备", children: [
      { label: "资料生成", href: "/teacher/materials", icon: "生" },
      { label: "资源库", href: "/teacher/resources", icon: "库" },
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
  const isChildActive = item.children?.some(
    (c) => c.href && isActivePath(pathname, c.href)
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
    const active = item.href ? isActivePath(pathname, item.href) : false;
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
        type="button"
        className={`sidebar-item sidebar-group-btn${isChildActive ? " active" : ""}`}
        onClick={toggleGroup}
        title={collapsed ? item.label : undefined}
        aria-expanded={open}
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
            const active = child.href ? isActivePath(pathname, child.href) : false;
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
        {/* 偏好设置（学生）/ Eval Dashboard（教师）移至 footer，降低视觉权重 */}
        {role === "student" && (
          <Link href="/student/settings" className="sidebar-footer-link" title="偏好设置">⚙</Link>
        )}
        {role === "teacher" && (
          <Link href="/eval" className="sidebar-footer-link" title="Eval Dashboard">测</Link>
        )}
        <button className="sidebar-logout" onClick={handleLogout} title="退出登录">⏻</button>
      </div>
    </aside>
  );
}

type MobileNavItem = { href: string; icon: string; label: string; badgeKey?: string; badgeKeys?: string[] };

// 移动端主导航：4 个高频入口（首页/辅导/复习中心/作业）
const STUDENT_MOBILE_NAV: MobileNavItem[] = [
  { href: "/student", icon: "主", label: "首页" },
  { href: "/student/auto-tutor", icon: "辅", label: "辅导" },
  { href: "/student/review", icon: "复", label: "复习", badgeKey: "pending_review" },
  { href: "/student/assignments", icon: "业", label: "作业", badgeKey: "pending_assignments" },
];
// 更多抽屉：其余功能，错题库并入复习中心，教材并入学习资料
const STUDENT_MORE_NAV: MobileNavItem[] = [
  { href: "/student/assistant", icon: "问", label: "学习助手" },
  { href: "/student/materials", icon: "册", label: "学习资料" },
  { href: "/student/materials?tab=textbook", icon: "本", label: "教材目录" },
  { href: "/student/history/chat", icon: "人", label: "历史对话" },
  { href: "/student/history/games", icon: "弈", label: "历史游戏" },
  { href: "/student/review?tab=weakpoints", icon: "错", label: "错题库" },
  { href: "/student/quiz", icon: "练", label: "智能练习" },
  { href: "/student/dashboard", icon: "析", label: "学情总览" },
  { href: "/student/dashboard?tab=report", icon: "报", label: "成长报告" },
  { href: "/student/memory", icon: "忆", label: "记忆中心" },
  { href: "/student/settings", icon: "设", label: "偏好设置" },
];

// 教师移动端：4 项高频入口（总览/作业/批改/学情）
const TEACHER_MOBILE_NAV: MobileNavItem[] = [
  { href: "/teacher", icon: "班", label: "总览" },
  { href: "/teacher/assignments", icon: "业", label: "作业", badgeKeys: ["pending_review", "blind_spots_to_review"] },
  { href: "/teacher/grading", icon: "批", label: "批改" },
  { href: "/teacher/class-analytics", icon: "析", label: "学情" },
];
const TEACHER_MORE_NAV: MobileNavItem[] = [
  { href: "/teacher/quality-dashboard", icon: "质", label: "命题质量" },
  { href: "/teacher/materials", icon: "生", label: "资料生成" },
  { href: "/teacher/resources", icon: "库", label: "资源库" },
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
                return (
                  <Link key={item.href} href={item.href} className={`mbn-drawer-item${active ? " active" : ""}`} onClick={() => setMenuOpen(false)}>
                    <span className="mbn-icon">{item.icon}{count > 0 && <span className="sidebar-badge-dot" />}</span>
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
          return (
            <Link key={item.href} href={item.href} className={`mbn-item${active ? " active" : ""}`}>
              <span className="mbn-icon">{item.icon}{count > 0 && <span className="sidebar-badge-dot" />}</span>
              <span className="mbn-label">{item.label}</span>
            </Link>
          );
        })}
        <button type="button" className={`mbn-item${activeMoreItem ? " active" : ""}`} onClick={() => setMenuOpen(true)} aria-expanded={menuOpen}>
          <span className="mbn-icon">≡{moreCount > 0 && <span className="sidebar-badge-dot" />}</span>
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
