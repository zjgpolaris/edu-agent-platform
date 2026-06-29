import { ApiError, apiUrl } from "@/lib/api";
import { authHeaders, clientSessionHeaders } from "@/lib/auth";

export type SseEvent<TData = Record<string, unknown>> = {
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
  let event = "message";
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    const trimmedLine = line.endsWith("\r") ? line.slice(0, -1) : line;
    if (!trimmedLine || trimmedLine.startsWith(":")) continue;
    if (trimmedLine.startsWith("event:")) {
      event = trimmedLine.slice(6).trim() || "message";
    } else if (trimmedLine.startsWith("data:")) {
      dataLines.push(trimmedLine.slice(5).trimStart());
    }
  }

  if (!dataLines.length) return null;
  return { event, data: JSON.parse(dataLines.join("\n")) as TData };
}

export async function readSseStream<TData = Record<string, unknown>>(
  response: Response,
  onEvent: (event: SseEvent<TData>) => void | Promise<void>,
) {
  if (!response.body) {
    throw new Error("浏览器没有收到流式响应，请稍后重试。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  async function drainFrames(frames: string[]) {
    for (const frame of frames) {
      const streamEvent = parseSseFrame<TData>(frame.trim());
      if (streamEvent) await onEvent(streamEvent);
    }
  }

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() || "";
    await drainFrames(frames);
  }

  buffer += decoder.decode();
  if (buffer.trim()) {
    await drainFrames([buffer]);
  }
}

export async function postJsonSse<TData = Record<string, unknown>>(
  path: string,
  body: unknown,
  options: PostJsonSseOptions<TData>,
) {
  const { headers, token, includeClientSession, signal, fallbackMessage = "流式生成失败，请稍后重试。", onEvent } = options;
  const requestHeaders = new Headers(headers);
  if (!requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }
  if (token) {
    for (const [key, value] of Object.entries(authHeaders(token))) {
      requestHeaders.set(key, value);
    }
  }
  if (includeClientSession) {
    for (const [key, value] of Object.entries(clientSessionHeaders())) {
      requestHeaders.set(key, value);
    }
  }

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
