from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from agent_runtime.models import AgentRunState, CompletionDecision


class CompletionEvaluator:
    """The only component allowed to turn execution results into terminal semantics."""

    def from_outcome(
        self,
        *,
        status: Literal["completed", "partial", "waiting_input", "waiting_confirmation", "failed", "cancelled"],
        completed_steps: int,
        total_steps: int,
        verification_status: Literal["verified", "partial", "failed", "not_required"],
        reason_codes: list[str],
        deliverable_refs: list[str] | None = None,
        unresolved_items: list[str] | None = None,
        completion_allowed: bool | None = None,
    ) -> CompletionDecision:
        """Normalize a product adapter's already-evaluated outcome.

        Product-specific graphs may have stronger rubric or human-review
        semantics than the generic step evaluator.  They still delegate the
        final CompletionDecision construction and invariant checks here.
        """
        allowed = status == "completed" if completion_allowed is None else completion_allowed
        return CompletionDecision(
            status=status,
            completion_allowed=allowed,
            completed_steps=completed_steps,
            total_steps=total_steps,
            verification_status=verification_status,
            reason_codes=list(dict.fromkeys(reason_codes)),
            deliverable_refs=list(dict.fromkeys(deliverable_refs or [])),
            unresolved_items=list(dict.fromkeys(unresolved_items or [])),
        )

    def evaluate(
        self,
        state: AgentRunState,
        *,
        evidence_required: bool = False,
        known_source_ids: Iterable[str] = (),
        source_conflict: bool = False,
        verifier_error: bool = False,
        policy_error: bool = False,
        deliverable_refs: list[str] | None = None,
    ) -> CompletionDecision:
        results = list(state.step_results.values())
        total_steps = len(state.plan.steps) if state.plan else len(results)
        completed_steps = sum(result.status in {"completed", "degraded"} for result in results)
        refs = list(deliverable_refs or [])
        unresolved: list[str] = []
        reasons: list[str] = []

        waiting_input = next((item for item in results if item.status == "waiting_input"), None)
        if waiting_input:
            return CompletionDecision(
                status="waiting_input",
                completion_allowed=False,
                completed_steps=completed_steps,
                total_steps=total_steps,
                verification_status="not_required",
                reason_codes=["waiting_input"],
                deliverable_refs=refs,
                unresolved_items=[waiting_input.step_id],
            )
        waiting_confirmation = next((item for item in results if item.status == "waiting_confirmation"), None)
        if waiting_confirmation:
            return CompletionDecision(
                status="waiting_confirmation",
                completion_allowed=False,
                completed_steps=completed_steps,
                total_steps=total_steps,
                verification_status="not_required",
                reason_codes=["waiting_confirmation"],
                deliverable_refs=refs,
                unresolved_items=[waiting_confirmation.step_id],
            )
        if state.status == "cancelled" or any(item.status == "cancelled" for item in results):
            return CompletionDecision(
                status="cancelled",
                completion_allowed=False,
                completed_steps=completed_steps,
                total_steps=total_steps,
                verification_status="not_required",
                reason_codes=["run_cancelled"],
                deliverable_refs=refs,
            )

        known_sources = set(known_source_ids)
        evidence_claims = [claim for result in results for claim in result.evidence_claims]
        source_ids = {source_id for result in results for source_id in result.source_ids}
        source_ids.update(source_id for claim in evidence_claims for source_id in claim.source_ids)
        unknown_sources = sorted(source_ids - known_sources) if known_sources else []
        critical_without_source = [claim.claim_id for claim in evidence_claims if claim.critical and not claim.source_ids]

        if verifier_error:
            reasons.append("verifier_error")
        if policy_error:
            reasons.append("policy_error")
        if source_conflict:
            reasons.append("source_conflict")
        if unknown_sources:
            reasons.append("unknown_source_id")
            unresolved.extend(unknown_sources)
        if evidence_required and not source_ids:
            reasons.append("required_evidence_missing")
        if critical_without_source:
            reasons.append("critical_claim_unsupported")
            unresolved.extend(critical_without_source)

        failed_steps = [result.step_id for result in results if result.status == "failed"]
        partial_steps = [result.step_id for result in results if result.status in {"partial", "degraded"}]
        unresolved.extend(failed_steps + partial_steps)
        hard_failure = bool(verifier_error or policy_error or unknown_sources or critical_without_source)
        missing_required_evidence = evidence_required and not source_ids

        if hard_failure or (missing_required_evidence and not refs):
            status = "partial" if refs or completed_steps else "failed"
            return CompletionDecision(
                status=status,
                completion_allowed=False,
                completed_steps=completed_steps,
                total_steps=total_steps,
                verification_status="failed",
                reason_codes=reasons or ["execution_failed"],
                deliverable_refs=refs,
                unresolved_items=list(dict.fromkeys(unresolved)),
            )
        if source_conflict or missing_required_evidence or failed_steps or partial_steps or completed_steps < total_steps:
            if source_conflict and "source_conflict" not in reasons:
                reasons.append("source_conflict")
            if failed_steps and "step_failed" not in reasons:
                reasons.append("step_failed")
            if completed_steps < total_steps and "plan_incomplete" not in reasons:
                reasons.append("plan_incomplete")
            return CompletionDecision(
                status="partial" if refs or completed_steps else "failed",
                completion_allowed=False,
                completed_steps=completed_steps,
                total_steps=total_steps,
                verification_status="partial" if source_ids else ("failed" if evidence_required else "not_required"),
                reason_codes=reasons,
                deliverable_refs=refs,
                unresolved_items=list(dict.fromkeys(unresolved)),
            )

        return CompletionDecision(
            status="completed",
            completion_allowed=True,
            completed_steps=completed_steps,
            total_steps=total_steps,
            verification_status="verified" if evidence_required else "not_required",
            reason_codes=["completion_criteria_satisfied"],
            deliverable_refs=refs,
        )
