# 页面结构与角色分离优化方案

## 文档信息
- 创建时间: 2026-06-11
- 目标: 优化前端页面结构，实现学生端/教师端角色分离，统一视觉风格

## 当前问题分析

### 1. 页面结构混乱

#### 现状
首页（`/app/page.tsx`）平铺了 11 个功能模块，学生端和教师端功能混杂：

| 模块 | 路径 | 目标用户 | 状态 |
|------|------|----------|------|
| 统一学习助手 | `/learning-assistant` | 学生 | 混合 |
| 教材同步学习 | `/textbook-learning` | 学生 | 混合 |
| 教材章节导读 | `/textbook-guide` | 学生 | 混合 |
| 历史人物对话馆 | `/history-character` | 学生 | 混合 |
| 历史游戏大厅 | `/history-games` | 学生 | 混合 |
| 历史时空地图 | `/history-map` | 学生 | 混合 |
| 作文批改仪表板 | `/essay-dashboard` | 教师 | 混合 |
| 作文批改助手 | `/essay-grade` | 教师 | 混合 |
| 智能出题练习 | `/quiz-practice` | 学生 | 混合 |
| 历史辩论场 | `/history-debate` | 学生 | 混合 |
| 学情分析中心 | `/student-dashboard` | 学生 | 混合 |

#### 问题
- 功能过多导致首页信息过载
- 教师专用功能与学生功能并列，用户难以区分
- 缺少角色感知的入口设计

### 2. 导航设计问题

#### 现状
`GlobalHeader.tsx` 固定了 5 个导航链接：
```typescript
const NAV_LINKS = [
  { href: "/", label: "学习中心" },
  { href: "/history-character", label: "人物对话" },
  { href: "/history-games", label: "游戏大厅" },
  { href: "/textbook-learning", label: "教材同步" },
  { href: "/quiz-practice", label: "智能练习" },
];
```

#### 问题
- 教师端功能（作文批改、班级学情）不在导航中
- 没有根据 `user.role` 动态渲染导航
- 学生学情中心需要手动输入 ID，体验不流畅

### 3. 视觉风格不统一

#### 现状
- `globals.css` 有 6000+ 行，样式管理困难
- 不同页面使用不同的类名前缀：
  - 学生学情中心: `dv2-*`
  - 教师端: `tc-*`
  - 作文批改: `academy-shell`
  - 历史地图: 独立样式

#### 问题
- 视觉语言割裂，缺乏统一性
- 样式复用困难
- 维护成本高

### 4. 路由结构问题

#### 现状
```
/                    # 混合首页
/student-dashboard   # 学生学情（独立路径）
/teacher/dashboard   # 教师仪表板（独立路径）
/teacher/students/[id]  # 教师查看学生详情
```

#### 问题
- 没有统一的角色入口
- 路径语义不清晰
- 缺少角色权限的路由守卫

## 优化方案

### 1. 角色分离的首页结构

#### 目标结构
```
/                           # 根据角色重定向
├── /student-home          # 学生专属首页
│   ├── 教材同步学习
│   ├── 历史人物对话
│   ├── 历史游戏大厅
│   ├── 智能出题练习
│   ├── 学情分析中心
│   └── 学习助手
└── /teacher-home          # 教师专属首页
    ├── 班级学情总览
    ├── 学生学情详情
    ├── 作文批改仪表板
    └── 教学资源管理
```

#### 实施步骤
1. 创建 `/app/student-home/page.tsx`
2. 创建 `/app/teacher-home/page.tsx`
3. 修改 `/app/page.tsx` 为角色重定向页面
4. 将学生相关模块迁移到学生首页
5. 将教师相关模块迁移到教师首页

### 2. 统一导航栏设计

#### 目标
根据 `user.role` 动态渲染导航链接

#### 学生端导航
```typescript
const STUDENT_NAV_LINKS = [
  { href: "/student-home", label: "学习中心" },
  { href: "/textbook-learning", label: "教材同步" },
  { href: "/history-character", label: "人物对话" },
  { href: "/history-games", label: "游戏大厅" },
  { href: "/quiz-practice", label: "智能练习" },
  { href: "/student-dashboard", label: "学情分析" },
];
```

#### 教师端导航
```typescript
const TEACHER_NAV_LINKS = [
  { href: "/teacher-home", label: "班级管理" },
  { href: "/teacher/dashboard", label: "学情总览" },
  { href: "/essay-dashboard", label: "作文批改" },
  { href: "/textbook-learning", label: "教学资源" },
];
```

#### 实施步骤
1. 修改 `GlobalHeader.tsx` 添加角色判断
2. 创建角色专属导航配置
3. 添加导航激活状态逻辑

### 3. 样式系统重构

#### 目标
- 提取 Design Tokens
- 按模块组织样式文件
- 统一视觉语言

#### 现有 Design Tokens（已部分完成）
```css
:root {
  --paper: #f4ead5;
  --paper-soft: #fbf6ea;
  --ink: #241b16;
  --ink-soft: #66584b;
  --jade: #0f6b5f;
  --cinnabar: #b7422b;
  --gold: #b88b3e;
  --border: rgba(96, 72, 44, 0.2);
  --radius-lg: 28px;
  --radius-md: 20px;
  --radius-sm: 14px;
}
```

#### 实施步骤
1. 创建 `frontend/styles/tokens.css` - Design Tokens
2. 创建 `frontend/styles/components/` - 组件样式
3. 创建 `frontend/styles/layouts/` - 布局样式
4. 创建 `frontend/styles/pages/` - 页面样式
5. 逐步迁移 globals.css 中的样式

### 4. 面板展示优化

#### 学生学情面板优化
- 当前已有良好设计（`dv2-*` 类名）
- 建议增加：
  - 快捷入口：针对薄弱点推荐练习
  - 学习进度可视化
  - 与其他模块的联动（如点击薄弱点直接跳转到教材对应章节）

#### 教师班级面板优化
- 建议增加：
  - 学生筛选（按年级、班级）
  - 排序功能（按学情、活跃度）
  - 批量操作（批量查看学情、导出报告）
  - 班级整体学情统计图表

#### 作文批改面板优化
- 建议增加：
  - 批改进度追踪
  - 批改历史查看
  - 学生作文趋势分析

## 实施优先级

### 优先级高
1. 创建角色感知的首页（根据 AuthContext.role 重定向）
2. 重构 GlobalHeader，根据角色显示不同导航
3. 统一教师端和学生端的视觉风格

### 优先级中
1. 拆分 globals.css，按模块组织样式
2. 优化首页卡片布局，减少信息密度
3. 学情分析增加快捷操作入口

### 优先级低
1. 添加角色切换功能（测试用）
2. 增加个性化推荐入口
3. 优化移动端适配

## 技术债务

### 已知问题
1. `globals.css` 文件过大（6000+ 行）
2. 样式类名前缀不统一（`dv2-*`, `tc-*`, `academy-*`）
3. 部分页面使用内联样式（`jsx` style）
4. 缺少统一的组件库

### 建议
- 考虑引入 CSS-in-JS 方案（如 styled-components）或 CSS Modules
- 建立设计系统文档
- 创建可复用的 UI 组件库

## 相关文件

### 前端页面
- `/frontend/app/page.tsx` - 混合首页
- `/frontend/app/student-dashboard/page.tsx` - 学生学情
- `/frontend/app/teacher/dashboard/page.tsx` - 教师仪表板
- `/frontend/app/teacher/students/[id]/page.tsx` - 教师查看学生详情
- `/frontend/app/essay-dashboard/page.tsx` - 作文批改仪表板

### 组件
- `/frontend/components/GlobalHeader.tsx` - 全局导航
- `/frontend/contexts/AuthContext.tsx` - 认证上下文

### 样式
- `/frontend/app/globals.css` - 全局样式（6000+ 行）
- `/frontend/app/WeakpointCloud.tsx` - 薄弱点云图组件

## 后续跟进

- [x] 创建角色分离的首页
- [x] 重构 GlobalHeader
- [x] 统一视觉风格
- [ ] 拆分 globals.css（部分完成，添加了统一样式）
- [ ] 优化首页卡片布局
- [ ] 学情分析增加快捷操作入口
- [ ] 添加角色切换功能（测试用）
- [ ] 增加个性化推荐入口
- [ ] 优化移动端适配

## 已完成变更 (2026-06-11)

### 1. 角色分离的首页
- 创建 `/app/student-home/page.tsx` - 学生专属首页（9个学生模块）
- 创建 `/app/teacher-home/page.tsx` - 教师专属首页（4个教师模块）
- 修改 `/app/page.tsx` - 根据角色重定向到对应首页
- 添加加载状态样式

### 2. GlobalHeader 重构
- 添加角色动态导航配置（STUDENT_NAV_LINKS / TEACHER_NAV_LINKS）
- 学生端导航：学习中心、教材同步、人物对话、游戏大厅、智能练习、学情分析
- 教师端导航：班级管理、学情总览、作文批改、教学资源
- 添加角色徽章显示（学生/教师）
- 动态首页链接和标签

### 3. 视觉风格统一
- 在 globals.css 中添加统一的教师端样式（`teacher-*` 类名）
- 移除教师页面的内联样式，使用统一类名
- 重构 `/app/teacher/dashboard/page.tsx` 使用 `teacher-*` 类名
- 重构 `/app/teacher/students/[id]/page.tsx` 使用 `teacher-*` 类名
- 添加教师首页专属样式（`teacher-home-*` 类名）
- 添加角色徽章样式（`global-header-role-badge`）
