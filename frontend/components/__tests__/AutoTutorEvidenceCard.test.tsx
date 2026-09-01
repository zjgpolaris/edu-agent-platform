import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AutoTutorEvidenceCard, type AutoTutorEvidence } from "../AutoTutorEvidenceCard";

describe("AutoTutorEvidenceCard", () => {
  it("展示会话级反思、退出票和验证掌握证据", () => {
    const data: AutoTutorEvidence = {
      session_id: "at_demo",
      student_id: "pilot-student",
      status: "completed",
      knowledge_points: ["洋务运动目的"],
      replans: 1,
      reflection_count: 1,
      exit_ticket: { recorded: true, knowledge_point: "洋务运动目的", passed: true },
      mastery: { status: "verified" },
      evidence: { learning_event_recorded: true, weakpoint_action: "verified_correct_evidence_recorded", tutor_effectiveness_ready: true },
    };
    render(<AutoTutorEvidenceCard data={data} />);
    expect(screen.getByText("at_demo", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("1 / 1")).toBeInTheDocument();
    expect(screen.getByText("通过")).toBeInTheDocument();
    expect(screen.getByText("已验证")).toBeInTheDocument();
  });
});
