import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from agents.card_game import generate_card_game_round
from agents.history_games import TIMELINE_LEVELS
from agents.timeline_question_generator import (
    TimelineGenerationError,
    event_count_for_difficulty,
    generate_timeline_round_with_llm,
    leaks_year,
)

TIMELINE_CASES = [
    {"name": "timeline-ancient-easy", "grade": "七年级", "difficulty": "easy", "topic": "中国古代史"},
    {"name": "timeline-modern-normal", "grade": "八年级上", "difficulty": "normal", "topic": "中国近代史"},
]
CARD_CASES = [
    {"name": "card-ancient-easy", "grade": "七年级", "difficulty": "easy", "topic": "中国古代史"},
    {"name": "card-world-normal", "grade": "九年级", "difficulty": "normal", "topic": "世界史"},
]


def _ids_unique(items: list[dict[str, Any]]) -> bool:
    ids = [item.get("id") for item in items]
    return len(ids) == len(set(ids))


def _years_unique(items: list[dict[str, Any]]) -> bool:
    years = [item.get("year") for item in items]
    return len(years) == len(set(years))


def _selected_ids_match(round_data: dict[str, Any]) -> bool:
    events = round_data.get("events") or []
    return round_data.get("selected_event_ids") == [event.get("id") for event in events]


def _shape_valid(round_data: dict[str, Any], difficulty: str) -> bool:
    events = round_data.get("events") or []
    if not round_data.get("title") or not round_data.get("learning_goal"):
        return False
    if len(events) != event_count_for_difficulty(difficulty):
        return False
    required = {"id", "title", "year", "display_year", "period", "summary", "explanation"}
    for event in events:
        if not required.issubset(event.keys()):
            return False
        if not event.get("title") or not event.get("summary") or not event.get("explanation"):
            return False
    return True


def _year_leaks(round_data: dict[str, Any]) -> bool:
    for event in round_data.get("events") or []:
        if leaks_year(str(event.get("summary") or ""), event):
            return True
    return False


def _run_timeline_case(case: dict[str, Any]) -> dict[str, Any]:
    try:
        round_data = generate_timeline_round_with_llm(
            TIMELINE_LEVELS,
            grade=case["grade"],
            difficulty=case["difficulty"],
            topic=case["topic"],
            student_id=None,
            recent_store={},
        )
        error = ""
    except Exception as exc:
        round_data = {}
        error = str(exc)

    events = round_data.get("events") or []
    return {
        "name": case["name"],
        "kind": "timeline",
        "generated": bool(round_data),
        "shape_valid": _shape_valid(round_data, case["difficulty"]),
        "ids_unique": _ids_unique(events),
        "years_unique": _years_unique(events),
        "selected_ids_match": _selected_ids_match(round_data),
        "year_leak": _year_leaks(round_data),
        "error": error,
    }


def _run_card_case(case: dict[str, Any]) -> dict[str, Any]:
    try:
        round_data = generate_card_game_round(
            TIMELINE_LEVELS,
            grade=case["grade"],
            difficulty=case["difficulty"],
            topic=case["topic"],
            student_id=None,
            recent_store={},
            wrong_card_ids=[],
        )
        error = ""
    except Exception as exc:
        round_data = {}
        error = str(exc)

    events = round_data.get("events") or []
    return {
        "name": case["name"],
        "kind": "card",
        "generated": bool(round_data),
        "shape_valid": _shape_valid(round_data, case["difficulty"]),
        "ids_unique": _ids_unique(events),
        "years_unique": _years_unique(events),
        "selected_ids_match": _selected_ids_match(round_data),
        "year_leak": _year_leaks(round_data),
        "error": error,
    }


def _passed(result: dict[str, Any]) -> bool:
    return all(
        [
            result["generated"],
            result["shape_valid"],
            result["ids_unique"],
            result["years_unique"],
            result["selected_ids_match"],
            not result["year_leak"],
        ]
    )


def main() -> None:
    results = [_run_timeline_case(case) for case in TIMELINE_CASES]
    results.extend(_run_card_case(case) for case in CARD_CASES)

    for result in results:
        status = "OK" if _passed(result) else "FAIL"
        print(
            f"{status} {result['name']}: kind={result['kind']} generated={result['generated']} "
            f"shape={result['shape_valid']} ids_unique={result['ids_unique']} years_unique={result['years_unique']} "
            f"selected_ids={result['selected_ids_match']} year_leak={result['year_leak']} error={result['error']}"
        )

    total = len(results)
    timeline_total = sum(item["kind"] == "timeline" for item in results)
    card_total = sum(item["kind"] == "card" for item in results)
    metrics = {
        "timeline_round_valid_rate": sum(item["kind"] == "timeline" and _passed(item) for item in results),
        "card_round_valid_rate": sum(item["kind"] == "card" and _passed(item) for item in results),
        "json_parse_success_rate": sum(item["generated"] for item in results),
        "year_leak_rate": sum(item["year_leak"] for item in results),
    }
    print()
    print(f"timeline_round_valid_rate={metrics['timeline_round_valid_rate']}/{timeline_total}")
    print(f"card_round_valid_rate={metrics['card_round_valid_rate']}/{card_total}")
    print(f"json_parse_success_rate={metrics['json_parse_success_rate']}/{total}")
    print(f"year_leak_rate={metrics['year_leak_rate']}/{total}")

    failures = [item["name"] for item in results if not _passed(item)]
    if failures:
        raise SystemExit(f"failed cases: {', '.join(failures)}")


if __name__ == "__main__":
    main()
