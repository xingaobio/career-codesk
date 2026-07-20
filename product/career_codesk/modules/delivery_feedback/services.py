"""Persist delivery and learner/adviser outcome feedback without rewriting history."""

from django.db import transaction

from career_codesk.domain import DomainInvariantError
from career_codesk.modules.casework.services import CaseWorkflowService
from career_codesk.modules.intake_provenance.services import case_has_safety_exit
from career_codesk.modules.planning.models import InterventionAllocation

from .models import DeliveryEvent, OutcomeConfirmation


class DeliveryFeedbackService:
    def convention(self):
        from .contracts import DeliveryFeedbackConvention

        return DeliveryFeedbackConvention(feedback_persisted=True, delivery_status="available")

    @transaction.atomic
    def record_delivery(self, *, case_id, allocation, actor_id, result, source):
        allocation = InterventionAllocation.objects.select_for_update().get(pk=allocation.pk)
        canonical_case_id = allocation.case_id
        if canonical_case_id != case_id or allocation.state != "active":
            raise DomainInvariantError("Delivery requires an active allocation for this case")
        if case_has_safety_exit(canonical_case_id):
            raise DomainInvariantError("A safety-exited case cannot record ordinary delivery")
        return DeliveryEvent.objects.create(
            case_id=canonical_case_id,
            allocation=allocation,
            actor_id=actor_id,
            result=result,
            source=source,
        )

    @transaction.atomic
    def record_outcome(self, *, delivery_event, actor_id, response, exact_response):
        if response not in {"helped", "unresolved", "confirmed"}:
            raise DomainInvariantError("Outcome response is invalid")
        delivery_event = DeliveryEvent.objects.select_for_update().get(pk=delivery_event.pk)
        canonical_case_id = delivery_event.case_id
        if case_has_safety_exit(canonical_case_id):
            raise DomainInvariantError("A safety-exited case cannot record ordinary outcomes")
        outcome = OutcomeConfirmation.objects.create(
            case_id=canonical_case_id,
            delivery_event=delivery_event,
            actor_id=actor_id,
            response=response,
            exact_response=exact_response,
        )
        if response == "unresolved":
            CaseWorkflowService().reopen_from_unresolved(
                case_id=canonical_case_id,
                actor_id=actor_id,
                reason="unresolved outcome confirmation",
                outcome_confirmation_id=outcome.id,
            )
        return outcome
