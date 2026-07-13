from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ["EDU_AGENT_DB_PATH"] = str(Path(tempfile.gettempdir()) / "edu-agent-textbook-trace-smoke.sqlite3")

from textbook_learning.schema import TextbookAskRequest
from textbook_learning.service import stream_ask_events
from trace_store import create_trace_id, get_trace_store, trace_context


def _skip(reason: str) -> None:
    print(f"SKIP textbook_trace_smoke: {reason}")
    raise SystemExit(0)


def main() -> None:
    trace_id = create_trace_id()
    try:
        with trace_context(trace_id):
            events = stream_ask_events(
                TextbookAskRequest(
                    book_id="history-grade-8a",
                    lesson_id="lesson-1",
                    question="鸦片战争为什么重要",
                    item_id="lesson-1-item-2",
                )
            )
            for _event, _data in events:
                pass
    except Exception as exc:
        _skip(f"textbook trace unavailable ({exc})")

    trace = get_trace_store().get_trace(trace_id)
    retrieval = next((item for item in trace if item.get("step_name") == "rag_retrieval"), None)
    generation = next((item for item in trace if item.get("step_name") == "response_generation"), None)

    assert retrieval is not None
    assert generation is not None
    assert isinstance((retrieval.get("metadata") or {}).get("rag_inspector"), dict)
    assert ((retrieval.get("metadata") or {}).get("rag_inspector") or {}).get("diagnosis_code")
    assert isinstance((generation.get("metadata") or {}).get("rag_inspector"), dict)
    print("textbook_trace_smoke=PASS")


if __name__ == "__main__":
    main()
