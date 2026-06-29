# UX 重排布开发文档

**文档编号**: 202606171923  
**状态**: 草稿  
**日期**: 2026-06-17  

---

## 1. 背景与目标

### 现有问题

| 问题 | 影响 |
|------|------|
| 三层导航跳转（首页→角色首页→功能）| 用户路径长，首次使用困难 |
| 无持久化侧边栏，模块间切换需返回首页 | 操作效率低 |
| 历史模块碎片化（5个独立入口）| 功能发现率低 |
| 作文批改分散在4个页面 | 教师批改流程断裂 |
| 学生首页8+模块无优先级 | 信息过载，聚焦困难 |

### 目标

1. 引入持久左侧导航，消除二级首页层级
2. 历史模块统一到 `/history` 子导航中心
3. 教师批改工作台合并为单页 tabs
4. 学生主页改为任务驱动的仪表盘

---

## 2. 路由结构变更

### 变更前

```
/                        # 落地页（含功能演示）
/student-home            # 学生首页（8个模块卡片）
/teacher-home            # 教师首页（6个模块卡片）
/teacher/dashboard       # 教师班级总览（独立页面）
/history-character       # 历史人物对话
/history-debate          # 历史辩论
/history-games           # 历史游戏大厅
/history-map             # 历史地图
/essay-grading           # 作文批改
/essay-grade             # 作文评分
/essay-dashboard         # 作文仪表板
```

### 变更后

```
/                        # 简化落地页（仅品牌+登录入口）
/login                   # 登录（不变）
/register                # 注册（不变）

# 学生端（带侧边栏 shell）
/student                 # 学生今日仪表盘（替代 /student-home）
/student/textbook        # 教材同步学习
/student/materials       # 资料上传学习
/student/assistant       # 统一学习助手
/student/history         # 历史探索中心（新增子导航页）
/student/history/chat    # 历史人物对话（原 /history-character）
/student/history/debate  # 历史辩论（原 /history-debate）
/student/history/games   # 历史游戏（原 /history-games/*）
/student/history/map     # 历史地图（原 /history-map）
/student/quiz            # 智能练习
/student/dashboard       # 学情分析
/student/memory          # 学习记忆中心

# 教师端（带侧边栏 shell）
/teacher                 # 班级总览仪表盘（合并 /teacher-home + /teacher/dashboard）
/teacher/grading         # 批改工作台（合并4个批改页面，tab切换）
/teacher/materials       # 资料生成工作台
/teacher/resources       # 教学资源库
/teacher/students/[id]   # 学生详情（不变）
```

> **兼容策略**：原有路径（`/history-character`, `/student-home` 等）保留并 redirect 到新路径，避免书签失效。

---

## 3. 新增组件规格

### 3.1 全局侧边栏 `AppSidebar`

**文件路径**: `frontend/app/components/AppSidebar.tsx`

**功能**:
- 根据 `useAuth()` 中的角色（student / teacher）渲染不同导航组
- 当前路径高亮对应菜单项（`usePathname()`）
- 支持收起/展开（宽度 240px ↔ 64px），状态存 `localStorage`
- 移动端折叠为顶部 hamburger 菜单

**导航数据结构**:
```ts
type NavItem = {
  label: string
  href: string
  icon: string          // lucide icon name
  badge?: number        // 未读/待处理数量
  children?: NavItem[]  // 二级菜单（仅历史探索使用）
}
```

**学生端导航配置**:
```ts
const studentNav: NavItem[] = [
  { label: '今日学习', href: '/student', icon: 'Home' },
  {
    label: '学习中心', icon: 'BookOpen', children: [
      { label: '教材同步', href: '/student/textbook', icon: 'Book' },
      { label: '资料学习', href: '/student/materials', icon: 'FileText' },
      { label: '学习助手', href: '/student/assistant', icon: 'MessageCircle' },
    ]
  },
  {
    label: '历史探索', icon: 'Landmark', children: [
      { label: '人物对话馆', href: '/student/history/chat', icon: 'Users' },
      { label: '历史辩论场', href: '/student/history/debate', icon: 'Swords' },
      { label: '历史游戏厅', href: '/student/history/games', icon: 'Gamepad2' },
      { label: '历史地图', href: '/student/history/map', icon: 'Map' },
    ]
  },
  {
    label: '我的学情', icon: 'BarChart2', children: [
      { label: '学情分析', href: '/student/dashboard', icon: 'TrendingUp' },
      { label: '智能练习', href: '/student/quiz', icon: 'ClipboardList' },
      { label: '记忆中心', href: '/student/memory', icon: 'Brain' },
    ]
  },
]
```

**教师端导航配置**:
```ts
const teacherNav: NavItem[] = [
  { label: '班级总览', href: '/teacher', icon: 'LayoutDashboard' },
  {
    label: '批改工作台', icon: 'PenLine', children: [
      { label: '作文批改', href: '/teacher/grading?tab=essay', icon: 'FileEdit' },
      { label: '拍照批改', href: '/teacher/grading?tab=homework', icon: 'Camera' },
    ]
  },
  {
    label: '教学备课', icon: 'FolderOpen', children: [
      { label: '资料生成', href: '/teacher/materials', icon: 'Wand2' },
      { label: '资源库', href: '/teacher/resources', icon: 'Archive' },
    ]
  },
]
```

---

### 3.2 Shell 布局 `(student)/layout.tsx` 和 `(teacher)/layout.tsx`

**文件路径**:
- `frontend/app/(student)/layout.tsx`
- `frontend/app/(teacher)/layout.tsx`

使用 Next.js 路由组（Route Groups）分隔角色，不影响 URL。

```tsx
// (student)/layout.tsx
export default function StudentLayout({ children }) {
  return (
    <div className="app-shell">
      <AppSidebar role="student" />
      <main className="app-main">{children}</main>
    </div>
  )
}
```

**CSS（globals.css 追加）**:
```css
.app-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.app-main {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}
```

---

### 3.3 历史探索中心 `/student/history/page.tsx`

新增的子导航门户页，4个子模块卡片 + 当前学习进度。

**布局**: 2×2 卡片网格，每张卡片含：模块名、简介、已解锁内容数（或 badge）、进入按钮。

---

### 3.4 批改工作台合并 `/teacher/grading/page.tsx`

将 `essay-grading`、`essay-grade`、`essay-dashboard`、`homework-grading` 合并为单页 tabs。

**Tab 结构**:
```
[待批改] [已批改] [统计分析]
```
- URL 通过 `?tab=pending|done|stats` 区分，支持直链
- 原有独立页面通过 redirect 指向对应 tab

---

## 4. 落地页简化 `/page.tsx`

**改动**: 移除功能演示区块（工作台演示、模块卡片网格），保留：
- 品牌 Logo + 一句话描述
- "学生登录" / "教师登录" 两个按钮（直接跳 `/login?role=student` / `/login?role=teacher`）
- 已登录用户自动 redirect 到 `/student` 或 `/teacher`

---

## 5. 实施任务

### P0 - 骨架（必须先完成）

- [ ] 新增 `AppSidebar` 组件
- [ ] 新增 `(student)/layout.tsx` 和 `(teacher)/layout.tsx` 路由组
- [ ] 将 `/student-home` 迁移为 `/student`（今日任务仪表盘）
- [ ] 将 `/teacher-home` + `/teacher/dashboard` 合并为 `/teacher`
- [ ] 添加旧路径 redirects（`next.config.js` 的 `redirects`）

### P1 - 历史模块整合

- [ ] 新增 `/student/history` 子导航门户页
- [ ] 移动 `history-character`、`history-debate`、`history-games`、`history-map` 到 `(student)/history/` 下
- [ ] 更新各历史页面内部的"返回"链接

### P2 - 批改工作台

- [ ] 新增 `/teacher/grading` 合并页（tabs）
- [ ] 拆解 `essay-grading`/`essay-grade`/`essay-dashboard` 内容到对应 tab
- [ ] 添加旧批改页 redirects

### P3 - 落地页清理

- [ ] 简化 `/page.tsx`，移除功能演示区
- [ ] 登录后自动 redirect 逻辑（在 `AuthGuard` 中根据角色跳转）

---

## 6. 不变的内容

以下页面**路由和实现均不改动**，仅更新其内部导航链接：

- `history-character/page.tsx` 内部功能（SSE 流式对话、RAG、fact card）
- `history-games/*`（时间线、卡牌、多人游戏逻辑）
- `materials/` 和 `material-upload/`（资料上传 Level 1 已验证）
- `textbook-learning/**`（书→单元→课文完整流程）
- `quiz-practice/`、`memory/`、`student-dashboard/`
- 登录注册流程

---

## 7. 文件变更清单

| 操作 | 文件 |
|------|------|
| 新增 | `frontend/app/components/AppSidebar.tsx` |
| 新增 | `frontend/app/(student)/layout.tsx` |
| 新增 | `frontend/app/(teacher)/layout.tsx` |
| 新增 | `frontend/app/(student)/history/page.tsx` |
| 新增 | `frontend/app/(teacher)/grading/page.tsx` |
| 修改 | `frontend/app/page.tsx`（简化）|
| 修改 | `frontend/app/layout.tsx`（移除 GlobalHeader 顶部导航）|
| 修改 | `frontend/app/globals.css`（追加 `.app-shell` 样式）|
| 修改 | `frontend/next.config.js`（添加 redirects）|
| 迁移 | `student-home/` → `(student)/` |
| 迁移 | `teacher-home/` + `teacher/dashboard/` → `(teacher)/` |
