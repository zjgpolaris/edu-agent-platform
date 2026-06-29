from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "knowledge_base" / "history" / "corpus.json"
OUTPUT_PATH = ROOT / "knowledge_base" / "history" / "card_candidates.json"
YEAR_PATTERN = re.compile(r"(公元前\s*\d+|前\s*\d+|\d{3,4})\s*年")


def parse_year(text: str) -> tuple[int, str] | None:
    match = YEAR_PATTERN.search(text)
    if not match:
        return None

    raw = match.group(0).replace(" ", "")
    digits = re.search(r"\d+", raw)
    if not digits:
        return None

    year = int(digits.group(0))
    if raw.startswith("公元前") or raw.startswith("前"):
        year = -year
    return year, raw


def make_candidate(index: int, item: dict[str, Any]) -> dict[str, Any] | None:
    text = str(item.get("text") or "").strip()
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    if meta.get("type") != "textbook":
        return None

    parsed_year = parse_year(text)
    if not parsed_year:
        return None

    year, display_year = parsed_year
    topic = str(meta.get("topic") or meta.get("lesson") or "历史事件").strip()
    title = topic.split("·")[-1] or topic
    period = topic.split("·")[0] if "·" in topic else str(meta.get("unit") or "").strip()
    summary = text[:120]

    return {
        "id": f"corpus-card-{index:04d}",
        "title": title,
        "year": year,
        "display_year": display_year,
        "period": period or "历史时期",
        "summary": summary,
        "topic": topic,
        "grade": str(meta.get("grade") or "").strip(),
        "source": str(meta.get("source") or "").strip(),
    }


def main() -> None:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    candidates = []
    seen: set[tuple[str, int]] = set()
    for index, item in enumerate(corpus, start=1):
        if not isinstance(item, dict):
            continue
        candidate = make_candidate(index, item)
        if not candidate:
            continue
        key = (candidate["title"], candidate["year"])
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)

    OUTPUT_PATH.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(candidates)} candidates to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
