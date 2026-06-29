import { Suspense } from "react";
import { TextbookGrid, TextbookGridSkeleton, TextbookHero } from "./parts";

// 后端在 Render 免费实例上闲置会休眠，冷启动 30–50s。放宽 SSR 函数时长上限，
// 配合 getTextbooks 的超时重试，让冷启动期间进页面也能拿到教材而非报错。
export const maxDuration = 60;

export default function TextbookLearningPage() {
  return (
    <main className="academy-shell textbook-learning-shell">
      <TextbookHero />
      <Suspense fallback={<TextbookGridSkeleton />}>
        <TextbookGrid />
      </Suspense>
    </main>
  );
}
