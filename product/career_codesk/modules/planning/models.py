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


class PlannerRun(AppendOnlyRecord):
    """Immutable evidence for one pure feasibility calculation.

    The canonical fields intentionally exclude this record's generated ID and
    timestamp, so equivalent inputs retain equivalent feasibility digests.
    """

    input_digest = models.CharField(max_length=64, db_index=True)
    policy_version = models.CharField(max_length=64)
    algorithm_version = models.CharField(max_length=64)
    seed_metadata = models.JSONField(default=dict)
    source_ids = models.JSONField(default=list)
    canonical_input = models.JSONField()
    canonical_result = models.JSONField()
    result_digest = models.CharField(max_length=64, db_index=True)


class InterventionAllocation(DomainRecord):
    STATES = (("proposed", "Proposed"), ("active", "Active"), ("inactive", "Inactive"))

    case_id = models.CharField(max_length=32, db_index=True)
    need = models.ForeignKey(Need, on_delete=models.PROTECT, related_name="allocations")
    hypothesis = models.ForeignKey(
        NeedHypothesis, null=True, blank=True, on_delete=models.PROTECT, related_name="allocations"
    )
    route_code = models.CharField(max_length=64)
    # These are copied from the immutable planner result at proposal time.  They
    # make a proposal independently inspectable when a planner run contains
    # several demands using the same need and route.
    demand_id = models.CharField(max_length=64, default="legacy-unbound")
    resource_id = models.CharField(max_length=64, default="legacy-unbound")
    scheduled_on = models.DateField(null=True, blank=True)
    waiting_days = models.PositiveIntegerField(null=True, blank=True)
    effort_hours = models.PositiveIntegerField(default=1)
    # Zero is the primary plan; positive values select the corresponding
    # persisted feasible alternative.  It is evidence, never a mutable choice.
    plan_variant = models.PositiveIntegerField(default=0)
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="replacement_proposals",
    )
    planner_run_id = models.CharField(max_length=64)
    planner_algorithm_version = models.CharField(max_length=64)
    planner_policy_version = models.CharField(max_length=64)
    state = models.CharField(max_length=16, choices=STATES, default="proposed")
    objects = StateProjectionManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("case_id", "need", "planner_run_id", "demand_id", "plan_variant"),
                name="allocation_planner_binding_once",
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


class WeeklyPlanEntry(AppendOnlyRecord):
    """The immutable, approval-gated execution package for one allocation.

    This deliberately copies the small set of operational facts a weekly plan
    needs to remain inspectable when later planner runs create successor
    proposals.  Source and hypothesis IDs remain links, never rewritten text.
    """

    case_id = models.CharField(max_length=32, db_index=True)
    need = models.ForeignKey(Need, on_delete=models.PROTECT, related_name="weekly_entries")
    decision = models.OneToOneField(
        "decisions.SupportDecision", on_delete=models.PROTECT, related_name="weekly_plan_entry"
    )
    allocation = models.OneToOneField(
        InterventionAllocation, on_delete=models.PROTECT, related_name="weekly_plan_entry"
    )
    planner_run = models.ForeignKey(
        PlannerRun, on_delete=models.PROTECT, related_name="weekly_plan_entries"
    )
    route_code = models.CharField(max_length=64)
    resource_owner_id = models.CharField(max_length=64)
    scheduled_on = models.DateField()
    deadline = models.DateField()
    effort_hours = models.PositiveIntegerField()
    capacity_effect = models.JSONField(default=dict)
    reviewed_capture_ids = models.JSONField(default=list)
    reviewed_hypothesis_ids = models.JSONField(default=list)


class AdviserBrief(AppendOnlyRecord):
    """A deterministic staff brief, not learner-facing generated advice."""

    weekly_entry = models.OneToOneField(
        WeeklyPlanEntry, on_delete=models.PROTECT, related_name="adviser_brief"
    )
    known_facts = models.TextField()
    questions_to_ask = models.TextField()
    assumptions_prohibited = models.TextField()
    intended_outcome = models.TextField()
    source_capture_ids = models.JSONField(default=list)
    provisional_hypothesis_ids = models.JSONField(default=list)
