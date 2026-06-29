import { authHeaders, clientSessionHeaders } from "@/lib/auth";

export const DEFAULT_API_BASE_URL = "http://localhost:8000";

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
  const { body, headers, token, includeClientSession, fallbackMessage = "请求失败，请稍后重试", ...init } = options;
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

  const response = await fetch(apiUrl(path), {
    ...init,
    headers: requestHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await parseJsonSafely(response);

  if (!response.ok) {
    throw new ApiError(getPayloadMessage(payload) || fallbackMessage, response.status, payload, response);
  }

  return payload as T;
}
