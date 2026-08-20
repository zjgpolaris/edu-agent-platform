from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel


class SideEffectRecord(BaseModel):
    step_id: str
    operation: str
    idempotency_key: str
    status: Literal["started", "committed", "unknown", "failed"]
    resource_ref: str | None = None
    committed_at: str | None = None


class SideEffectLedger:
    def __init__(self, records: list[SideEffectRecord] | None = None) -> None:
        self._records = {record.idempotency_key: record for record in records or []}

    @classmethod
    def from_json(cls, payload: list[dict] | None) -> "SideEffectLedger":
        return cls([SideEffectRecord.model_validate(item) for item in payload or []])

    def is_committed(self, idempotency_key: str) -> bool:
        record = self._records.get(idempotency_key)
        return bool(record and record.status == "committed")

    def start(self, *, step_id: str, operation: str, idempotency_key: str) -> SideEffectRecord:
        existing = self._records.get(idempotency_key)
        if existing:
            return existing
        record = SideEffectRecord(
            step_id=step_id,
            operation=operation,
            idempotency_key=idempotency_key,
            status="started",
        )
        self._records[idempotency_key] = record
        return record

    def commit(self, idempotency_key: str, resource_ref: str | None = None) -> SideEffectRecord:
        record = self._records[idempotency_key]
        record = record.model_copy(update={
            "status": "committed",
            "resource_ref": resource_ref,
            "committed_at": datetime.now(timezone.utc).isoformat(),
        })
        self._records[idempotency_key] = record
        return record

    def mark_unknown(self, idempotency_key: str) -> SideEffectRecord:
        record = self._records[idempotency_key].model_copy(update={"status": "unknown"})
        self._records[idempotency_key] = record
        return record

    def model_dump(self) -> list[dict]:
        return [record.model_dump() for record in self._records.values()]
