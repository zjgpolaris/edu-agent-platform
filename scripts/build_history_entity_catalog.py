"""Build the deterministic history entity catalog from corpus metadata and reviewed events."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = ROOT / "knowledge_base" / "history"

REVIEWED_ENTITIES = (
    ("长平之战", "event", ()),
    ("赤壁之战", "event", ()),
    ("鸦片战争", "event", ()),
    ("洋务运动", "event", ()),
    ("商鞅变法", "event", ()),
    ("贞观之治", "event", ()),
    ("张骞出使西域", "event", ()),
    ("虎门销烟", "event", ()),
    ("苏轼", "person", ()),
    ("辛弃疾", "person", ()),
    ("李清照", "person", ()),
    ("秦始皇", "person", ("嬴政",)),
    ("唐太宗", "person", ("李世民",)),
    ("张骞", "person", ()),
    ("林则徐", "person", ()),
    ("商鞅", "person", ()),
    ("白起", "person", ()),
    ("诸葛亮", "person", ("孔明",)),
)


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def _entity_type(name: str, row: dict) -> str:
    event_type = str(row.get("type") or "")
    if event_type in {"battle", "politics", "reform", "movement", "treaty", "construction"} or name.endswith(("之战", "战争", "运动", "变法", "起义", "革命", "条约")):
        return "event"
    if name.endswith(("朝", "王朝", "时期")):
        return "dynasty"
    if name.endswith(("制度", "政策", "制")):
        return "institution"
    return "unknown"


def _entity_id(name: str, entity_type: str) -> str:
    digest = hashlib.sha256(_compact(name).encode("utf-8")).hexdigest()[:16]
    return f"{entity_type}.{digest}"


def main() -> None:
    corpus = json.loads((HISTORY_DIR / "corpus.json").read_text(encoding="utf-8"))
    events = json.loads((HISTORY_DIR / "geo_events.json").read_text(encoding="utf-8"))
    collected: dict[str, dict] = {}
    refs: dict[str, set[str]] = defaultdict(set)
    grades: dict[str, set[str]] = defaultdict(set)
    lessons: dict[str, set[str]] = defaultdict(set)

    for row in corpus:
        meta = row.get("meta") or {}
        names = [meta.get("event"), meta.get("topic"), *(meta.get("entities") or [])]
        for raw_name in names:
            name = str(raw_name or "").strip()
            if not (2 <= len(name) <= 30) or name in {"历史", "中国历史", "相关史事"}:
                continue
            entity_type = _entity_type(name, meta)
            collected.setdefault(name, {"entity_type": entity_type, "aliases": [], "reviewed": False})
            if meta.get("grade"):
                grades[name].add(str(meta["grade"]))
            if meta.get("lesson"):
                lessons[name].add(str(meta["lesson"]))
            refs[name].add(str(meta.get("source_id") or meta.get("source") or "corpus"))

    for event in events:
        name = str(event.get("title") or "").strip()
        if not name:
            continue
        collected[name] = {"entity_type": "event", "aliases": [], "reviewed": True}
        refs[name].add(f"geo-event-{event.get('id')}")

    for name, entity_type, aliases in REVIEWED_ENTITIES:
        current = collected.setdefault(name, {"entity_type": entity_type, "aliases": [], "reviewed": True})
        current["entity_type"] = entity_type
        current["aliases"] = sorted(set(current.get("aliases") or []) | set(aliases))
        current["reviewed"] = True
        refs[name].add("reviewed-seed-v1")

    rows = [
        {
            "entity_id": _entity_id(name, payload["entity_type"]),
            "canonical_name": name,
            "entity_type": payload["entity_type"],
            "aliases": payload["aliases"],
            "grades": sorted(grades[name]),
            "lessons": sorted(lessons[name]),
            "source_refs": sorted(refs[name]),
            "reviewed": payload["reviewed"],
        }
        for name, payload in sorted(collected.items(), key=lambda item: (_compact(item[0]), item[0]))
    ]
    target = HISTORY_DIR / "entities.json"
    target.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"history_entity_catalog={len(rows)} target={target}")


if __name__ == "__main__":
    main()
