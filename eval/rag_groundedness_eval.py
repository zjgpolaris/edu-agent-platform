"""Offline regression eval for citation coverage and invalid citation detection."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agents.history_character import _history_inspector_diagnosis, _mark_used_sources


SOURCES = [
    {"citation_label": "[史料1]", "snippet": "史料一"},
    {"citation_label": "[史料2]", "snippet": "史料二"},
]


def diagnose(response: str) -> dict:
    sources = _mark_used_sources(response, SOURCES)
    return _history_inspector_diagnosis(
        {"retrieval_strategy": "hybrid"},
        sources,
        response=response,
    )


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def full_citation_coverage() -> None:
    result = diagnose("结论一[史料1]，结论二[史料2]。")
    groundedness = result["citation_groundedness"]
    assert groundedness["grounded"] is True
    assert groundedness["citation_coverage_rate"] == 1.0
    assert result["diagnosis_code"] == "retrieval_ok"


def partial_citation_coverage() -> None:
    result = diagnose("这里只明确使用第一条证据[史料1]。")
    groundedness = result["citation_groundedness"]
    assert groundedness["grounded"] is True
    assert groundedness["citation_coverage_rate"] == 0.5
    assert result["diagnosis_code"] == "partial_citation_coverage"


def uncited_sources_are_reported() -> None:
    result = diagnose("回答没有引用任何史料。")
    assert result["citation_groundedness"]["grounded"] is False
    assert result["diagnosis_code"] == "generation_uncited_sources"
    assert result["failure_stage"] == "generation"


def invented_citation_is_rejected() -> None:
    result = diagnose("回答引用了不存在的证据[史料3]。")
    groundedness = result["citation_groundedness"]
    assert groundedness["grounded"] is False
    assert groundedness["unknown_labels"] == ["[史料3]"]
    assert result["diagnosis_code"] == "generation_invalid_citation"
    assert result["failure_stage"] == "generation"


def main() -> None:
    cases = [
        ("full_citation_coverage", full_citation_coverage),
        ("partial_citation_coverage", partial_citation_coverage),
        ("uncited_sources_are_reported", uncited_sources_are_reported),
        ("invented_citation_is_rejected", invented_citation_is_rejected),
    ]
    passed = sum(1 for name, fn in cases if run_case(name, fn))
    print(f"rag_groundedness={passed}/{len(cases)}")
    print(f"citation_faithfulness={round(passed / len(cases), 4)}")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
