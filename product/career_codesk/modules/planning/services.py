"""The narrow lifecycle for deterministic allocation proposals."""

from django.db import transaction

from career_codesk.domain import DomainInvariantError, _authorize_projection_state_change
from career_codesk.modules.ai_gateway.models import NeedHypothesis
from career_codesk.modules.casework.models import Case
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
            hypothesis = NeedHypothesis.objects.get(pk=hypothesis.pk)
            if hypothesis.case_id != case_id:
                raise DomainInvariantError("Allocation hypothesis must belong to the stated case")
        return InterventionAllocation.objects.create(
            case_id=case_id,
            need=need,
            hypothesis=hypothesis,
            route_code=route_code,
            planner_run_id=planner_run_id,
            planner_algorithm_version=planner_algorithm_version,
            planner_policy_version=planner_policy_version,
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
