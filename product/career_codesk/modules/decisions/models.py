"""Immutable adviser-owned support decisions and reviewed evidence references."""

from django.db import models

from career_codesk.domain import AppendOnlyRecord
from career_codesk.modules.planning.models import InterventionAllocation


class SupportDecision(AppendOnlyRecord):
    ACTIONS = (("approve", "Approve"), ("amend", "Amend"), ("reject", "Reject"))

    case_id = models.CharField(max_length=32, db_index=True)
    allocation = models.ForeignKey(
        InterventionAllocation, on_delete=models.PROTECT, related_name="support_decisions"
    )
    action = models.CharField(max_length=16, choices=ACTIONS)
    adviser_id = models.CharField(max_length=64)
    reason = models.TextField()
    policy_version = models.CharField(max_length=64)
    planner_version = models.CharField(max_length=64)
    predecessor = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="successors"
    )


class ReviewedInput(AppendOnlyRecord):
    decision = models.ForeignKey(
        SupportDecision, on_delete=models.PROTECT, related_name="reviewed_inputs"
    )
    record_type = models.CharField(max_length=32)
    record_id = models.CharField(max_length=32)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("decision", "record_type", "record_id"), name="decision_reviewed_input_once"
            )
        ]
