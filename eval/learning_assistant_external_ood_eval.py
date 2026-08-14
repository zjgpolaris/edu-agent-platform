"""Aggregate-only probe over an external, human-authored student corpus.

The initial supported input is Eedi Question-Anchored-Tutoring-Dialogues-2k.
Raw messages and local paths are never printed or copied into the repository.
This probe measures only out-of-domain tool-routing safety; it does not count as
Chinese in-domain blind evidence or real-LLM evidence.
"""
from __future__ import annotations

import csv
import hashlib
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agents.learning_assistant_router import IntentName, deterministic_route


MINIMUM_CASES = 200
MAXIMUM_CASES = 10_000
MINIMUM_PRECISION = 0.95


def _dataset_path() -> Path | None:
    configured = os.getenv("EDU_AGENT_EXTERNAL_OOD_PATH")
    if not configured:
        return None
    path = Path(configured).expanduser().resolve()
    if ROOT == path or ROOT in path.parents:
        raise RuntimeError("external_ood_dataset_must_be_outside_repository")
    if not path.is_file():
        raise RuntimeError("external_ood_dataset_not_available")
    return path


def _load_unique_student_messages(path: Path) -> list[str]:
    messages: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"IsTutor", "MessageString"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise RuntimeError("external_ood_dataset_schema_invalid")
        for row in reader:
            if str(row.get("IsTutor", "")).strip() != "0":
                continue
            message = re.sub(r"\s+", " ", str(row.get("MessageString") or "")).strip()
            normalized = message.casefold()
            if len(message) < 2 or normalized in seen:
                continue
            seen.add(normalized)
            messages.append(message)
            if len(messages) >= MAXIMUM_CASES:
                break
    if len(messages) < MINIMUM_CASES:
        raise RuntimeError("external_ood_dataset_below_minimum_size")
    return messages


def main() -> None:
    try:
        path = _dataset_path()
        if path is None:
            print("SKIP learning_assistant_external_ood_eval: external_ood_dataset_not_configured")
            return
        messages = _load_unique_student_messages(path)
    except RuntimeError as exc:
        allowed = {
            "external_ood_dataset_must_be_outside_repository",
            "external_ood_dataset_not_available",
            "external_ood_dataset_schema_invalid",
            "external_ood_dataset_below_minimum_size",
        }
        code = str(exc) if str(exc) in allowed else "external_ood_dataset_invalid"
        print("FAIL external_ood_aggregate")
        print(f"external_ood_dataset_error={code}")
        raise SystemExit(1)

    safe = 0
    unsafe = 0
    for message in messages:
        route = deterministic_route({"message": message})
        if all(task.intent == IntentName.chat for task in route.tasks):
            safe += 1
        else:
            unsafe += 1

    total = len(messages)
    precision = safe / total
    dataset_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    print("external_ood_source=eedi_qatd_2k_test")
    print("external_ood_license=cc_by_nc_metadata_card_mentions_cc_by_nc_sa")
    print(f"external_ood_dataset_sha256={dataset_hash}")
    print(f"external_ood_case_count={total}")
    print(f"external_ood_safe_routes={safe}/{total}")
    print(f"external_ood_precision={precision:.4f}")
    print(f"external_ood_unsafe_tool_routes={unsafe}")
    if precision < MINIMUM_PRECISION:
        print("FAIL external_ood_precision_threshold")
        raise SystemExit(1)
    print("OK external_ood_tool_routing_safety")
    print("learning_assistant_external_ood_eval=1/1")


if __name__ == "__main__":
    main()
