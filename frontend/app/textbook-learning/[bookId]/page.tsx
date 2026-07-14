type TocLesson = {
  id: string;
  title: string;
  item_count: number;
};

type TocUnit = {
  title: string;
  lessons: TocLesson[];
};

type TocResponse = {
  book_id: string;
  grade: string;
  book: string;
  status: "ready" | "empty" | "invalid";
  units: TocUnit[];
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function getToc(bookId: string): Promise<TocResponse | null> {
  try {
    const response = await fetch(`${apiBaseUrl}/api/textbooks/${bookId}/toc`, { cache: "no-store" });
    if (!response.ok) return null;
    return response.json();
  } catch {
    // 后端不可达时降级，避免整页 500。
    return null;
  }
}

export default async function TextbookTocPage(props: { params: Promise<{ bookId: string }> }) {
  const params = await props.params;
  const toc = await getToc(params.bookId);

  if (!toc) {
    return (
      <main className="academy-shell textbook-learning-shell">
        <section className="panel textbook-toc-page" aria-label="教材目录">
          <h1>教材目录暂时无法加载</h1>
          <p>无法连接教材服务，请稍后重试。</p>
          <a className="hero-game-link" href="/student/materials?tab=textbook">返回教材列表</a>
        </section>
      </main>
    );
  }

  return (
    <main className="academy-shell textbook-learning-shell">
      <section className="academy-hero textbook-hero compact-hero">
        <div className="hero-copy">
          <div className="eyebrow">{toc.grade} · 教材目录</div>
          <h1>{toc.book}</h1>
          <p>选择一课进入学习文档。页面中的知识点来自结构化教材同步材料，页码以“约第 X 页”提示。</p>
          <div className="hero-flow" aria-label="目录说明">
            <span>{toc.units.length} 个单元</span>
            <span>{toc.units.reduce((count, unit) => count + unit.lessons.length, 0)} 课</span>
            <span>知识点卡片</span>
          </div>
          <a className="hero-game-link" href="/student/materials?tab=textbook">返回教材列表</a>
        </div>
        <div className="teaching-card textbook-boundary-card" aria-label="学习建议">
          <div className="seal-mark" aria-hidden="true">目</div>
          <span className="card-label">学习建议</span>
          <strong>按课进入，边学边问</strong>
          <p>建议先浏览核心知识点，再使用 AI 助手生成摘要、自测题或针对单个知识点提问。</p>
        </div>
      </section>

      <section className="panel textbook-toc-page" aria-label="教材目录">
        {toc.units.map((unit, unitIndex) => (
          <section className="textbook-unit-block" key={unit.title}>
            <div className="textbook-unit-heading">
              <span>{String(unitIndex + 1).padStart(2, "0")}</span>
              <h2>{unit.title}</h2>
            </div>
            <div className="textbook-lesson-grid">
              {unit.lessons.map((lesson) => (
                <a className="textbook-lesson-card" href={`/textbook-learning/${toc.book_id}/${lesson.id}`} key={lesson.id}>
                  <strong>{lesson.title}</strong>
                  <span>{lesson.item_count} 条知识点</span>
                </a>
              ))}
            </div>
          </section>
        ))}
      </section>
    </main>
  );
}
