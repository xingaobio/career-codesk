"""Consequential decisions have one writer: the simulated adviser."""

from django.db import transaction

from career_codesk.domain import DomainInvariantError
from career_codesk.identity import SimulatedActor, is_canonical_simulated_adviser
from career_codesk.modules.ai_gateway.models import NeedHypothesis
from career_codesk.modules.intake_provenance.models import NeedCapture
from career_codesk.modules.intake_provenance.services import case_has_safety_exit
from career_codesk.modules.planning.models import InterventionAllocation
from career_codesk.modules.planning.services import AllocationService

from .models import ReviewedInput, SupportDecision


class SupportDecisionService:
    def convention(self):
        return {"decision_events_persisted": True, "adviser_only": True}

    @transaction.atomic
    def record(
        self,
        *,
        case_id,
        allocation,
        action,
        actor: SimulatedActor,
        reason,
        reviewed_inputs,
        policy_version,
        planner_version,
        predecessor=None,
    ):
        if action not in {"approve", "amend", "reject"}:
            raise DomainInvariantError("Support decision action is invalid")
        if not is_canonical_simulated_adviser(actor):
            raise DomainInvariantError("Only the simulated adviser may record a support decision")
        allocation = InterventionAllocation.objects.select_for_update().get(pk=allocation.pk)
        canonical_case_id = allocation.case_id
        if canonical_case_id != case_id:
            raise DomainInvariantError("Decision allocation must belong to the stated case")
        if case_has_safety_exit(canonical_case_id):
            raise DomainInvariantError("A safety-exited case cannot receive a support decision")
        if action in {"amend", "reject"} and predecessor is None:
            raise DomainInvariantError("An amendment or rejection must supersede a decision")
        if action == "approve" and predecessor is not None:
            raise DomainInvariantError("An approval must start a decision history")
        if predecessor is not None:
            predecessor = SupportDecision.objects.select_for_update().get(pk=predecessor.pk)
            if (
                predecessor.case_id != canonical_case_id
                or predecessor.allocation_id != allocation.id
            ):
                raise DomainInvariantError("A decision predecessor must describe the same proposal")
            if predecessor.successors.exists():
                raise DomainInvariantError("A decision predecessor already has a successor")
        decision = SupportDecision.objects.create(
            case_id=canonical_case_id,
            allocation=allocation,
            action=action,
            adviser_id=actor.id,
            reason=reason,
            policy_version=policy_version,
            planner_version=planner_version,
            predecessor=predecessor,
        )
        reviewed_inputs = tuple(reviewed_inputs)
        if not reviewed_inputs:
            raise DomainInvariantError("A support decision must identify reviewed evidence")
        for kind, record_id in reviewed_inputs:
            if kind == "capture":
                valid = NeedCapture.objects.filter(pk=record_id, case_id=canonical_case_id).exists()
            elif kind == "hypothesis":
                valid = NeedHypothesis.objects.filter(
                    pk=record_id, case_id=canonical_case_id
                ).exists()
            else:
                valid = False
            if not valid:
                raise DomainInvariantError(
                    "Reviewed evidence must be an exact record for this case"
                )
        ReviewedInput.objects.bulk_create(
            [
                ReviewedInput(decision=decision, record_type=kind, record_id=record_id)
                for kind, record_id in reviewed_inputs
            ]
        )
        if action == "approve":
            AllocationService().activate_for_approval(allocation, decision)
        else:
            AllocationService().retire_for_review(allocation, decision)
        return decision
