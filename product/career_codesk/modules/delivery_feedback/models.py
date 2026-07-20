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
