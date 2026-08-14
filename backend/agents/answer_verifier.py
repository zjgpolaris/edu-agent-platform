from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, Field


REQUIRED_EVIDENCE_INTENTS = {"history_search", "textbook_qa", "quiz_generation"}


class VerifiedClaim(BaseModel):
    claim_id: str
    operation: str
    critical: bool = False
    source_ids: list[str] = Field(default_factory=list)
    valid_source_ids: list[str] = Field(default_factory=list)
    invalid_source_ids: list[str] = Field(default_factory=list)
    citation_count: int = 0
    precise_citation_count: int = 0
    supported: bool


class SourceConflict(BaseModel):
    fact_key: str
    values: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class EvidenceVerification(BaseModel):
    schema_version: Literal[1] = 1
    required: bool
    status: Literal["verified", "partial", "not_required", "failed"]
    verification_mode: Literal["deterministic"] = "deterministic"
    completion_allowed: bool
    source_count: int = 0
    citation_count: int = 0
    valid_citation_count: int = 0
    precise_citation_count: int = 0
    supported_claim_count: int = 0
    unsupported_claim_count: int = 0
    critical_claim_count: int = 0
    unsupported_critical_claim_count: int = 0
    citation_validity_rate: float = 0.0
    supported_claim_coverage_rate: float = 0.0
    citation_precision_rate: float = 0.0
    unsupported_critical_claim_rate: float = 0.0
    source_conflict_count: int = 0
    reason_codes: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    claims: list[VerifiedClaim] = Field(default_factory=list)
    source_conflicts: list[SourceConflict] = Field(default_factory=list)


def canonical_source_id(source: dict[str, Any]) -> str:
    """Return the stable ID used by generation and verification contracts."""
    for key in ("source_id", "id", "document_id", "chunk_id"):
        value = source.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()[:96]
    basis = {
        "source": source.get("source") or source.get("title") or source.get("lesson_title"),
        "topic": source.get("topic"),
        "content": source.get("snippet") or source.get("content") or source.get("text"),
    }
    digest = hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"src_{digest[:16]}"


def _source_text(source: dict[str, Any]) -> str:
    return str(source.get("snippet") or source.get("content") or source.get("text") or "").strip()


def _normalized_text(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def citation_supports_claim(claim_text: str, quote: str) -> bool:
    """Conservative lexical entailment check for the deterministic verifier."""
    normalized_claim = _normalized_text(claim_text)
    normalized_quote = _normalized_text(quote)
    if len(normalized_claim) < 2 or len(normalized_quote) < 2:
        return False
    claim_years = set(re.findall(r"(?<!\d)\d{3,4}(?!\d)", claim_text))
    quote_years = set(re.findall(r"(?<!\d)\d{3,4}(?!\d)", quote))
    if claim_years and not claim_years.issubset(quote_years):
        return False
    if normalized_quote in normalized_claim or normalized_claim in normalized_quote:
        return True
    claim_bigrams = {normalized_claim[index:index + 2] for index in range(len(normalized_claim) - 1)}
    quote_bigrams = {normalized_quote[index:index + 2] for index in range(len(normalized_quote) - 1)}
    shared = claim_bigrams & quote_bigrams
    required = 1 if min(len(claim_bigrams), len(quote_bigrams)) <= 3 else 2
    return len(shared) >= required and len(shared) / max(1, min(len(claim_bigrams), len(quote_bigrams))) >= 0.2


def _lesson_sources(lesson: dict[str, Any]) -> list[dict[str, Any]]:
    title = str(lesson.get("lesson_title") or lesson.get("title") or "本课")
    return [
        {
            "source": title,
            "topic": item.get("topic") or title,
            "content": item.get("text") or item.get("content"),
            "source_id": item.get("source_id") or item.get("id"),
            "facts": item.get("facts"),
            "assertions": item.get("assertions"),
            "fact_key": item.get("fact_key"),
            "fact_value": item.get("fact_value"),
        }
        for item in (lesson.get("items") or [])
        if isinstance(item, dict) and str(item.get("text") or item.get("content") or "").strip()
    ]


def _collect_trusted_sources(execution: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Only tool output is trusted; generated copies cannot mint source IDs."""
    deduplicated: dict[str, dict[str, Any]] = {}
    for result in execution.get("tool_results") or []:
        if not isinstance(result, dict) or result.get("ok") is False:
            continue
        data = result.get("data") or {}
        if not isinstance(data, dict):
            continue
        sources = [item for item in (data.get("sources") or []) if isinstance(item, dict)]
        lesson = data.get("lesson")
        if isinstance(lesson, dict):
            sources.extend(_lesson_sources(lesson))
        for source in sources:
            deduplicated.setdefault(canonical_source_id(source), source)
    return deduplicated


def _claim_citations(raw_claim: dict[str, Any]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in raw_claim.get("citations") or []:
        if isinstance(raw, dict):
            source_id = str(raw.get("source_id") or raw.get("id") or "").strip()[:96]
            quote = str(raw.get("quote") or raw.get("supporting_text") or "").strip()[:500]
        else:
            source_id = str(raw or "").strip()[:96]
            quote = ""
        if source_id and source_id not in seen:
            citations.append({"source_id": source_id, "quote": quote})
            seen.add(source_id)
    for raw_id in raw_claim.get("source_ids") or []:
        source_id = str(raw_id or "").strip()[:96]
        if source_id and source_id not in seen:
            citations.append({"source_id": source_id, "quote": ""})
            seen.add(source_id)
    return citations


def _generated_claims(execution: dict[str, Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for generated in execution.get("generation_results") or []:
        if not isinstance(generated, dict):
            continue
        operation = str(generated.get("operation") or "generation")
        data = generated.get("data") or {}
        raw_claims = generated.get("evidence_claims") or (data.get("evidence_claims") if isinstance(data, dict) else None)
        if isinstance(raw_claims, list):
            for raw_claim in raw_claims:
                if isinstance(raw_claim, dict):
                    claims.append({"operation": operation, **raw_claim})
            continue
        has_output = bool(str(generated.get("response") or "").strip() or data)
        if has_output:
            claims.append({
                "claim_id": str(generated.get("step_id") or f"claim_{len(claims) + 1}"),
                "operation": operation,
                "critical": False,
                "citations": generated.get("citations") or (data.get("citations") if isinstance(data, dict) else []) or [],
            })
    return claims


def _quiz_tool_claims(execution: dict[str, Any], trusted_sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for result in execution.get("tool_results") or []:
        if not isinstance(result, dict) or result.get("tool_name") != "generate_quiz" or result.get("ok") is False:
            continue
        questions = (((result.get("data") or {}).get("quiz") or {}).get("questions") or [])
        for index, question in enumerate(questions, start=1):
            if not isinstance(question, dict):
                continue
            citations = []
            for raw_id in question.get("source_item_ids") or []:
                source_id = str(raw_id or "").strip()[:96]
                source = trusted_sources.get(source_id)
                citations.append({"source_id": source_id, "quote": _source_text(source or {})})
            claims.append({
                "claim_id": f"quiz_{question.get('id') or index}",
                "operation": "generate_quiz",
                "critical": False,
                "text": " ".join(str(question.get(key) or "") for key in ("question", "answer", "explanation")),
                "citations": citations,
            })
    return claims


def _quote_is_precise(claim_text: str, quote: str, source: dict[str, Any]) -> bool:
    normalized_quote = _normalized_text(quote)
    normalized_source = _normalized_text(_source_text(source))
    return (
        len(normalized_quote) >= 2
        and normalized_quote in normalized_source
        and citation_supports_claim(claim_text, quote)
    )


def _source_facts(source: dict[str, Any]) -> list[tuple[str, str]]:
    facts: list[tuple[str, str]] = []
    raw_facts = source.get("facts")
    if isinstance(raw_facts, dict):
        facts.extend((str(key).strip(), str(value).strip()) for key, value in raw_facts.items())
    for assertion in source.get("assertions") or []:
        if isinstance(assertion, dict):
            key = str(assertion.get("key") or assertion.get("fact_key") or "").strip()
            value = str(assertion.get("value") or assertion.get("fact_value") or "").strip()
            if key and value:
                facts.append((key, value))
    fact_key = str(source.get("fact_key") or "").strip()
    fact_value = str(source.get("fact_value") or "").strip()
    if fact_key and fact_value:
        facts.append((fact_key, fact_value))
    return [(key[:120], value[:240]) for key, value in facts if key and value]


def _detect_conflicts(trusted_sources: dict[str, dict[str, Any]], cited_source_ids: set[str]) -> list[SourceConflict]:
    observed: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for source_id in cited_source_ids:
        source = trusted_sources.get(source_id)
        if not source:
            continue
        for key, value in _source_facts(source):
            observed[key][value].add(source_id)
    conflicts: list[SourceConflict] = []
    for key, by_value in observed.items():
        if len(by_value) < 2:
            continue
        conflicts.append(SourceConflict(
            fact_key=key,
            values=sorted(by_value),
            source_ids=sorted({source_id for ids in by_value.values() for source_id in ids}),
        ))
    return conflicts


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def verify_answer_evidence(*, intents: list[str], execution: dict[str, Any]) -> EvidenceVerification:
    required = any(intent in REQUIRED_EVIDENCE_INTENTS for intent in intents)
    trusted_sources = _collect_trusted_sources(execution)
    source_ids = list(trusted_sources)

    if not required:
        return EvidenceVerification(
            required=False,
            status="not_required",
            completion_allowed=True,
            source_count=len(source_ids),
            source_ids=source_ids,
        )

    raw_claims = _generated_claims(execution)
    raw_claims.extend(_quiz_tool_claims(execution, trusted_sources))
    claims: list[VerifiedClaim] = []
    total_citations = 0
    valid_citations = 0
    precise_citations = 0
    cited_valid_source_ids: set[str] = set()

    for index, raw_claim in enumerate(raw_claims, start=1):
        citations = _claim_citations(raw_claim)
        claim_text = str(raw_claim.get("text") or raw_claim.get("claim") or "").strip()[:2000]
        citation_source_ids = [item["source_id"] for item in citations]
        valid_ids = [source_id for source_id in citation_source_ids if source_id in trusted_sources]
        invalid_ids = [source_id for source_id in citation_source_ids if source_id not in trusted_sources]
        precise_count = sum(
            1
            for item in citations
            if item["source_id"] in trusted_sources and _quote_is_precise(claim_text, item["quote"], trusted_sources[item["source_id"]])
        )
        total_citations += len(citations)
        valid_citations += len(valid_ids)
        precise_citations += precise_count
        cited_valid_source_ids.update(valid_ids)
        claims.append(VerifiedClaim(
            claim_id=str(raw_claim.get("claim_id") or f"claim_{index}")[:120],
            operation=str(raw_claim.get("operation") or "generation")[:80],
            critical=bool(raw_claim.get("critical")),
            source_ids=citation_source_ids,
            valid_source_ids=valid_ids,
            invalid_source_ids=invalid_ids,
            citation_count=len(citations),
            precise_citation_count=precise_count,
            supported=precise_count > 0 and not invalid_ids,
        ))

    conflicts = _detect_conflicts(trusted_sources, cited_valid_source_ids)
    supported = sum(claim.supported for claim in claims)
    unsupported = len(claims) - supported
    critical = sum(claim.critical for claim in claims)
    unsupported_critical = sum(claim.critical and not claim.supported for claim in claims)
    citation_validity = _rate(valid_citations, total_citations)
    supported_coverage = _rate(supported, len(claims))
    citation_precision = _rate(precise_citations, total_citations)
    unsupported_critical_rate = _rate(unsupported_critical, critical)

    reason_codes: list[str] = []
    if not source_ids:
        reason_codes.append("evidence_missing_sources")
    if not claims:
        reason_codes.append("evidence_missing_claims")
    if total_citations == 0:
        reason_codes.append("evidence_missing_citations")
    if valid_citations < total_citations:
        reason_codes.append("evidence_invalid_source_id")
    if precise_citations < valid_citations:
        reason_codes.append("evidence_citation_not_supported_by_source")
    if unsupported:
        reason_codes.append("evidence_unsupported_claims")
    if unsupported_critical:
        reason_codes.append("evidence_unsupported_critical_claim")
    if conflicts:
        reason_codes.append("evidence_source_conflict")

    completion_allowed = (
        bool(source_ids)
        and bool(claims)
        and total_citations > 0
        and citation_validity == 1.0
        and supported_coverage >= 0.90
        and citation_precision >= 0.95
        and unsupported_critical_rate <= 0.03
        and not conflicts
    )
    if completion_allowed:
        status: Literal["verified", "partial", "failed"] = "verified"
    elif source_ids and claims and (supported > 0 or conflicts):
        status = "partial"
    else:
        status = "failed"
    return EvidenceVerification(
        required=True,
        status=status,
        completion_allowed=completion_allowed,
        source_count=len(source_ids),
        citation_count=total_citations,
        valid_citation_count=valid_citations,
        precise_citation_count=precise_citations,
        supported_claim_count=supported,
        unsupported_claim_count=unsupported,
        critical_claim_count=critical,
        unsupported_critical_claim_count=unsupported_critical,
        citation_validity_rate=citation_validity,
        supported_claim_coverage_rate=supported_coverage,
        citation_precision_rate=citation_precision,
        unsupported_critical_claim_rate=unsupported_critical_rate,
        source_conflict_count=len(conflicts),
        reason_codes=reason_codes,
        source_ids=source_ids,
        claims=claims,
        source_conflicts=conflicts,
    )
