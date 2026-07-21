"""Operational case projection and immutable transition history."""

from django.db import models

from career_codesk.domain import (
    AppendOnlyRecord,
    DomainInvariantError,
    DomainRecord,
    StateProjectionManager,
    projection_state_change_is_authorized,
)
from career_codesk.modules.intake_provenance.models import Enrolment, Learner


class Case(DomainRecord):
    STATES = (("open", "Open"), ("active", "Active"), ("closed", "Closed"))

    learner = models.ForeignKey(Learner, on_delete=models.PROTECT, related_name="cases")
    enrolment = models.ForeignKey(
        Enrolment, null=True, blank=True, on_delete=models.PROTECT, related_name="cases"
    )
    state = models.CharField(max_length=16, choices=STATES, default="open")
    updated_at = models.DateTimeField(auto_now=True)
    objects = StateProjectionManager()

    def clean(self):
        super().clean()
        if self.enrolment_id and self.enrolment.learner_id != self.learner_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Case enrolment must belong to its learner")

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.full_clean()
        if not self._state.adding:
            original_state = (
                type(self).objects.filter(pk=self.pk).values_list("state", flat=True).get()
            )
            if original_state != self.state and not projection_state_change_is_authorized():
                raise DomainInvariantError("Case state must be changed through CaseWorkflowService")
        return super().save(*args, **kwargs)


class CaseTransition(AppendOnlyRecord):
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="transitions")
    from_state = models.CharField(max_length=16)
    to_state = models.CharField(max_length=16)
    actor_id = models.CharField(max_length=64)
    actor_type = models.CharField(max_length=32, default="adviser")
    reason = models.TextField()
    unresolved_outcome = models.ForeignKey(
        "delivery_feedback.OutcomeConfirmation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reopen_transitions",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=~models.Q(from_state=models.F("to_state")), name="case_state_changes"
            )
        ]


class CaseReviewRequest(AppendOnlyRecord):
    """Append-only evidence that feedback requires staff review.

    It exists for already-open cases where a same-state transition would be
    misleading, and avoids manufacturing a CaseTransition merely for audit UI.
    """

    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="review_requests")
    feedback_id = models.CharField(max_length=32, unique=True)
    reason = models.TextField()
    actor_id = models.CharField(max_length=64)
