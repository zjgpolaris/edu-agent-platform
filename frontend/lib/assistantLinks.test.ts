import { describe, expect, it } from "vitest";
import { buildKnowledgeReviewAssistantHref, buildKnowledgeReviewPrompt } from "./assistantLinks";

describe("knowledge review assistant link", () => {
  it("opens a fresh student assistant session with a targeted teaching prompt", () => {
    const href = buildKnowledgeReviewAssistantHref(" 洋务运动目的 ");
    const url = new URL(href, "http://localhost");

    expect(url.pathname).toBe("/student/assistant");
    expect(url.searchParams.get("new")).toBe("1");
    expect(url.searchParams.get("prompt")).toBe("请围绕知识点「洋务运动目的」讲解核心史实、原因、影响和易错点。");
  });

  it("keeps the selected knowledge point in the prompt", () => {
    expect(buildKnowledgeReviewPrompt("戊戌变法失败原因")).toContain("戊戌变法失败原因");
  });
});
