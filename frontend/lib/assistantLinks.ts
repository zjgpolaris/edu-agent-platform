export function buildKnowledgeReviewPrompt(topic: string): string {
  return `请围绕知识点「${topic.trim()}」讲解核心史实、原因、影响和易错点。`;
}

export function buildKnowledgeReviewAssistantHref(topic: string): string {
  const params = new URLSearchParams({
    new: "1",
    prompt: buildKnowledgeReviewPrompt(topic),
  });
  return `/student/assistant?${params.toString()}`;
}
