import { describe, expect, it } from "vitest";
import { homeForRole, safeNextForRole } from "./auth";

describe("homeForRole", () => {
  it("routes every authenticated role to its own home", () => {
    expect(homeForRole("student")).toBe("/student");
    expect(homeForRole("teacher")).toBe("/teacher");
    expect(homeForRole("admin")).toBe("/eval");
  });

  it("只允许与角色匹配的站内 next 路径", () => {
    expect(safeNextForRole("/teacher/evidence?session_id=at_1", "teacher")).toBe("/teacher/evidence?session_id=at_1");
    expect(safeNextForRole("/student/auto-tutor?demo=1", "student")).toBe("/student/auto-tutor?demo=1");
    expect(safeNextForRole("https://evil.example/teacher", "teacher")).toBe("/teacher");
    expect(safeNextForRole("//evil.example/teacher", "teacher")).toBe("/teacher");
    expect(safeNextForRole("/student", "teacher")).toBe("/teacher");
    expect(safeNextForRole("/teacher", "student")).toBe("/student");
  });
});
