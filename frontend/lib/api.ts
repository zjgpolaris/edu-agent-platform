import { authHeaders, clientSessionHeaders } from "@/lib/auth";

export const DEFAULT_API_BASE_URL = "http://localhost:8000";
export const REQUEST_TIMEOUTS = { read: 30_000, mutation: 90_000, slow: 8_000 };

export class ApiTransportError extends Error {
  constructor(public kind: "timeout" | "network" | "cancelled") {
    super(kind === "timeout" ? "等待响应超时，请确认当前进度后重试" : kind === "cancelled" ? "已停止等待，服务端操作可能仍在进行" : "网络连接中断，请检查网络后同步进度");
    this.name = "ApiTransportError";
  }
}

export function apiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return ({ 401: "登录已失效或账号密码错误，请重新登录", 403: "无权访问此内容", 409: "请求状态冲突，请同步最新进度", 429: "请求过于频繁，请稍后重试", 503: "服务暂不可用，请稍后重试" } as Record<number, string>)[error.status] || "服务请求失败，请稍后重试";
  }
  return error instanceof ApiTransportError ? error.message : "请求失败，请稍后重试";
}

type ErrorPayload = {
  detail?: unknown;
  message?: unknown;
  error?: unknown;
};

export class ApiError extends Error {
  status: number;
  detail: unknown;
  response: Response;

  constructor(message: string, status: number, detail: unknown, response: Response) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.response = response;
  }
}

export type ApiJsonOptions = Omit<RequestInit, "body" | "headers"> & {
  body?: unknown;
  headers?: HeadersInit;
  token?: string | null;
  includeClientSession?: boolean;
  fallbackMessage?: string;
  timeoutMs?: number;
};

export function getApiBaseUrl() {
  return (process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/+$/, "");
}

export function apiUrl(path: string) {
  if (/^https?:\/\//i.test(path)) return path;
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${getApiBaseUrl()}${normalizedPath}`;
}

function getPayloadMessage(payload: unknown): string | null {
  if (typeof payload === "string") return payload;
  if (!payload || typeof payload !== "object") return null;

  const item = payload as ErrorPayload;
  const candidate = item.detail ?? item.message ?? item.error;
  if (typeof candidate === "string") return candidate;
  if (Array.isArray(candidate)) return candidate.map((entry) => (typeof entry === "string" ? entry : JSON.stringify(entry))).join("；");
  if (candidate && typeof candidate === "object") return JSON.stringify(candidate);
  return null;
}

async function parseJsonSafely(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

function applyHeaders(headers: Headers, values: Record<string, string>) {
  for (const [key, value] of Object.entries(values)) {
    headers.set(key, value);
  }
}

export function normalizeError(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export async function fetchApiJson<T>(path: string, options: ApiJsonOptions = {}): Promise<T> {
  const { body, headers, token, includeClientSession, timeoutMs, signal, fallbackMessage = "请求失败，请稍后重试", ...init } = options;
  const requestHeaders = new Headers(headers);

  if (body !== undefined && !requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }
  if (token) {
    applyHeaders(requestHeaders, authHeaders(token));
  }
  if (includeClientSession) {
    applyHeaders(requestHeaders, clientSessionHeaders());
  }

  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  else signal?.addEventListener("abort", abort, { once: true });
  const timer = timeoutMs === undefined ? undefined : setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  try {
    const response = await fetch(apiUrl(path), {
    ...init,
    signal: controller.signal,
    headers: requestHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = timeoutMs === undefined ? await parseJsonSafely(response) : await response.json().catch((error) => {
    if (controller.signal.aborted) throw error;
    if (response.ok) throw new ApiTransportError("network");
    return {};
  });

  if (!response.ok) {
    throw new ApiError(getPayloadMessage(payload) || fallbackMessage, response.status, payload, response);
  }

  return payload as T;
  } catch (error) {
    // Opt-in contract: older callers rely on native DOMException AbortError
    // to ignore effect cleanup (including React Strict Mode's first request).
    if (timeoutMs === undefined) throw error;
    if (timedOut) throw new ApiTransportError("timeout");
    if (signal?.aborted) throw new ApiTransportError("cancelled");
    if (error instanceof ApiError || error instanceof ApiTransportError) throw error;
    throw new ApiTransportError("network");
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}
