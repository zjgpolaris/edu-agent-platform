// 教材同步页的拆分部件：静态 hero 立即渲染，数据网格走 Suspense 流式加载。

export type Textbook = {
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

async function getTextbooks(): Promise<{ textbooks: Textbook[]; error: boolean }> {
  // Render 免费实例闲置会休眠，冷启动需 30–50s，单次 fetch 易超时。
  // 多次尝试：首个请求即便超时被 abort，也已触发后端唤醒，重试时通常已就绪。
  // 配合 page.tsx 的 maxDuration=60，总耗时控制在函数时长上限内。
  const attempts = 2;
  const perAttemptTimeoutMs = 25000;
  for (let i = 0; i < attempts; i++) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), perAttemptTimeoutMs);
      let response: Response;
      try {
        response = await fetch(`${apiBaseUrl}/api/textbooks`, {
          cache: "no-store",
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timer);
      }
      if (!response.ok) {
        // 5xx / 网关错误多为冷启动中途，重试；4xx 是确定性错误，直接降级。
        if (response.status >= 500 && i < attempts - 1) {
          await new Promise((resolve) => setTimeout(resolve, 2000));
          continue;
        }
        return { textbooks: [], error: true };
      }
      const data = (await response.json()) as { textbooks?: Textbook[] };
      return { textbooks: data.textbooks || [], error: false };
    } catch {
      // 超时 / 网络错误：还有机会就退避后重试，否则降级避免整页 500。
      if (i < attempts - 1) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        continue;
      }
      return { textbooks: [], error: true };
    }
  }
  return { textbooks: [], error: true };
}

function statusLabel(status: Textbook["status"]) {
  if (status === "ready") return "可学习";
  if (status === "empty") return "待补全";
  return "需检查";
}

// 静态英雄区，不依赖后端数据，可立即渲染。
export function TextbookHero() {
  return (
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
  );
}

// 数据加载时的骨架占位，结构与真实网格一致，避免布局抖动。
export function TextbookGridSkeleton() {
  return (
    <section className="textbook-book-grid" aria-label="教材列表加载中" aria-busy="true">
      {Array.from({ length: 3 }).map((_, index) => (
        <div className="textbook-book-card skeleton-card" key={index} aria-hidden="true">
          <div className="portal-card-topline">
            <span className="skeleton" style={{ width: 72, height: 14 }} />
            <span className="skeleton" style={{ width: 40, height: 14 }} />
          </div>
          <div className="skeleton" style={{ width: 44, height: 44, borderRadius: 12, marginTop: 8 }} />
          <div className="skeleton" style={{ width: "60%", height: 24, marginTop: 14 }} />
          <div className="skeleton" style={{ width: "100%", height: 14, marginTop: 14 }} />
          <div className="skeleton" style={{ width: "85%", height: 14, marginTop: 8 }} />
          <div className="skeleton" style={{ width: "70%", height: 14, marginTop: 18 }} />
        </div>
      ))}
    </section>
  );
}

// 真正访问后端并渲染教材卡片的异步组件，被 <Suspense> 包裹后可流式输出。
export async function TextbookGrid() {
  const { textbooks, error } = await getTextbooks();

  if (error) {
    return (
      <section className="textbook-book-grid" aria-label="教材列表">
        <div className="textbook-book-card disabled" aria-live="polite">
          <h2>教材服务暂时无法连接</h2>
          <p>无法加载教材列表，请稍后重试。如果问题持续，可能是后端服务未就绪。</p>
        </div>
      </section>
    );
  }

  if (textbooks.length === 0) {
    return (
      <section className="textbook-book-grid" aria-label="教材列表">
        <div className="textbook-book-card disabled">
          <h2>暂无可学习的教材</h2>
          <p>教材内容正在补全中，敬请期待。</p>
        </div>
      </section>
    );
  }

  return (
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
  );
}
