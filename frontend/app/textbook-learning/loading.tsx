import { TextbookGridSkeleton, TextbookHero } from "./parts";

export default function Loading() {
  return (
    <main className="academy-shell textbook-learning-shell">
      <TextbookHero />
      <TextbookGridSkeleton />
    </main>
  );
}
