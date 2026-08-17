"""Contract smoke for the human-only history retrieval review workflow."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.history_retrieval_review import (
    apply_review_packet,
    dataset_review_status,
    export_review_packet,
    validate_reviewed_case,
)
from eval.build_history_eval_datasets import build_datasets
from eval.history_retrieval_quality_eval import reviewed_relevance


def _dataset() -> list[dict]:
    return [
        {
            "id": "review-case-1",
            "query": "长平之战有什么意义",
            "expected_entity": "长平之战",
            "expected_aspect": "significance",
            "relevance_scale": {"0": "unrelated", "1": "entity_only", "2": "answer_bearing"},
            "review_status": "seed_pending_teacher_review",
        },
        {
            "id": "review-case-2",
            "query": "苏轼做了什么",
            "expected_entity": "苏轼",
            "expected_aspect": "contribution",
            "relevance_scale": {"0": "unrelated", "1": "entity_only", "2": "answer_bearing"},
            "review_status": "seed_pending_teacher_review",
        },
    ]


def _candidate_provider(case: dict, _limit: int) -> list[dict]:
    entity = case["expected_entity"]
    return [
        {
            "source_id": f"source-{case['id']}-answer",
            "source_title": "review fixture",
            "source_tier": "L1_TEXTBOOK_DIRECT",
            "document_type": "textbook_passage",
            "entity": entity,
            "aspect": case["expected_aspect"],
            "snippet": f"{entity}的当前问答维度可以由这条史料直接支持。",
        },
        {
            "source_id": f"source-{case['id']}-entity",
            "source_title": "review fixture",
            "source_tier": "L1_TEXTBOOK_DIRECT",
            "document_type": "textbook_passage",
            "entity": entity,
            "aspect": "background",
            "snippet": f"这条材料只提到{entity}，不能直接回答当前维度。",
        },
    ]


def _read_packet(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_packet(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def _approve(record: dict) -> None:
    record["decision"] = "approve"
    record["reviewer_id"] = "history-teacher-01"
    record["reviewed_at"] = "2026-08-17T10:00:00+08:00"
    record["review_notes"] = "已核对实体、问答维度与候选史料。"
    for index, judgment in enumerate(record["judgments"]):
        judgment["relevance"] = 2 if index == 0 else 1


def main() -> None:
    passed = 0
    total = 11
    scale = {"0": "unrelated", "1": "entity_only", "2": "answer_bearing"}
    rebuilt = build_datasets([
        {
            "id": "person-苏轼-1",
            "query": "苏轼是什么",
            "expected_entity": "苏轼",
            "expected_aspect": "definition",
            "relevance_scale": scale,
            "review_status": "teacher_rejected",
            "reviewed_by": "history-teacher-01",
        },
        {
            "id": "person-苏轼-6",
            "query": "苏轼有什么影响",
            "expected_entity": "苏轼",
            "expected_aspect": "impact",
            "relevance_scale": scale,
            "review_status": "teacher_reviewed",
            "reviewed_by": "history-teacher-01",
        },
    ])
    rebuilt_retrieval = {case["id"]: case for case in rebuilt["history_retrieval_cases.json"]}
    assert rebuilt_retrieval["person-苏轼-1"]["query"] == "苏轼是谁"
    assert rebuilt_retrieval["person-苏轼-1"]["review_status"] == "seed_pending_teacher_review"
    assert "reviewed_by" not in rebuilt_retrieval["person-苏轼-1"]
    assert rebuilt_retrieval["person-苏轼-6"]["reviewed_by"] == "history-teacher-01"
    assert rebuilt_retrieval["event-长平之战-1"]["query"] == "长平之战是什么"
    passed += 1

    with tempfile.TemporaryDirectory(prefix="history-review-smoke-") as temp_dir:
        root = Path(temp_dir)
        dataset_path = root / "history_retrieval_cases.json"
        packet_path = root / "review.jsonl"
        original = _dataset()
        dataset_path.write_text(json.dumps(original, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        export_result = export_review_packet(
            dataset_path,
            packet_path,
            candidate_provider=_candidate_provider,
        )
        records = _read_packet(packet_path)
        assert export_result == {"exported": 2, "skipped_reviewed": 0, "empty_candidate_cases": 0}
        assert all(record["decision"] == "pending" for record in records)
        assert json.loads(dataset_path.read_text(encoding="utf-8")) == original
        passed += 1

        _approve(records[0])
        records[1]["decision"] = "reject"
        records[1]["reviewer_id"] = "history-teacher-02"
        records[1]["reviewed_at"] = "2026-08-17T10:05:00+08:00"
        records[1]["review_notes"] = "候选材料不足，需要补充语料后重审。"
        _write_packet(packet_path, records)

        dry_run = apply_review_packet(dataset_path, packet_path, write=False)
        assert dry_run == {"approved": 1, "rejected": 1, "pending": 0, "written": 0}
        assert json.loads(dataset_path.read_text(encoding="utf-8")) == original
        passed += 1

        written = apply_review_packet(dataset_path, packet_path, write=True)
        assert written["written"] == 1
        applied = json.loads(dataset_path.read_text(encoding="utf-8"))
        assert applied[0]["review_status"] == "teacher_reviewed"
        assert applied[1]["review_status"] == "teacher_rejected"
        assert [item["relevance"] for item in applied[0]["source_judgments"]] == [2, 1]
        passed += 1

        assert validate_reviewed_case(applied[0]) == []
        status = dataset_review_status(dataset_path)
        assert status == {"total": 2, "teacher_reviewed": 1, "teacher_rejected": 1, "pending": 0, "invalid_reviewed": 0}
        passed += 1

        changed_after_review = dict(applied[0])
        changed_after_review["query"] = "人工复核完成后被修改的问题"
        assert "review_source_fingerprint_stale" in validate_reviewed_case(changed_after_review)
        passed += 1

        stale_packet = root / "stale.jsonl"
        export_review_packet(dataset_path, stale_packet, include_reviewed=True, candidate_provider=_candidate_provider)
        stale_records = _read_packet(stale_packet)
        _approve(stale_records[0])
        _write_packet(stale_packet, stale_records)
        applied[0]["query"] = "已经变化的问题"
        dataset_path.write_text(json.dumps(applied, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            apply_review_packet(dataset_path, stale_packet, write=True)
        except ValueError as exc:
            assert "stale_case_fingerprint" in str(exc)
            passed += 1
        else:
            raise AssertionError("stale review packet was accepted")

        dataset_path.write_text(json.dumps(original, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        incomplete_packet = root / "incomplete.jsonl"
        export_review_packet(dataset_path, incomplete_packet, candidate_provider=_candidate_provider)
        incomplete = _read_packet(incomplete_packet)
        _approve(incomplete[0])
        incomplete[0]["judgments"].pop()
        _write_packet(incomplete_packet, incomplete)
        try:
            apply_review_packet(dataset_path, incomplete_packet, write=True)
        except ValueError as exc:
            assert "review_judgments_must_cover_candidate_snapshot" in str(exc)
            assert json.loads(dataset_path.read_text(encoding="utf-8")) == original
            passed += 1
        else:
            raise AssertionError("incomplete source judgments were accepted")

        automated_packet = root / "automated.jsonl"
        export_review_packet(dataset_path, automated_packet, candidate_provider=_candidate_provider)
        automated = _read_packet(automated_packet)
        _approve(automated[0])
        automated[0]["reviewer_id"] = "llm"
        _write_packet(automated_packet, automated)
        try:
            apply_review_packet(dataset_path, automated_packet, write=True)
        except ValueError as exc:
            assert "reviewer_id_missing_or_automated" in str(exc)
            passed += 1
        else:
            raise AssertionError("automated reviewer was accepted")

        relabel_packet = root / "relabel.jsonl"
        export_review_packet(dataset_path, relabel_packet, candidate_provider=_candidate_provider)
        relabel = _read_packet(relabel_packet)
        _approve(relabel[0])
        relabel[0]["proposed_labels"]["expected_entity"] = "错误的新实体"
        _write_packet(relabel_packet, relabel)
        try:
            apply_review_packet(dataset_path, relabel_packet, write=True)
        except ValueError as exc:
            assert "review_label_change_requires_reexport" in str(exc)
            passed += 1
        else:
            raise AssertionError("label change was accepted against an old candidate snapshot")

        relevance, unjudged = reviewed_relevance(
            [
                {"source_id": "human-says-zero", "answer_bearing": True, "entity_match": True},
                {"source_id": "not-reviewed", "answer_bearing": True, "entity_match": True},
            ],
            {"human-says-zero": 0},
        )
        assert relevance == [0, 0]
        assert unjudged == 1
        passed += 1

    assert passed == total, (passed, total)
    print(f"history_retrieval_review_smoke={passed}/{total}")
    print("history_retrieval_review_smoke=PASS")


if __name__ == "__main__":
    main()
