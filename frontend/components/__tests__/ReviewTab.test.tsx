import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ReviewTab from "../../app/(student)/student/review/ReviewTab";

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { actorId: "pilot-student", token: "test-token" } }),
}));

afterEach(() => vi.restoreAllMocks());

describe("ReviewTab", () => {
  it("reveals the feedback material only after the server judges the selected option", async () => {
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
    };
    const nextTask = {
      question_id: "westernization-purpose-practice-1",
      tag: "洋务运动目的",
      question: "洋务运动提出“自强”“求富”，其根本目的是什么？",
      options: [
        "A. 建立资产阶级共和国",
        "B. 维护和巩固清政府统治",
        "C. 推翻清朝封建统治",
        "D. 实现民族独立",
      ],
      difficulty: "easy",
      cognitive_action: "explain",
      is_variant: false,
      quality_status: "verified",
      done: false,
      correct: null,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ date: "2026-08-24", completed: 0, total: 2, tasks: [task, nextTask] })))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        completed: 1,
        total: 2,
        is_correct: true,
        replayed: false,
        task: { ...task, material: feedbackMaterial, done: true, correct: true, answer: "A", explanation: "解析" },
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
    expect(payload).toEqual({ task_index: 0, selected_answer: "A" });
    expect(payload).not.toHaveProperty("is_correct");
    const nextButton = await screen.findByRole("button", { name: "下一题 →" });
    expect(screen.getByText(feedbackMaterial)).toBeInTheDocument();
    expect(screen.getAllByText("解析").length).toBeGreaterThan(0);

    fireEvent.click(nextButton);
    expect(screen.getByText(nextTask.question)).toBeInTheDocument();
    expect(screen.queryByText(feedbackMaterial)).not.toBeInTheDocument();
  });
});
