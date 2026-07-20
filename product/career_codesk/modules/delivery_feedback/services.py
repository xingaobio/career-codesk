"""Persist delivery and learner/adviser outcome feedback without rewriting history."""

from django.db import transaction

from career_codesk.domain import DomainInvariantError
from career_codesk.modules.casework.services import CaseWorkflowService
from career_codesk.modules.intake_provenance.models import NeedCapture
from career_codesk.modules.intake_provenance.services import CaptureService, case_has_safety_exit
from career_codesk.modules.planning.models import InterventionAllocation, WeeklyPlanEntry

from .models import DeliveryEvent, LearnerActionFeedback, OutcomeConfirmation


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

    @transaction.atomic
    def record_learner_feedback(
        self,
        *,
        weekly_entry,
        actor_id,
        kind,
        exact_response,
        correction_statement=None,
    ):
        """Record a simulated learner response against one currently approved action."""
        if kind not in {"helped", "unresolved", "human_help", "correction"}:
            raise DomainInvariantError("Learner feedback kind is invalid")
        entry = (
            WeeklyPlanEntry.objects.select_for_update()
            .select_related("allocation", "decision")
            .get(pk=weekly_entry.pk)
        )
        if (
            entry.allocation.state != "active"
            or entry.decision.action != "approve"
            or entry.decision.allocation_id != entry.allocation_id
            or case_has_safety_exit(entry.case_id)
        ):
            raise DomainInvariantError("Feedback requires one currently approved ordinary action")
        correction = None
        if kind == "correction":
            if not correction_statement or not correction_statement.strip():
                raise DomainInvariantError("A correction request needs a source statement")
            original_id = next(iter(entry.reviewed_capture_ids), None)
            original = NeedCapture.objects.filter(pk=original_id, case_id=entry.case_id).first()
            if original is None:
                raise DomainInvariantError("A correction requires a reviewed source capture")
            correction = CaptureService().correct(
                original,
                source_payload={"statement": correction_statement.strip()},
                source_version="learner-correction-v1",
            )
        feedback = LearnerActionFeedback.objects.create(
            case_id=entry.case_id,
            weekly_entry=entry,
            actor_id=actor_id,
            kind=kind,
            exact_response=exact_response.strip() or kind.replace("_", " "),
            correction_capture=correction,
        )
        if kind in {"helped", "unresolved"}:
            delivery = DeliveryEvent.objects.create(
                case_id=entry.case_id,
                allocation=entry.allocation,
                actor_id=actor_id,
                result="learner_action_response",
                source="local learner next-action page",
            )
            OutcomeConfirmation.objects.create(
                case_id=entry.case_id,
                delivery_event=delivery,
                actor_id=actor_id,
                response=kind,
                exact_response=feedback.exact_response,
            )
        if kind in {"unresolved", "human_help", "correction"}:
            CaseWorkflowService().open_review_from_feedback(
                case_id=entry.case_id,
                actor_id=actor_id,
                reason=f"learner {kind.replace('_', ' ')} feedback",
                feedback_id=feedback.id,
            )
        return feedback
