#!/usr/bin/env python3
"""Export and apply auditable teacher review for history retrieval labels.

The production retrieval gate must never infer relevance from the system under
test. This workflow snapshots stable source IDs for each query, lets a history
teacher assign 0/1/2 relevance, and applies only explicit human decisions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_DATASET = ROOT / "eval" / "datasets" / "history_retrieval_cases.json"
SCHEMA_VERSION = 1
RELEVANCE_LABELS = {0, 1, 2}
PLACEHOLDER_REVIEWERS = {"", "pending", "todo", "unknown", "system", "auto", "llm"}
AUTOMATED_REVIEWER_PREFIXES = ("gpt-", "qwen-", "claude-", "gemini-", "llm-", "auto-", "system-")
CASE_FINGERPRINT_FIELDS = (
    "id",
    "query",
    "expected_entity",
    "expected_aspect",
    "relevance_scale",
)
SOURCE_SNAPSHOT_FIELDS = (
    "source_id",
    "parent_source_id",
    "source_title",
    "source",
    "source_tier",
    "document_type",
    "entity_id",
    "entity",
    "topic",
    "aspect",
    "claim",
    "snippet",
    "grade",
    "unit",
    "lesson",
    "page",
    "corpus_version",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def case_fingerprint(case: dict[str, Any]) -> str:
    return _sha256({field: case.get(field) for field in CASE_FINGERPRINT_FIELDS})


def candidate_snapshot_hash(candidates: list[dict[str, Any]]) -> str:
    return _sha256(candidates)


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("dataset_not_found") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("dataset_invalid_json") from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("dataset_must_be_object_array")
    ids = [str(item.get("id") or "") for item in payload]
    if any(not case_id for case_id in ids):
        raise ValueError("dataset_case_id_missing")
    if len(ids) != len(set(ids)):
        raise ValueError("dataset_case_id_duplicate")
    return payload


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ValueError("review_packet_not_found") from exc
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"review_packet_invalid_json_line:{line_number}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"review_packet_line_not_object:{line_number}")
        records.append(record)
    case_ids = [str(record.get("case_id") or "") for record in records]
    if any(not case_id for case_id in case_ids):
        raise ValueError("review_packet_case_id_missing")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("review_packet_case_id_duplicate")
    return records


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(serialized)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(serialized)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _source_snapshot(source: dict[str, Any]) -> dict[str, Any] | None:
    source_id = str(source.get("source_id") or "").strip()
    if not source_id:
        return None
    snapshot: dict[str, Any] = {"source_id": source_id[:96]}
    for field in SOURCE_SNAPSHOT_FIELDS[1:]:
        value = source.get(field)
        if value in (None, "", []):
            continue
        if isinstance(value, str):
            snapshot[field] = value[:800]
        elif isinstance(value, (int, float, bool)):
            snapshot[field] = value
        elif isinstance(value, list):
            snapshot[field] = value[:12]
    return snapshot


def _default_candidate_provider(case: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from tools.history_search import search_history_knowledge

    result = search_history_knowledge({
        "query": str(case["query"]),
        "topic": str(case["expected_entity"]),
        "k": limit,
    }).model_dump()
    sources = (result.get("data") or {}).get("sources") or []
    return [source for source in sources if isinstance(source, dict)]


def export_review_packet(
    dataset_path: Path,
    output_path: Path,
    *,
    candidate_limit: int = 8,
    include_reviewed: bool = False,
    candidate_provider: Callable[[dict[str, Any], int], list[dict[str, Any]]] | None = None,
) -> dict[str, int]:
    if candidate_limit < 5 or candidate_limit > 8:
        raise ValueError("candidate_limit_must_be_between_5_and_8")
    provider = candidate_provider or _default_candidate_provider
    cases = _load_json_array(dataset_path)
    records: list[dict[str, Any]] = []
    skipped_reviewed = 0
    empty_candidate_cases = 0
    for case in cases:
        if case.get("review_status") == "teacher_reviewed" and not include_reviewed:
            skipped_reviewed += 1
            continue
        raw_candidates = provider(case, candidate_limit)
        candidates: list[dict[str, Any]] = []
        seen_source_ids: set[str] = set()
        for raw_source in raw_candidates:
            snapshot = _source_snapshot(raw_source)
            if not snapshot or snapshot["source_id"] in seen_source_ids:
                continue
            seen_source_ids.add(snapshot["source_id"])
            candidates.append(snapshot)
        if not candidates:
            empty_candidate_cases += 1
        records.append({
            "schema_version": SCHEMA_VERSION,
            "dataset": dataset_path.name,
            "case_id": str(case["id"]),
            "query": str(case.get("query") or ""),
            "source_fingerprint": case_fingerprint(case),
            "proposed_labels": {
                "expected_entity": str(case.get("expected_entity") or ""),
                "expected_aspect": str(case.get("expected_aspect") or ""),
            },
            "candidate_snapshot_hash": candidate_snapshot_hash(candidates),
            "candidates": candidates,
            "judgments": [
                {"source_id": candidate["source_id"], "relevance": None, "notes": ""}
                for candidate in candidates
            ],
            "decision": "pending",
            "reviewer_id": "",
            "reviewed_at": "",
            "review_notes": "",
        })
    _write_jsonl(output_path, records)
    return {
        "exported": len(records),
        "skipped_reviewed": skipped_reviewed,
        "empty_candidate_cases": empty_candidate_cases,
    }


def _validate_review_timestamp(value: Any) -> None:
    text_value = str(value or "").strip()
    if not text_value:
        raise ValueError("reviewed_at_missing")
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reviewed_at_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("reviewed_at_timezone_required")


def _reviewer_is_automated(value: Any) -> bool:
    reviewer_id = str(value or "").strip().lower()
    return reviewer_id in PLACEHOLDER_REVIEWERS or reviewer_id.startswith(AUTOMATED_REVIEWER_PREFIXES)


def _validated_decision(record: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("review_schema_version_invalid")
    decision = str(record.get("decision") or "pending").strip().lower()
    if decision == "pending":
        return decision, []
    if decision not in {"approve", "reject"}:
        raise ValueError("review_decision_invalid")
    reviewer_id = str(record.get("reviewer_id") or "").strip()
    if _reviewer_is_automated(reviewer_id):
        raise ValueError("reviewer_id_missing_or_automated")
    _validate_review_timestamp(record.get("reviewed_at"))
    candidates = record.get("candidates")
    if not isinstance(candidates, list) or not all(isinstance(item, dict) for item in candidates):
        raise ValueError("review_candidates_invalid")
    if candidate_snapshot_hash(candidates) != record.get("candidate_snapshot_hash"):
        raise ValueError("review_candidate_snapshot_changed")
    candidate_ids = [str(item.get("source_id") or "").strip() for item in candidates]
    if any(not source_id for source_id in candidate_ids) or len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("review_candidate_source_ids_invalid")
    if decision == "reject":
        return decision, []
    if not candidate_ids:
        raise ValueError("review_approval_requires_candidates")
    labels = record.get("proposed_labels")
    if not isinstance(labels, dict) or not str(labels.get("expected_entity") or "").strip() or not str(labels.get("expected_aspect") or "").strip():
        raise ValueError("review_labels_missing")
    judgments = record.get("judgments")
    if not isinstance(judgments, list) or not all(isinstance(item, dict) for item in judgments):
        raise ValueError("review_judgments_invalid")
    judgment_ids = [str(item.get("source_id") or "").strip() for item in judgments]
    if len(judgment_ids) != len(set(judgment_ids)) or set(judgment_ids) != set(candidate_ids):
        raise ValueError("review_judgments_must_cover_candidate_snapshot")
    normalized: list[dict[str, Any]] = []
    for item in judgments:
        relevance = item.get("relevance")
        if isinstance(relevance, bool) or relevance not in RELEVANCE_LABELS:
            raise ValueError("review_relevance_must_be_0_1_2")
        normalized.append({
            "source_id": str(item["source_id"]),
            "relevance": int(relevance),
            "notes": str(item.get("notes") or "")[:300],
        })
    if not any(item["relevance"] == 2 for item in normalized):
        raise ValueError("review_approval_requires_answer_bearing_source")
    return decision, normalized


def validate_reviewed_case(case: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if case.get("review_status") != "teacher_reviewed":
        failures.append("not_teacher_reviewed")
    reviewer_id = str(case.get("reviewed_by") or "").strip()
    if _reviewer_is_automated(reviewer_id):
        failures.append("reviewer_missing_or_automated")
    try:
        _validate_review_timestamp(case.get("reviewed_at"))
    except ValueError as exc:
        failures.append(str(exc))
    for hash_field in ("review_source_fingerprint", "candidate_snapshot_hash"):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(case.get(hash_field) or "")):
            failures.append(f"{hash_field}_missing_or_invalid")
    review_fingerprint = str(case.get("review_source_fingerprint") or "")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", review_fingerprint) and review_fingerprint != case_fingerprint(case):
        failures.append("review_source_fingerprint_stale")
    judgments = case.get("source_judgments")
    if not isinstance(judgments, list) or not judgments:
        failures.append("source_judgments_missing")
        return failures
    source_ids: list[str] = []
    relevances: list[int] = []
    for item in judgments:
        if not isinstance(item, dict):
            failures.append("source_judgment_invalid")
            continue
        source_id = str(item.get("source_id") or "").strip()
        relevance = item.get("relevance")
        if not source_id:
            failures.append("source_judgment_id_missing")
        if isinstance(relevance, bool) or relevance not in RELEVANCE_LABELS:
            failures.append("source_judgment_relevance_invalid")
            continue
        source_ids.append(source_id)
        relevances.append(int(relevance))
    if len(source_ids) != len(set(source_ids)):
        failures.append("source_judgment_id_duplicate")
    if 2 not in relevances:
        failures.append("answer_bearing_judgment_missing")
    return list(dict.fromkeys(failures))


def apply_review_packet(dataset_path: Path, packet_path: Path, *, write: bool = False) -> dict[str, int]:
    cases = _load_json_array(dataset_path)
    records = _load_jsonl(packet_path)
    by_id = {str(case["id"]): case for case in cases}
    updated_cases = [dict(case) for case in cases]
    updated_by_id = {str(case["id"]): case for case in updated_cases}
    counts = Counter({"approved": 0, "rejected": 0, "pending": 0})
    errors: list[str] = []
    for record in records:
        case_id = str(record.get("case_id") or "")
        case = by_id.get(case_id)
        if case is None:
            errors.append(f"unknown_case:{case_id}")
            continue
        if record.get("dataset") != dataset_path.name:
            errors.append(f"dataset_mismatch:{case_id}")
            continue
        if record.get("source_fingerprint") != case_fingerprint(case):
            errors.append(f"stale_case_fingerprint:{case_id}")
            continue
        try:
            decision, judgments = _validated_decision(record)
        except ValueError as exc:
            errors.append(f"{exc}:{case_id}")
            continue
        labels = record.get("proposed_labels") or {}
        if decision == "approve" and any(
            str(labels.get(field) or "").strip() != str(case.get(field) or "").strip()
            for field in ("expected_entity", "expected_aspect")
        ):
            errors.append(f"review_label_change_requires_reexport:{case_id}")
            continue
        if decision == "pending":
            counts["pending"] += 1
            continue
        target = updated_by_id[case_id]
        review_metadata = {
            "reviewed_by": str(record.get("reviewer_id") or "").strip(),
            "reviewed_at": str(record.get("reviewed_at") or "").strip(),
            "review_notes": str(record.get("review_notes") or "")[:500],
            "review_source_fingerprint": str(record.get("source_fingerprint")),
            "candidate_snapshot_hash": str(record.get("candidate_snapshot_hash")),
        }
        if decision == "reject":
            target.update({"review_status": "teacher_rejected", **review_metadata})
            counts["rejected"] += 1
            continue
        counts["approved"] += 1
        target.update({
            "expected_entity": str(labels["expected_entity"]).strip(),
            "expected_aspect": str(labels["expected_aspect"]).strip(),
            "source_judgments": judgments,
            "review_status": "teacher_reviewed",
            **review_metadata,
        })
    if errors:
        raise ValueError("review_packet_rejected " + ",".join(errors[:20]))
    if write:
        _write_json_atomic(dataset_path, updated_cases)
    return {
        "approved": int(counts["approved"]),
        "rejected": int(counts["rejected"]),
        "pending": int(counts["pending"]),
        "written": int(write),
    }


def dataset_review_status(dataset_path: Path) -> dict[str, int]:
    cases = _load_json_array(dataset_path)
    counts = Counter(str(case.get("review_status") or "missing") for case in cases)
    invalid_reviewed = sum(1 for case in cases if case.get("review_status") == "teacher_reviewed" and validate_reviewed_case(case))
    return {
        "total": len(cases),
        "teacher_reviewed": counts["teacher_reviewed"],
        "teacher_rejected": counts["teacher_rejected"],
        "pending": len(cases) - counts["teacher_reviewed"] - counts["teacher_rejected"],
        "invalid_reviewed": invalid_reviewed,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and apply human relevance review for history retrieval evals.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Snapshot retrieval candidates into an editable JSONL review packet.")
    export_parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    export_parser.add_argument("--output", type=Path, required=True)
    export_parser.add_argument("--candidate-limit", type=int, default=8)
    export_parser.add_argument("--include-reviewed", action="store_true")

    apply_parser = subparsers.add_parser("apply", help="Validate review decisions; pass --write to atomically update the dataset.")
    apply_parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    apply_parser.add_argument("--input", type=Path, required=True)
    apply_parser.add_argument("--write", action="store_true")

    status_parser = subparsers.add_parser("status", help="Print aggregate review readiness without exposing review content.")
    status_parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.command == "export":
        result = export_review_packet(
            args.dataset.resolve(),
            args.output.resolve(),
            candidate_limit=args.candidate_limit,
            include_reviewed=args.include_reviewed,
        )
        print("history_retrieval_review_export=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
        return
    if args.command == "apply":
        result = apply_review_packet(args.dataset.resolve(), args.input.resolve(), write=args.write)
        print("history_retrieval_review_apply=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
        if not args.write and (result["approved"] or result["rejected"]):
            print("history_retrieval_review_dry_run=1 pass --write to update the dataset")
        return
    result = dataset_review_status(args.dataset.resolve())
    print("history_retrieval_review_status=" + json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
