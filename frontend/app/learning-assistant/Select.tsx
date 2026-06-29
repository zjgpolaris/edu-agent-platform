"use client";

import { useEffect, useRef, useState } from "react";

export type SelectOption = { value: string; label: string; group?: string };

interface Props {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
}

export function Select({ value, onChange, options, placeholder = "— 请选择 —", disabled }: Props) {
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(-1);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  // reset cursor when opening
  useEffect(() => {
    if (open) {
      const idx = options.findIndex((o) => o.value === value);
      setCursor(idx >= 0 ? idx : 0);
    }
  }, [open, options, value]);

  // scroll cursor into view
  useEffect(() => {
    if (!open || cursor < 0) return;
    const item = menuRef.current?.querySelector<HTMLElement>(`[data-idx="${cursor}"]`);
    item?.scrollIntoView({ block: "nearest" });
  }, [cursor, open]);

  function select(val: string) {
    onChange(val);
    setOpen(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (disabled) return;
    if (!open) {
      if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
        e.preventDefault();
        setOpen(true);
      }
      return;
    }
    if (e.key === "Escape") { e.preventDefault(); setOpen(false); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(c + 1, options.length - 1)); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); return; }
    if (e.key === "Enter" && cursor >= 0) { e.preventDefault(); select(options[cursor].value); return; }
    if (e.key === "Tab") setOpen(false);
  }

  const selected = options.find((o) => o.value === value);

  const groups: { group: string; items: (SelectOption & { idx: number })[] }[] = [];
  const ungrouped: (SelectOption & { idx: number })[] = [];
  options.forEach((opt, idx) => {
    if (opt.group) {
      const g = groups.find((g) => g.group === opt.group);
      if (g) g.items.push({ ...opt, idx });
      else groups.push({ group: opt.group, items: [{ ...opt, idx }] });
    } else {
      ungrouped.push({ ...opt, idx });
    }
  });

  return (
    <div
      className={`ls-select${open ? " open" : ""}${disabled ? " disabled" : ""}`}
      ref={ref}
      onKeyDown={handleKeyDown}
    >
      <button
        type="button"
        className="ls-select-trigger"
        onClick={() => !disabled && setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
      >
        <span className={selected ? "" : "ls-select-placeholder"}>
          {selected ? selected.label : placeholder}
        </span>
        <svg className="ls-select-arrow" width="10" height="6" viewBox="0 0 10 6">
          <path d="M0 0l5 6 5-6z" fill="currentColor" />
        </svg>
      </button>
      {open && (
        <div className="ls-select-menu" role="listbox" ref={menuRef}>
          {ungrouped.map((opt) => (
            <div
              key={opt.value}
              data-idx={opt.idx}
              className={`ls-select-opt${value === opt.value ? " active" : ""}${cursor === opt.idx ? " focused" : ""}`}
              role="option"
              aria-selected={value === opt.value}
              onMouseEnter={() => setCursor(opt.idx)}
              onClick={() => select(opt.value)}
            >
              {opt.label}
            </div>
          ))}
          {groups.map((g) => (
            <div key={g.group}>
              <div className="ls-select-group">{g.group}</div>
              {g.items.map((opt) => (
                <div
                  key={opt.value}
                  data-idx={opt.idx}
                  className={`ls-select-opt grouped${value === opt.value ? " active" : ""}${cursor === opt.idx ? " focused" : ""}`}
                  role="option"
                  aria-selected={value === opt.value}
                  onMouseEnter={() => setCursor(opt.idx)}
                  onClick={() => select(opt.value)}
                >
                  {opt.label}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
