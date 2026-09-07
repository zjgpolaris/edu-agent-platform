import { getApiBaseUrl } from "./api";

export type PendingStart = { version: 1; kind: "start"; key: string; actor: string; createdAt: number; focus: string | null };
export type PendingAnswer = { version: 1; kind: "answer"; key: string; actor: string; createdAt: number; sessionId: string; revision: number; answer: string };
export type PendingTransition = PendingStart | PendingAnswer;
const PREFIX = "autotutor-pending-v1:";
const TTL = 60 * 60 * 1000;
const storageKey = (actor: string) => `${PREFIX}${encodeURIComponent(getApiBaseUrl())}:${encodeURIComponent(actor)}`;

export function readPending(actor: string): PendingTransition | null {
  try {
    const raw = sessionStorage.getItem(storageKey(actor));
    if (!raw) return null;
    const p = JSON.parse(raw);
    if (p.version !== 1 || p.actor !== actor || typeof p.key !== "string" || !p.key.startsWith("at-client-") || !Number.isFinite(p.createdAt) || Date.now() - p.createdAt > TTL || p.createdAt > Date.now() ||
      (p.kind !== "start" && p.kind !== "answer") ||
      (p.kind === "start" && p.focus !== null && typeof p.focus !== "string") ||
      (p.kind === "answer" && (typeof p.sessionId !== "string" || !Number.isInteger(p.revision) || p.revision < 0 || !/^[A-D]$/.test(p.answer)))) {
      clearPending(actor); return null;
    }
    return p as PendingTransition;
  } catch { return null; }
}

export function savePending(pending: PendingTransition): void {
  // Fail before sending a mutation if refresh-safe recovery cannot be recorded.
  sessionStorage.setItem(storageKey(pending.actor), JSON.stringify(pending));
}

export function clearPending(actor: string): void {
  try { sessionStorage.removeItem(storageKey(actor)); } catch { /* blocked storage */ }
}

export function clearAllPending(): void {
  try {
    for (let i = sessionStorage.length - 1; i >= 0; i--) {
      const key = sessionStorage.key(i);
      if (key?.startsWith(PREFIX)) sessionStorage.removeItem(key);
    }
  } catch { /* blocked storage */ }
}

export function pendingKey(): string { return `at-client-${crypto.randomUUID()}`; }
