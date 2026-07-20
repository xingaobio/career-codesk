"""Local mock writeback audit records; no external integration is represented."""

from django.db import models

from career_codesk.domain import AppendOnlyRecord
from career_codesk.modules.decisions.models import SupportDecision
from career_codesk.modules.planning.models import InterventionAllocation


class StructuredExport(AppendOnlyRecord):
    """Canonical local-only mock export produced from one weekly plan entry."""

    weekly_entry = models.OneToOneField(
        "planning.WeeklyPlanEntry", on_delete=models.PROTECT, related_name="structured_export"
    )
    allocation = models.ForeignKey(
        InterventionAllocation, on_delete=models.PROTECT, related_name="structured_exports"
    )
    decision = models.ForeignKey(
        SupportDecision, on_delete=models.PROTECT, related_name="structured_exports"
    )
    destination = models.CharField(max_length=64, default="local-mock-outbox")
    payload_version = models.CharField(max_length=32)
    canonical_payload = models.JSONField()
    payload_digest = models.CharField(max_length=64, db_index=True)
    idempotency_key = models.CharField(max_length=128, unique=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("decision", "allocation", "payload_version"),
                name="structured_export_approval_once",
            )
        ]


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
    structured_export = models.ForeignKey(
        StructuredExport,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="attempts",
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
