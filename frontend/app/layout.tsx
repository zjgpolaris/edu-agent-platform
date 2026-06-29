import type { Metadata } from "next";
import { ZCOOL_XiaoWei, Noto_Serif_SC, Cormorant_Garamond } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/contexts/AuthContext";
import AuthGuard from "@/components/AuthGuard";

// 展示字体：用于标题、大号装饰文字
const zcoolXiaoWei = ZCOOL_XiaoWei({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

// 正文字体：中文衬线，正文阅读
const notoSerifSC = Noto_Serif_SC({
  weight: ["400", "700"],
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

// 西文装饰字体：数字、标签、英文标注
const cormorant = Cormorant_Garamond({
  weight: ["400", "500", "600", "700"],
  subsets: ["latin"],
  variable: "--font-accent",
  display: "swap",
});

export const metadata: Metadata = {
  title: "EduAgent",
  description: "面向历史与语文学科的 AI Agent 教学辅助平台",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="zh-CN"
      className={`${zcoolXiaoWei.variable} ${notoSerifSC.variable} ${cormorant.variable}`}
    >
      <body>
        <AuthProvider>
          <AuthGuard>{children}</AuthGuard>
        </AuthProvider>
      </body>
    </html>
  );
}
