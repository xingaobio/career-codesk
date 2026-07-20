"""Persist a fake-AI output without granting it decision authority."""

from django.db import transaction

from career_codesk.domain import DomainInvariantError
from career_codesk.modules.casework.models import Case
from career_codesk.modules.intake_provenance.models import NeedCapture
from career_codesk.modules.intake_provenance.services import case_has_safety_exit

from .models import NeedHypothesis, NeedHypothesisInput


class HypothesisService:
    @transaction.atomic
    def record(
        self,
        *,
        case_id,
        captures,
        tags,
        explanation,
        unknowns,
        gateway_policy_version,
        adapter_version,
        confidence=None,
        output_schema_version="1.0",
    ):
        capture_ids = tuple(capture.pk for capture in captures)
        if not capture_ids:
            raise DomainInvariantError("A hypothesis must cite at least one exact capture")
        captures = tuple(
            NeedCapture.objects.select_for_update().get(pk=capture_id) for capture_id in capture_ids
        )
        if not Case.objects.filter(pk=case_id).exists():
            raise DomainInvariantError("A hypothesis must belong to an existing case")
        if case_has_safety_exit(case_id):
            raise DomainInvariantError("A safety-exited case cannot receive a hypothesis")
        if any(capture.case_id != case_id for capture in captures):
            raise DomainInvariantError("Hypothesis inputs must belong to the stated case")
        if any(not capture.field_allowlist_passed for capture in captures):
            raise DomainInvariantError("Only allowlisted source evidence may be interpreted")
        hypothesis = NeedHypothesis.objects.create(
            case_id=case_id,
            tags=tags,
            explanation=explanation,
            confidence=confidence,
            unknowns=unknowns,
            output_schema_version=output_schema_version,
            gateway_policy_version=gateway_policy_version,
            adapter_version=adapter_version,
        )
        NeedHypothesisInput.objects.bulk_create(
            [NeedHypothesisInput(hypothesis=hypothesis, capture=capture) for capture in captures]
        )
        return hypothesis
