import { Suspense } from "react";
import { TextbookGrid, TextbookGridSkeleton, TextbookHero } from "./parts";

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
