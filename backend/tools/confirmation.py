"""Tool confirmation token management for high-risk tool execution."""
from __future__ import annotations

import time
import threading
from typing import Dict, Optional
from uuid import uuid4


class ConfirmationStore:
    """Confirmation token storage for high-risk tool execution."""

    def __init__(self, ttl_seconds: int = 300):
        self._tokens: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds

    def create_token(self, tool_name: str, actor_id: str) -> str:
        """Create a confirmation token."""
        token = f"confirm_{uuid4().hex[:12]}"
        with self._lock:
            self._tokens[token] = {
                "tool_name": tool_name,
                "actor_id": actor_id,
                "created_at": time.time(),
            }
        return token

    def validate_token(self, token: str, tool_name: str, actor_id: str) -> bool:
        """Validate a confirmation token."""
        with self._lock:
            data = self._tokens.get(token)
            if not data:
                return False
            if time.time() - data["created_at"] > self._ttl_seconds:
                del self._tokens[token]
                return False
            return data["tool_name"] == tool_name and data["actor_id"] == actor_id

    def consume_token(self, token: str) -> bool:
        """Consume a confirmation token (one-time use)."""
        with self._lock:
            if token in self._tokens:
                del self._tokens[token]
                return True
            return False

    def cleanup_expired(self) -> int:
        """Clean up expired tokens. Returns number of tokens removed."""
        now = time.time()
        with self._lock:
            expired = [tid for tid, data in self._tokens.items() if now - data["created_at"] > self._ttl_seconds]
            for tid in expired:
                del self._tokens[tid]
            return len(expired)


# Global confirmation store instance
_confirmation_store = ConfirmationStore()


def get_confirmation_store() -> ConfirmationStore:
    """Get the global confirmation store instance."""
    return _confirmation_store
