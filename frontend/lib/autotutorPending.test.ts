import { beforeEach, expect, it, vi } from "vitest";
import { clearAllPending, pendingKey, readPending, savePending } from "./autotutorPending";
beforeEach(() => { sessionStorage.clear(); vi.restoreAllMocks(); });
it("preserves one intent across reload reads and isolates actors", () => {
  const pending = { version: 1 as const, kind: "start" as const, key: pendingKey(), actor: "a", createdAt: Date.now(), focus: "洋务运动目的" };
  savePending(pending);
  expect(readPending("a")).toEqual(pending);
  expect(readPending("b")).toBeNull();
  expect(readPending("a")?.key).toBe(pending.key);
  expect(pendingKey()).not.toBe(pending.key);
  clearAllPending(); expect(readPending("a")).toBeNull();
});
it("expires pending data and fails before mutation if storage is blocked", () => {
  savePending({ version: 1, kind: "answer", key: pendingKey(), actor: "a", createdAt: Date.now()-3_600_001, sessionId: "s", revision: 1, answer: "A" });
  expect(readPending("a")).toBeNull();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
  expect(() => savePending({ version: 1, kind: "start", key: pendingKey(), actor: "a", createdAt: Date.now(), focus: null })).toThrow();
});
