"""Transactional state transitions for an operational case projection."""

from django.db import transaction

from career_codesk.domain import DomainInvariantError, _authorize_projection_state_change
from career_codesk.identity import SimulatedActor, is_canonical_simulated_adviser
from career_codesk.modules.intake_provenance.services import case_has_safety_exit

from .models import Case, CaseTransition


class CaseWorkflowService:
    _TRANSITIONS = {
        "open": {"active", "closed"},
        "active": {"closed"},
        "closed": {"open"},
    }

    def convention(self):
        from .contracts import CaseworkConvention

        return CaseworkConvention(records_persisted=True, workflow_status="available")

    @transaction.atomic
    def transition(self, case_id, to_state, actor: SimulatedActor, reason):
        if not is_canonical_simulated_adviser(actor):
            raise DomainInvariantError("Only the simulated adviser may move a case manually")
        case = Case.objects.select_for_update().get(pk=case_id)
        if case_has_safety_exit(case_id):
            raise DomainInvariantError("A safety-exited case cannot move in the ordinary workflow")
        self._assert_transition(case.state, to_state)
        CaseTransition.objects.create(
            case=case,
            from_state=case.state,
            to_state=to_state,
            actor_id=actor.id,
            actor_type=actor.role,
            reason=reason,
        )
        self._set_state(case, to_state)
        return case

    @transaction.atomic
    def reopen_from_unresolved(self, *, case_id, actor_id, reason, outcome_confirmation_id):
        from career_codesk.modules.delivery_feedback.models import OutcomeConfirmation

        case = Case.objects.select_for_update().get(pk=case_id)
        outcome = (
            OutcomeConfirmation.objects.select_for_update()
            .select_related("delivery_event")
            .get(pk=outcome_confirmation_id)
        )
        if (
            outcome.response != "unresolved"
            or outcome.case_id != case.id
            or outcome.delivery_event.case_id != case.id
        ):
            raise DomainInvariantError("Reopening requires an unresolved outcome for this case")
        if CaseTransition.objects.filter(unresolved_outcome=outcome).exists():
            raise DomainInvariantError("An unresolved outcome may reopen a case only once")
        if case_has_safety_exit(case_id):
            raise DomainInvariantError(
                "A safety-exited case cannot reopen in the ordinary workflow"
            )
        if case.state != "closed":
            raise DomainInvariantError("An unresolved outcome can only reopen a closed case")
        CaseTransition.objects.create(
            case=case,
            from_state="closed",
            to_state="open",
            actor_id=actor_id,
            actor_type="automated_feedback",
            reason=reason,
            unresolved_outcome=outcome,
        )
        self._set_state(case, "open")
        return case

    @staticmethod
    def _set_state(case, to_state):
        with _authorize_projection_state_change():
            case.state = to_state
            case.save(update_fields=("state", "updated_at"))

    def _assert_transition(self, from_state, to_state):
        if to_state not in self._TRANSITIONS.get(from_state, set()):
            raise DomainInvariantError(f"Invalid case transition: {from_state} -> {to_state}")
