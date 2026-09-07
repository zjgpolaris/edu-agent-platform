import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ReviewTab from "../../app/(student)/student/review/ReviewTab";

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { actorId: "pilot-student", token: "test-token" } }),
}));

afterEach(() => vi.restoreAllMocks());

describe("ReviewTab", () => {
  it("answers first, reveals feedback, then advances to an independent verification question", async () => {
    const feedbackMaterial = "某次改革只依靠少数上层人物，既没有可靠军队，也没有广泛社会支持。";
    const task = {
      question_id: "wuxu-cause-exit-1",
      tag: "戊戌变法失败原因",
      material_timing: "after_answer",
      question: "从政治力量基础看，戊戌变法失败最能说明下列哪一问题？",
      options: [
        "A. 改革力量薄弱，面对既得利益集团反击时难以坚持",
        "B. 改革一定会立即完成思想启蒙",
        "C. 改革措施越少越容易成功",
        "D. 只要皇帝支持，改革必然成功",
      ],
      difficulty: "medium",
      cognitive_action: "apply",
      is_variant: true,
      quality_status: "verified",
      adaptive_message: "这个知识点近期反复出错，先独立作答，再用对照材料检查理解。",
      done: false,
      correct: null,
      task_role: "retrieval",
      phase: "answering",
      feedback_acknowledged: false,
    };
    const verificationTask = {
      question_id: "wuxu-cause-practice-2",
      tag: "戊戌变法失败原因",
      question: "下列哪一项属于戊戌变法失败原因，而不是变法影响？",
      options: [
        "A. 维新派力量弱小",
        "B. 推动思想启蒙",
        "C. 促进社会进步",
        "D. 传播民主思想",
      ],
      difficulty: "medium",
      cognitive_action: "explain",
      is_variant: false,
      quality_status: "verified",
      done: false,
      correct: null,
      task_role: "verification",
      phase: "answering",
    };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({
        date: "2026-08-24", completed: 0, total: 1, session_revision: 0, tasks: [task], scheduled_reviews: [],
      })))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        completed: 1, total: 1, session_revision: 1, phase: "awaiting_feedback",
        is_correct: true,
        replayed: false,
        task: { ...task, material: feedbackMaterial, done: true, correct: true, answer: "A", explanation: "解析" },
      })))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        phase: "verification_pending", task_index: 1, session_revision: 2, task: verificationTask,
      })));

    render(<ReviewTab />);
    await waitFor(() => expect(screen.getByText(task.question)).toBeInTheDocument());
    expect(screen.getByText("先答后证")).toBeInTheDocument();
    expect(screen.queryByText(feedbackMaterial)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /改革力量薄弱/ }));
    fireEvent.click(screen.getByRole("button", { name: "确认答案" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const submitInit = fetchMock.mock.calls[1][1] as RequestInit;
    const payload = JSON.parse(String(submitInit.body));
    expect(payload).toMatchObject({ task_index: 0, selected_answer: "A", expected_revision: 0 });
    expect(payload.idempotency_key).toMatch(/^review-client-/);
    expect(payload).not.toHaveProperty("is_correct");
    const nextButton = await screen.findByRole("button", { name: "看完了，做一道验证题" });
    expect(screen.getByText(feedbackMaterial)).toBeInTheDocument();
    expect(screen.getAllByText("解析").length).toBeGreaterThan(0);

    fireEvent.click(nextButton);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const advanceInit = fetchMock.mock.calls[2][1] as RequestInit;
    expect(JSON.parse(String(advanceInit.body))).toMatchObject({
      task_index: 0,
      action: "continue_after_feedback",
      expected_revision: 1,
    });
    expect(await screen.findByText(verificationTask.question)).toBeInTheDocument();
    expect(screen.queryByText(feedbackMaterial)).not.toBeInTheDocument();
  });
});

it.each([false, true])("shows retention schedule and blocks even alongside other tasks: %s", async (done) => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    date: "2030-01-01", completed: done ? 1 : 0, total: 1, session_revision: 2,
    tasks: [{ question_id: "other", tag: "其他目标", question: "其他练习题", options: ["A. 一", "B. 二", "C. 三", "D. 四"], done, correct: done ? true : null, quality_status: "verified" }],
    scheduled_reviews: [{ knowledge_tag: "戊戌变法失败原因", available_at: "2030-01-02T03:00:00Z", message: "等待" }],
    blocked_reviews: [{ knowledge_tag: "洋务运动目的", available_at: "2030-01-01T03:00:00Z", reason_code: "independent_review_content_missing" }],
  })));
  render(<ReviewTab />);
  expect(await screen.findByLabelText("复测安排")).toHaveTextContent("等待间隔复测");
  expect(screen.getByLabelText("复测安排")).toHaveTextContent("延迟复测暂缺独立题");
});
