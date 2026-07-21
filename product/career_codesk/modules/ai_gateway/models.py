"""Provisional machine interpretation with immutable exact source inputs."""

from django.db import models

from career_codesk.domain import AppendOnlyRecord
from career_codesk.modules.intake_provenance.models import NeedCapture

from .contracts import CONFIDENCE_STATES, DISPOSITIONS, TASK_KINDS


class NeedHypothesis(AppendOnlyRecord):
    case_id = models.CharField(max_length=32, db_index=True)
    tags = models.JSONField(default=list)
    explanation = models.TextField()
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    unknowns = models.JSONField(default=list)
    output_schema_version = models.CharField(max_length=32)
    gateway_policy_version = models.CharField(max_length=64)
    adapter_version = models.CharField(max_length=64)
    prompt_version = models.CharField(default="legacy-prompt-v1", max_length=64)
    model_version = models.CharField(default="legacy-fake-v1", max_length=64)
    confidence_state = models.CharField(default="unknown", max_length=16)
    gateway_output = models.ForeignKey(
        "AiGatewayOutput",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="hypotheses",
    )
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


class AiGatewayAttempt(AppendOnlyRecord):
    """One invocation audit record, including failures and restricted exits."""

    task_kind = models.CharField(max_length=32)
    source_record_ids = models.JSONField()
    source_records = models.JSONField()
    input_metadata = models.JSONField()
    input_digest = models.CharField(max_length=64)
    disposition = models.CharField(max_length=40)
    prompt_version = models.CharField(max_length=64)
    output_schema_version = models.CharField(max_length=64)
    model_version = models.CharField(max_length=64)
    adapter_version = models.CharField(max_length=64)
    policy_version = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(task_kind__in=TASK_KINDS), name="ai_attempt_task_is_allowlisted"
            ),
            models.CheckConstraint(
                check=models.Q(disposition__in=DISPOSITIONS),
                name="ai_attempt_disposition_is_closed",
            ),
        ]


class AiGatewayOutput(AppendOnlyRecord):
    """Validated payload only; malformed raw adapter content is never stored."""

    attempt = models.OneToOneField(
        AiGatewayAttempt, on_delete=models.PROTECT, related_name="output"
    )
    validated_payload = models.JSONField(null=True, blank=True)
    output_digest = models.CharField(max_length=64, blank=True)
    validation_errors = models.JSONField(default=list)
    confidence = models.CharField(max_length=16)
    authority = models.CharField(max_length=64, default="provisional_no_decision_authority")

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(confidence__in=CONFIDENCE_STATES),
                name="ai_output_confidence_is_closed",
            ),
            models.CheckConstraint(
                check=models.Q(authority="provisional_no_decision_authority"),
                name="ai_output_has_no_decision_authority",
            ),
        ]
