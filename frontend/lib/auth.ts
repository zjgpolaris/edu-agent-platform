export interface AuthUser {
  actorId: string;
  role: "student" | "teacher" | "admin";
  displayName?: string;
  demoMode?: boolean;
  token: string;
}

const KEY = "edu_auth";
const CLIENT_SESSION_KEY = "edu_agent_client_session";

export function saveAuth(user: AuthUser) {
  localStorage.setItem(KEY, JSON.stringify(user));
}

export function loadAuth(): AuthUser | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function homeForRole(role: AuthUser["role"]): string {
  if (role === "admin") return "/eval";
  if (role === "teacher") return "/teacher";
  return "/student";
}

export function safeNextForRole(next: string | null | undefined, role: AuthUser["role"]): string {
  const fallback = homeForRole(role);
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return fallback;
  try {
    const parsed = new URL(next, "https://edu-agent.local");
    if (parsed.origin !== "https://edu-agent.local") return fallback;
    const allowed = role === "admin"
      ? parsed.pathname === "/eval"
      : role === "teacher"
        ? parsed.pathname === "/teacher" || parsed.pathname.startsWith("/teacher/")
        : parsed.pathname === "/student" || parsed.pathname.startsWith("/student/");
    return allowed ? `${parsed.pathname}${parsed.search}` : fallback;
  } catch {
    return fallback;
  }
}

export function clearAuth() {
  localStorage.removeItem(KEY);
}

export function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

export function getClientSessionId(): string {
  const existing = localStorage.getItem(CLIENT_SESSION_KEY);
  if (existing) return existing;
  const id = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  localStorage.setItem(CLIENT_SESSION_KEY, id);
  return id;
}

export function clientSessionHeaders(): Record<string, string> {
  return { "X-Client-Session": getClientSessionId() };
}
