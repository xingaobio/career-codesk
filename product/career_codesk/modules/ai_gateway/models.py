"""Provisional machine interpretation with immutable exact source inputs."""

from django.db import models

from career_codesk.domain import AppendOnlyRecord
from career_codesk.modules.intake_provenance.models import NeedCapture


class NeedHypothesis(AppendOnlyRecord):
    case_id = models.CharField(max_length=32, db_index=True)
    tags = models.JSONField(default=list)
    explanation = models.TextField()
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    unknowns = models.JSONField(default=list)
    output_schema_version = models.CharField(max_length=32)
    gateway_policy_version = models.CharField(max_length=64)
    adapter_version = models.CharField(max_length=64)
    status = models.CharField(default="provisional", max_length=32)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(confidence__isnull=True)
                | (models.Q(confidence__gte=0) & models.Q(confidence__lte=1)),
                name="hypothesis_confidence_in_range",
            ),
            models.CheckConstraint(
                check=models.Q(status="provisional"), name="hypothesis_is_provisional"
            ),
        ]


class NeedHypothesisInput(AppendOnlyRecord):
    hypothesis = models.ForeignKey(NeedHypothesis, on_delete=models.PROTECT, related_name="inputs")
    capture = models.ForeignKey(
        NeedCapture, on_delete=models.PROTECT, related_name="hypothesis_inputs"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("hypothesis", "capture"), name="hypothesis_input_once")
        ]
