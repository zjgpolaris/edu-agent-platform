import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/contexts/AuthContext";
import AuthGuard from "@/components/AuthGuard";

export const metadata: Metadata = {
  title: "EduAgent",
  description: "面向历史与语文学科的 AI Agent 教学辅助平台",
};

// 字体改用国内可达的 Google Fonts 镜像（浏览器端按需加载，display=swap 不阻塞渲染）。
// 之前用 next/font/google 会在构建/编译期从 fonts.gstatic.com 拉取字体文件，
// 国内不可达导致超时阻塞，表现为页面进入缓慢；改为镜像 <link> + 系统字体回退后即可消除。
const FONTS_CSS =
  "https://fonts.loli.net/css2?family=ZCOOL+XiaoWei&family=Noto+Serif+SC:wght@400;700&family=Cormorant+Garamond:wght@400;500;600;700&display=swap";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" data-scroll-behavior="smooth">
      <head>
        <link rel="preconnect" href="https://fonts.loli.net" />
        <link rel="preconnect" href="https://gstatic.loli.net" crossOrigin="anonymous" />
        <link rel="stylesheet" href={FONTS_CSS} />
      </head>
      <body>
        <AuthProvider>
          <AuthGuard>{children}</AuthGuard>
        </AuthProvider>
      </body>
    </html>
  );
}
