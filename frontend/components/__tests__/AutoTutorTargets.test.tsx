import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AutoTutorTargets } from "../AutoTutorTargets";
const response = (label = "洋务运动目的") => new Response(JSON.stringify({ items: [
  { objective_id: "western", label, grade: "八年级上册", launchable: true },
  { objective_id: "missing", label: "待补充目标", grade: "七年级上册", launchable: false },
] }), { status: 200 });
describe("AutoTutorTargets", () => {
  afterEach(() => vi.restoreAllMocks());
  it("shows grades and prevents duplicate intentions", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response());
    const select = vi.fn(() => true);
    render(<AutoTutorTargets apiBase="" token="token" disabled={false} onSelect={select} />);
    const button = await screen.findByRole("button", { name: /洋务运动目的.*八年级上册/ });
    expect(screen.getByRole("button", { name: /待补充目标/ })).toBeDisabled();
    fireEvent.click(button); fireEvent.click(button);
    expect(select).toHaveBeenCalledTimes(1);
  });
  it("blocks selection while a mutation is unresolved", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response());
    const select = vi.fn(() => true);
    render(<AutoTutorTargets apiBase="" token="token" disabled onSelect={select} />);
    const button = await screen.findByRole("button", { name: /洋务运动目的/ });
    fireEvent.click(button);
    expect(button).toBeDisabled(); expect(select).not.toHaveBeenCalled();
  });
  it("offers manual retry after a directory failure", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(response());
    render(<AutoTutorTargets apiBase="" token="token" disabled={false} onSelect={() => true} />);
    fireEvent.click(await screen.findByRole("button", { name: "重试目标目录" }));
    expect(await screen.findByRole("button", { name: /洋务运动目的/ })).toBeEnabled();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("aborts stale requests and ignores their responses", async () => {
    let finish!: (value: Response) => void;
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockResolvedValueOnce(response("当前目标"));
    const view = render(<AutoTutorTargets apiBase="" token="old" disabled={false} onSelect={() => true} />);
    const signal = fetcher.mock.calls[0][1]?.signal;
    view.rerender(<AutoTutorTargets apiBase="" token="new" disabled={false} onSelect={() => true} />);
    expect(await screen.findByRole("button", { name: /当前目标/ })).toBeInTheDocument();
    expect(signal?.aborted).toBe(true);
    await act(async () => { finish(response("过期目标")); });
    expect(screen.queryByText(/过期目标/)).not.toBeInTheDocument();
  });
});
