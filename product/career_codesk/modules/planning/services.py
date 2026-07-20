"""The narrow lifecycle for deterministic allocation proposals."""

from django.db import transaction

from career_codesk.domain import DomainInvariantError, _authorize_projection_state_change
from career_codesk.modules.ai_gateway.contracts import (
    AiRequest,
    SourceReference,
    canonical_digest,
    canonical_request_digest,
    payload_errors,
    validate_request,
)
from career_codesk.modules.ai_gateway.models import NeedHypothesis
from career_codesk.modules.casework.models import Case
from career_codesk.modules.intake_provenance.models import NeedCapture
from career_codesk.modules.intake_provenance.services import case_has_safety_exit

from .models import InterventionAllocation, Need


class AllocationService:
    @transaction.atomic
    def propose(
        self,
        *,
        case_id,
        need,
        route_code,
        planner_run_id,
        planner_algorithm_version,
        planner_policy_version,
        hypothesis=None,
    ):
        if not Case.objects.filter(pk=case_id).exists():
            raise DomainInvariantError("An allocation must belong to an existing case")
        if case_has_safety_exit(case_id):
            raise DomainInvariantError("A safety-exited case cannot receive an allocation")
        need = Need.objects.select_for_update().get(pk=need.pk)
        if route_code not in need.permitted_routes:
            raise DomainInvariantError("Allocation route is not permitted by the need taxonomy")
        if hypothesis:
            hypothesis = NeedHypothesis.objects.select_related("gateway_output__attempt").get(
                pk=hypothesis.pk
            )
            if hypothesis.case_id != case_id:
                raise DomainInvariantError("Allocation hypothesis must belong to the stated case")
            self._require_validated_gateway_hypothesis(hypothesis, case_id)
        return InterventionAllocation.objects.create(
            case_id=case_id,
            need=need,
            hypothesis=hypothesis,
            route_code=route_code,
            planner_run_id=planner_run_id,
            planner_algorithm_version=planner_algorithm_version,
            planner_policy_version=planner_policy_version,
        )

    @staticmethod
    def _require_validated_gateway_hypothesis(hypothesis, case_id):
        """Reject legacy or manually-created hypotheses at the planning boundary.

        ``NeedHypothesis`` is append-only but can still be inserted through the
        ORM.  Planning therefore independently verifies the immutable gateway
        output instead of trusting the relation merely because it is present.
        """
        output = hypothesis.gateway_output
        if output is None:
            raise DomainInvariantError("Allocation hypotheses require validated gateway evidence")
        attempt = output.attempt
        expected_payload = {
            "tags": hypothesis.tags,
            "explanation": hypothesis.explanation,
            "unknowns": hypothesis.unknowns,
            "confidence": "high",
        }
        input_ids = list(hypothesis.inputs.values_list("capture_id", flat=True))
        source_ids = attempt.source_record_ids
        try:
            persisted_request = AiRequest(
                task_kind=attempt.task_kind,
                source_records=tuple(
                    SourceReference(**source) for source in attempt.source_records
                ),
                input_metadata=attempt.input_metadata,
                prompt_version=attempt.prompt_version,
                output_schema_version=attempt.output_schema_version,
                policy_version=attempt.policy_version,
            )
            validate_request(persisted_request)
        except (DomainInvariantError, TypeError) as error:
            raise DomainInvariantError("Allocation gateway request evidence is invalid") from error
        source_captures = {
            capture.id: capture for capture in NeedCapture.objects.filter(pk__in=source_ids)
        }
        expected_source_records = [
            {
                "record_id": source_id,
                "record_type": "need_capture",
                "source_version": source_captures[source_id].source_version,
            }
            for source_id in source_ids
            if source_id in source_captures
        ]
        expected_metadata = {"case_id": case_id, "capture_ids": source_ids}
        provenance_matches = (
            hypothesis.output_schema_version == attempt.output_schema_version
            and hypothesis.prompt_version == attempt.prompt_version
            and hypothesis.model_version == attempt.model_version
            and hypothesis.gateway_policy_version == attempt.policy_version
            and hypothesis.adapter_version == attempt.adapter_version
        )
        if (
            hypothesis.status != "provisional"
            or hypothesis.confidence_state != "high"
            or attempt.task_kind not in {"intake_interpretation", "need_hypothesis"}
            or attempt.disposition != "provisional_output"
            or output.authority != "provisional_no_decision_authority"
            or output.confidence != "high"
            or output.validated_payload != expected_payload
            or output.output_digest != canonical_digest(expected_payload)
            or output.validation_errors
            or hypothesis.unknowns
            or payload_errors(attempt.task_kind, output.validated_payload)
            or not input_ids
            or len(input_ids) != len(set(input_ids))
            or len(source_ids) != len(set(source_ids))
            or source_ids != [source.record_id for source in persisted_request.source_records]
            or set(input_ids) != set(source_ids)
            or len(source_captures) != len(source_ids)
            or any(
                capture.case_id != case_id or not capture.field_allowlist_passed
                for capture in source_captures.values()
            )
            or attempt.source_records != expected_source_records
            or attempt.input_metadata != expected_metadata
            or attempt.input_digest != canonical_request_digest(persisted_request)
            or not provenance_matches
        ):
            raise DomainInvariantError(
                "Allocation hypotheses must exactly match high-confidence "
                "validated gateway evidence"
            )

    @transaction.atomic
    def activate_for_approval(self, allocation, decision):
        from career_codesk.modules.decisions.models import SupportDecision

        allocation = InterventionAllocation.objects.select_for_update().get(pk=allocation.pk)
        decision = SupportDecision.objects.select_for_update().get(pk=decision.pk)
        if (
            decision.action != "approve"
            or decision.allocation_id != allocation.id
            or decision.case_id != allocation.case_id
        ):
            raise DomainInvariantError(
                "Only the matching approved decision can activate an allocation"
            )
        if case_has_safety_exit(allocation.case_id):
            raise DomainInvariantError("A safety-exited case cannot activate an allocation")
        if allocation.state != "proposed":
            raise DomainInvariantError("Only a proposed allocation can become active")
        self._set_state(allocation, "active")
        return allocation

    @transaction.atomic
    def retire_for_review(self, allocation, decision):
        """Make a later adviser amendment or rejection operationally effective.

        The immutable decision remains the audit record; the proposal projection is
        retired so an earlier approval cannot continue to authorise delivery.
        """
        from career_codesk.modules.decisions.models import SupportDecision

        allocation = InterventionAllocation.objects.select_for_update().get(pk=allocation.pk)
        decision = SupportDecision.objects.select_for_update().get(pk=decision.pk)
        if (
            decision.action not in {"amend", "reject"}
            or decision.allocation_id != allocation.id
            or decision.case_id != allocation.case_id
        ):
            raise DomainInvariantError(
                "Only a matching amendment or rejection can retire an allocation"
            )
        if allocation.state != "inactive":
            self._set_state(allocation, "inactive")
        return allocation

    @staticmethod
    def _set_state(allocation, state):
        with _authorize_projection_state_change():
            allocation.state = state
            allocation.save(update_fields=("state",))
