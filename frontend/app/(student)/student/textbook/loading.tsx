import { TextbookGridSkeleton, TextbookHero } from "@/app/textbook-learning/parts";

export default function Loading() {
  return (
    <main className="academy-shell textbook-learning-shell">
      <TextbookHero />
      <TextbookGridSkeleton />
    </main>
  );
}
