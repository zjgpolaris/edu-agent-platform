"""Session message history storage."""
import json
import time

try:
    import redis
except ImportError:
    redis = None

SESSION_TTL = 3600
_SUMMARY_THRESHOLD = 20  # compress when history exceeds this many messages
_KEEP_RECENT = 6         # keep this many recent messages after compression
_memory_sessions: dict[str, tuple[float, list[dict]]] = {}
_r = redis.Redis(host="localhost", port=6379, decode_responses=True) if redis else None


def _summarize(messages: list[dict]) -> str:
    from llm_config import llm_fast
    history = "\n".join(
        f"{m['role']}: {str(m.get('content', ''))[:200]}"
        for m in messages
    )
    prompt = f"请用200字以内概括以下对话历史的关键内容：\n{history}"
    try:
        return llm_fast.invoke([{"role": "user", "content": prompt}]).content.strip()
    except Exception:
        return ""


def compress_messages(messages: list[dict]) -> list[dict]:
    if len(messages) <= _SUMMARY_THRESHOLD:
        return messages
    to_compress = messages[:-_KEEP_RECENT]
    recent = messages[-_KEEP_RECENT:]
    summary = _summarize(to_compress)
    if not summary:
        return messages
    return [{"role": "system", "content": f"[对话摘要] {summary}"}] + recent


def load_messages(session_id: str) -> list[dict]:
    if _r:
        try:
            raw = _r.get(f"session:{session_id}")
            return json.loads(raw) if raw else []
        except Exception:
            pass

    expires_at, messages = _memory_sessions.get(session_id, (0, []))
    if expires_at < time.time():
        _memory_sessions.pop(session_id, None)
        return []
    return messages


def save_messages(session_id: str, messages: list[dict]):
    messages = compress_messages(messages)
    if _r:
        try:
            _r.setex(f"session:{session_id}", SESSION_TTL, json.dumps(messages, ensure_ascii=False))
            return
        except Exception:
            pass

    _memory_sessions[session_id] = (time.time() + SESSION_TTL, messages)
