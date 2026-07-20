"""Append-only simulated delivery and outcome evidence."""

from django.db import models

from career_codesk.domain import AppendOnlyRecord
from career_codesk.modules.planning.models import InterventionAllocation


class DeliveryEvent(AppendOnlyRecord):
    case_id = models.CharField(max_length=32, db_index=True)
    allocation = models.ForeignKey(
        InterventionAllocation, on_delete=models.PROTECT, related_name="delivery_events"
    )
    actor_id = models.CharField(max_length=64)
    result = models.CharField(max_length=64)
    source = models.CharField(max_length=64)


class OutcomeConfirmation(AppendOnlyRecord):
    RESPONSES = (("helped", "Helped"), ("unresolved", "Unresolved"), ("confirmed", "Confirmed"))

    case_id = models.CharField(max_length=32, db_index=True)
    delivery_event = models.ForeignKey(
        DeliveryEvent, on_delete=models.PROTECT, related_name="outcome_confirmations"
    )
    actor_id = models.CharField(max_length=64)
    response = models.CharField(max_length=16, choices=RESPONSES)
    exact_response = models.TextField()


class LearnerActionFeedback(AppendOnlyRecord):
    """A local learner-page response; it never edits delivery or source history."""

    KINDS = (
        ("helped", "Helped"),
        ("unresolved", "Unresolved"),
        ("human_help", "Human help requested"),
        ("correction", "Correction requested"),
    )

    case_id = models.CharField(max_length=32, db_index=True)
    weekly_entry = models.ForeignKey(
        "planning.WeeklyPlanEntry", on_delete=models.PROTECT, related_name="learner_feedback"
    )
    actor_id = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=KINDS)
    exact_response = models.TextField()
    correction_capture = models.ForeignKey(
        "intake_provenance.NeedCapture",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="learner_feedback_corrections",
    )
