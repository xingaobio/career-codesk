"""Local mock writeback audit records; no external integration is represented."""

from django.db import models

from career_codesk.domain import AppendOnlyRecord
from career_codesk.modules.decisions.models import SupportDecision
from career_codesk.modules.planning.models import InterventionAllocation


class WritebackAttempt(AppendOnlyRecord):
    RESULTS = (
        ("pending", "Pending"),
        ("succeeded", "Succeeded locally"),
        ("failed", "Failed"),
        ("not_sent", "Not sent"),
    )

    allocation = models.ForeignKey(
        InterventionAllocation, on_delete=models.PROTECT, related_name="writeback_attempts"
    )
    decision = models.ForeignKey(
        SupportDecision, on_delete=models.PROTECT, related_name="writeback_attempts"
    )
    idempotency_key = models.CharField(max_length=128)
    payload_version = models.CharField(max_length=32)
    payload_digest = models.CharField(max_length=64)
    attempt_number = models.PositiveIntegerField()
    result = models.CharField(max_length=16, choices=RESULTS)
    failure_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("allocation", "payload_version", "attempt_number"),
                name="writeback_attempt_number_once",
            )
        ]
