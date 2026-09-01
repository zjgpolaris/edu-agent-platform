import { describe, expect, it } from "vitest";
import { demoMoreDestinations, demoPrimaryDestinations } from "./demoNavigation";

describe("Demo navigation", () => {
  it.each(["student", "teacher"] as const)("%s 首屏入口不超过五个且更多能力仍可达", (role) => {
    const primary = demoPrimaryDestinations(role);
    const more = demoMoreDestinations(role);
    expect(primary.length).toBeGreaterThan(0);
    expect(primary.length).toBeLessThanOrEqual(5);
    expect(more.length).toBeGreaterThan(0);
    expect(new Set([...primary, ...more].map((item) => item.href)).size).toBe(primary.length + more.length);
  });
});
