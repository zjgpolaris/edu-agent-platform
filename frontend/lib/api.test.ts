import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, ApiTransportError, apiErrorMessage, fetchApiJson } from "./api";

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });
describe("bounded requests", () => {
  it.each([401, 403, 409, 429, 503])("classifies HTTP %s without retries", async status => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response('{}', { status }));
    await expect(fetchApiJson("/test", { method: "POST", body: {}, timeoutMs: 100 })).rejects.toBeInstanceOf(ApiError);
    expect(fetch).toHaveBeenCalledTimes(1);
    if (status === 503) expect(apiErrorMessage(new ApiError("", status, {}, new Response()))).not.toContain("密码");
  });
  it("aborts on deadline and cleans caller listener", async () => {
    vi.useFakeTimers();
    const caller = new AbortController();
    const cleanup = vi.spyOn(caller.signal, "removeEventListener");
    vi.spyOn(globalThis, "fetch").mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));
    const request = fetchApiJson("/test", { timeoutMs: 20, signal: caller.signal });
    const assertion = expect(request).rejects.toMatchObject({ kind: "timeout" });
    await vi.advanceTimersByTimeAsync(21);
    await assertion;
    expect(cleanup).toHaveBeenCalled();
  });
  it("does not claim cancellation rolls back a mutation", async () => {
    const caller = new AbortController();
    vi.spyOn(globalThis, "fetch").mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));
    const request = fetchApiJson("/test", { method: "POST", signal: caller.signal, timeoutMs: 100 });
    caller.abort();
    await expect(request).rejects.toMatchObject({ kind: "cancelled" });
  });
  it("classifies network loss", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(fetchApiJson("/test", { timeoutMs: 100 })).rejects.toBeInstanceOf(ApiTransportError);
  });
  it("preserves native abort for existing callers without timeout opt-in", async () => {
    const error = new DOMException("aborted", "AbortError");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(error);
    await expect(fetchApiJson("/test")).rejects.toBe(error);
  });
});
