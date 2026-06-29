type Textbook = {
  id: string;
  grade: string;
  book: string;
  source: string;
  status: "ready" | "empty" | "invalid";
  unit_count: number;
  lesson_count: number;
  item_count: number;
  message?: string | null;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function getTextbooks(): Promise<Textbook[]> {
  const response = await fetch(`${apiBaseUrl}/api/textbooks`, { cache: "no-store" });
  if (!response.ok) throw new Error("教材列表加载失败");
  const data = (await response.json()) as { textbooks?: Textbook[] };
  return data.textbooks || [];
}

function statusLabel(status: Textbook["status"]) {
  if (status === "ready") return "可学习";
  if (status === "empty") return "待补全";
  return "需检查";
}

export default async function TextbookLearningPage() {
  const textbooks = await getTextbooks();

  return (
    <main className="academy-shell textbook-learning-shell">
      <section className="academy-hero textbook-hero">
        <div className="hero-copy">
          <div className="eyebrow">初中历史 · 教材同步学习</div>
          <h1>教材同步学习文档</h1>
          <p>按教材目录进入每一课，围绕结构化知识点进行解释、摘要、笔记和自测。当前内容是同步学习文档，不是 PDF 原文阅读器。</p>
          <div className="hero-flow" aria-label="学习流程">
            <span>选教材</span>
            <span>看目录</span>
            <span>学知识点</span>
            <span>问 AI</span>
          </div>
        </div>
        <div className="teaching-card textbook-boundary-card" aria-label="教材同步说明">
          <div className="seal-mark" aria-hidden="true">课</div>
          <span className="card-label">学习边界</span>
          <strong>先学习文档，后接原文页</strong>
          <p>本期以 YAML 结构化知识点为核心，帮助学生按课理解、复习和练习；OCR 原文页模式会在后续版本接入。</p>
        </div>
      </section>

      <section className="textbook-book-grid" aria-label="教材列表">
        {textbooks.map((textbook) => {
          const ready = textbook.status === "ready";
          const CardEl = ready ? "a" : "div";
          const cardProps = ready
            ? { href: `/textbook-learning/${textbook.id}` }
            : { title: textbook.status === "empty" ? "内容补全中，暂不可学习" : "内容需要检查，暂不可学习" };
          return (
            <CardEl
              className={`textbook-book-card ${ready ? "ready" : "disabled"}`}
              key={textbook.id}
              {...(cardProps as unknown as Record<string, string>)}
            >
              <div className="portal-card-topline">
                <span>{textbook.grade || "未标注年级"}</span>
                <em>{statusLabel(textbook.status)}</em>
              </div>
              <div className="textbook-book-seal" aria-hidden="true">史</div>
              <h2>{textbook.book}</h2>
              <p>{textbook.message || "按单元和课次组织知识点，可进入目录开始学习。"}</p>
              <div className="textbook-stat-row">
                <span>{textbook.unit_count} 个单元</span>
                <span>{textbook.lesson_count} 课</span>
                <span>{textbook.item_count} 条知识点</span>
              </div>
              <div className="portal-module-action">{ready ? "查看目录" : "暂不可用"}</div>
            </CardEl>
          );
        })}
      </section>
    </main>
  );
}
