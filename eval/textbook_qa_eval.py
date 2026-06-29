import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from textbook_learning.loader import get_lesson, get_toc, list_textbooks
from textbook_learning.schema import TextbookAskRequest
from textbook_learning.service import stream_ask_events

DATASET_PATH = Path(__file__).parent / "datasets" / "textbook_qa_cases.json"


def _any_keyword_hit(text: str, keywords: list[str]) -> bool:
    return not keywords or any(keyword in text for keyword in keywords)


def _default_lesson() -> tuple[str, str, str | None, list[str]]:
    for textbook in list_textbooks():
        if textbook.status != "ready":
            continue
        toc = get_toc(textbook.id)
        for unit in toc.units:
            if unit.lessons:
                lesson_id = unit.lessons[0].id
                lesson = get_lesson(textbook.id, lesson_id)
                item = lesson.items[0] if lesson.items else None
                item_id = item.id if item else None
                keywords = []
                if item:
                    keywords = [item.topic, *item.keywords[:2], *item.entities[:2]]
                return textbook.id, lesson_id, item_id, [keyword for keyword in keywords if keyword]
    raise SystemExit("no ready textbook lesson found")


def _collect_events(req: TextbookAskRequest) -> dict[str, Any]:
    events = list(stream_ask_events(req))
    names = [name for name, _ in events]
    final = next((data for name, data in events if name == "final"), {})
    sources_event = next((data for name, data in events if name == "sources"), {})
    deltas = [data.get("text", "") for name, data in events if name == "delta"]
    return {
        "event_names": names,
        "final": final,
        "sources": sources_event.get("sources", []),
        "delta_text": "".join(deltas),
    }


def run_case(case: dict[str, Any], defaults: tuple[str, str, str | None, list[str]]) -> dict[str, Any]:
    default_book_id, default_lesson_id, default_item_id, default_keywords = defaults
    book_id = case.get("book_id") or default_book_id
    lesson_id = case.get("lesson_id") or default_lesson_id
    item_id = case.get("item_id") if "item_id" in case else default_item_id
    expected_answer_keywords = case.get("expected_answer_keywords") or default_keywords[:2]
    expected_source_keywords = case.get("expected_source_keywords") or default_keywords[:2]

    req = TextbookAskRequest(
        book_id=book_id,
        lesson_id=lesson_id,
        item_id=item_id,
        question=case.get("question") or "解释一下",
        action=case.get("action"),
        selected_text=case.get("selected_text"),
    )
    collected = _collect_events(req)
    final = collected["final"]
    sources = collected["sources"]
    response = final.get("response", "")
    source_blob = "\n".join(" ".join(str(value or "") for value in source.values()) for source in sources)

    return {
        "name": case["name"],
        "sources_event": "sources" in collected["event_names"],
        "final_returned": bool(final),
        "answer_non_empty": bool(response.strip()),
        "book_lesson_match": final.get("book_id") == book_id and final.get("lesson_id") == lesson_id,
        "source_presence": isinstance(sources, list) and bool(sources),
        "source_keyword_hit": _any_keyword_hit(source_blob, expected_source_keywords),
        "answer_keyword_hit": _any_keyword_hit(response, expected_answer_keywords),
        "sources": len(sources) if isinstance(sources, list) else 0,
    }


def main() -> None:
    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    defaults = _default_lesson()
    results = [run_case(case, defaults) for case in cases]

    for result in results:
        passed = all(
            [
                result["sources_event"],
                result["final_returned"],
                result["answer_non_empty"],
                result["book_lesson_match"],
                result["source_keyword_hit"],
                result["answer_keyword_hit"],
            ]
        )
        status = "OK" if passed else "FAIL"
        print(
            f"{status} {result['name']}: "
            f"sources_event={result['sources_event']} final={result['final_returned']} "
            f"answer={result['answer_non_empty']} book_lesson={result['book_lesson_match']} "
            f"source_hit={result['source_keyword_hit']} answer_hit={result['answer_keyword_hit']} sources={result['sources']}"
        )

    total = len(results)
    metrics = {
        "source_presence_rate": sum(item["source_presence"] for item in results),
        "final_return_rate": sum(item["final_returned"] for item in results),
        "answer_non_empty_rate": sum(item["answer_non_empty"] for item in results),
        "answer_keyword_hit_rate": sum(item["answer_keyword_hit"] for item in results),
        "source_keyword_hit_rate": sum(item["source_keyword_hit"] for item in results),
    }
    print()
    for name, count in metrics.items():
        print(f"{name}={count}/{total}")

    failures = [
        item["name"]
        for item in results
        if not (
            item["sources_event"]
            and item["final_returned"]
            and item["answer_non_empty"]
            and item["book_lesson_match"]
            and item["source_keyword_hit"]
            and item["answer_keyword_hit"]
        )
    ]
    if failures:
        raise SystemExit(f"failed cases: {', '.join(failures)}")


if __name__ == "__main__":
    main()
