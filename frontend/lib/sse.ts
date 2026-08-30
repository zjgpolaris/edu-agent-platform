import { ApiError, apiUrl } from "@/lib/api";
import { authHeaders, clientSessionHeaders } from "@/lib/auth";

export type SseEvent<TData = Record<string, unknown>> = {
  id?: string;
  event: string;
  data: TData;
};

export type PostJsonSseOptions<TData = Record<string, unknown>> = {
  headers?: HeadersInit;
  token?: string | null;
  includeClientSession?: boolean;
  signal?: AbortSignal;
  fallbackMessage?: string;
  onEvent: (event: SseEvent<TData>) => void | Promise<void>;
};

async function parseErrorPayload(response: Response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

function getErrorMessage(payload: unknown, fallback: string) {
  if (typeof payload === "string") return payload;
  if (!payload || typeof payload !== "object") return fallback;
  const item = payload as { detail?: unknown; message?: unknown; error?: unknown };
  const candidate = item.detail ?? item.message ?? item.error;
  return typeof candidate === "string" ? candidate : fallback;
}

export function parseSseFrame<TData = Record<string, unknown>>(frame: string): SseEvent<TData> | null {
  let id: string | undefined;
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    const clean = line.endsWith("\r") ? line.slice(0, -1) : line;
    if (!clean || clean.startsWith(":")) continue;
    if (clean.startsWith("event:")) event = clean.slice(6).trim() || "message";
    else if (clean.startsWith("id:")) id = clean.slice(3).trim() || undefined;
    else if (clean.startsWith("data:")) dataLines.push(clean.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  return { id, event, data: JSON.parse(dataLines.join("\n")) as TData };
}

export async function readSseStream<TData = Record<string, unknown>>(
  response: Response,
  onEvent: (event: SseEvent<TData>) => void | Promise<void>,
) {
  if (!response.body) throw new Error("浏览器没有收到流式响应，请稍后重试。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  async function drain(frames: string[]) {
    for (const frame of frames) {
      const event = parseSseFrame<TData>(frame.trim());
      if (event) await onEvent(event);
    }
  }
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() || "";
    await drain(frames);
  }
  buffer += decoder.decode();
  if (buffer.trim()) await drain([buffer]);
}

export async function postJsonSse<TData = Record<string, unknown>>(
  path: string,
  body: unknown,
  options: PostJsonSseOptions<TData>,
) {
  const { headers, token, includeClientSession, signal, fallbackMessage = "流式生成失败，请稍后重试。", onEvent } = options;
  const requestHeaders = new Headers(headers);
  if (!requestHeaders.has("Content-Type")) requestHeaders.set("Content-Type", "application/json");
  if (token) Object.entries(authHeaders(token)).forEach(([key, value]) => requestHeaders.set(key, value));
  if (includeClientSession) Object.entries(clientSessionHeaders()).forEach(([key, value]) => requestHeaders.set(key, value));
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: requestHeaders,
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    const payload = await parseErrorPayload(response);
    throw new ApiError(getErrorMessage(payload, fallbackMessage), response.status, payload, response);
  }
  await readSseStream(response, onEvent);
}

export async function fetchSSE(
  url: string,
  options: {
    token?: string;
    signal?: AbortSignal;
    onMessage: (data: string) => void;
  },
): Promise<void> {
  const response = await fetch(url, {
    headers: options.token ? { Authorization: `Bearer ${options.token}` } : undefined,
    signal: options.signal,
  });
  if (!response.ok) throw new Error(`SSE request failed (${response.status})`);
  await readSseStream(response, event => options.onMessage(JSON.stringify(event.data)));
}
