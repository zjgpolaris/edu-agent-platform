"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ReactNode } from "react";

export type TabShellItem<T extends string> = {
  value: T;
  label: string;
  badge?: number | string;
  render: ReactNode;
};

type TabShellProps<T extends string> = {
  tabs: TabShellItem<T>[];
  defaultTab: T;
  ariaLabel: string;
};

export default function TabShell<T extends string>({ tabs, defaultTab, ariaLabel }: TabShellProps<T>) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const requestedTab = searchParams.get("tab") as T | null;
  const active = tabs.some((tab) => tab.value === requestedTab) ? requestedTab! : defaultTab;
  const activeItem = tabs.find((tab) => tab.value === active) || tabs[0];

  function setTab(value: T) {
    const params = new URLSearchParams(searchParams.toString());
    if (value === defaultTab) {
      params.delete("tab");
    } else {
      params.set("tab", value);
    }
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname);
  }

  function onKeyDown(currentIndex: number, event: React.KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const delta = event.key === "ArrowRight" ? 1 : -1;
    const next = (currentIndex + delta + tabs.length) % tabs.length;
    setTab(tabs[next].value);
  }

  return (
    <>
      <style>{CSS}</style>
      <div className="student-tabbar" role="tablist" aria-label={ariaLabel}>
        {tabs.map((tab, index) => {
          const selected = tab.value === active;
          return (
            <button
              key={tab.value}
              type="button"
              role="tab"
              aria-selected={selected}
              className={`student-tab${selected ? " active" : ""}`}
              onClick={() => setTab(tab.value)}
              onKeyDown={(event) => onKeyDown(index, event)}
            >
              <span>{tab.label}</span>
              {tab.badge !== undefined && tab.badge !== null && <span className="student-tab-badge">{tab.badge}</span>}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" className="student-tabpanel">
        {activeItem?.render}
      </div>
    </>
  );
}

const CSS = `
.student-tabbar { display:flex; border-bottom:2px solid var(--border); background:var(--paper-soft,#fdfbf7); padding:0 24px; overflow-x:auto; scrollbar-width:none; }
.student-tabbar::-webkit-scrollbar { display:none; }
.student-tab { flex:0 0 auto; display:flex; align-items:center; gap:6px; padding:14px 20px; font-size:14px; font-weight:700; letter-spacing:.05em; color:var(--muted); background:none; border:none; border-bottom:2px solid transparent; margin-bottom:-2px; cursor:pointer; transition:color .18s, border-color .18s, background .18s; }
.student-tab.active { color:var(--cinnabar); border-bottom-color:var(--cinnabar); background:rgba(183,66,43,.035); }
.student-tab:hover:not(.active) { color:var(--ink); }
.student-tab:focus-visible { outline:3px solid rgba(183,66,43,.22); outline-offset:-3px; }
.student-tab-badge { display:inline-flex; align-items:center; justify-content:center; min-width:18px; height:18px; padding:0 5px; border-radius:9px; font-size:11px; font-weight:800; background:var(--cinnabar); color:#fff; line-height:1; }
@media (max-width: 768px) { .student-tabbar { position:sticky; top:0; z-index:20; padding:0 14px; box-shadow:0 8px 22px rgba(59,39,19,.08); } .student-tab { padding:13px 16px; } }
`;
