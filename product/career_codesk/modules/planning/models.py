"""Versioned non-clinical taxonomy and deterministic allocation proposals."""

from django.db import models

from career_codesk.domain import (
    AppendOnlyRecord,
    DomainInvariantError,
    DomainRecord,
    StateProjectionManager,
    projection_state_change_is_authorized,
)
from career_codesk.modules.ai_gateway.models import NeedHypothesis


class Need(AppendOnlyRecord):
    taxonomy_code = models.CharField(max_length=64)
    taxonomy_version = models.CharField(max_length=64)
    permitted_routes = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("taxonomy_code", "taxonomy_version"), name="need_taxonomy_version_once"
            )
        ]


class InterventionAllocation(DomainRecord):
    STATES = (("proposed", "Proposed"), ("active", "Active"), ("inactive", "Inactive"))

    case_id = models.CharField(max_length=32, db_index=True)
    need = models.ForeignKey(Need, on_delete=models.PROTECT, related_name="allocations")
    hypothesis = models.ForeignKey(
        NeedHypothesis, null=True, blank=True, on_delete=models.PROTECT, related_name="allocations"
    )
    route_code = models.CharField(max_length=64)
    planner_run_id = models.CharField(max_length=64)
    planner_algorithm_version = models.CharField(max_length=64)
    planner_policy_version = models.CharField(max_length=64)
    state = models.CharField(max_length=16, choices=STATES, default="proposed")
    objects = StateProjectionManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("case_id", "need", "planner_run_id"),
                name="allocation_planner_proposal_once",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original_state = (
                type(self).objects.filter(pk=self.pk).values_list("state", flat=True).get()
            )
            if original_state != self.state and not projection_state_change_is_authorized():
                raise DomainInvariantError(
                    "Allocation state must be changed through AllocationService"
                )
        return super().save(*args, **kwargs)
