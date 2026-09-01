import { describe, expect, it } from "vitest";
import { homeForRole } from "./auth";

describe("homeForRole", () => {
  it("routes every authenticated role to its own home", () => {
    expect(homeForRole("student")).toBe("/student");
    expect(homeForRole("teacher")).toBe("/teacher");
    expect(homeForRole("admin")).toBe("/eval");
  });
});
