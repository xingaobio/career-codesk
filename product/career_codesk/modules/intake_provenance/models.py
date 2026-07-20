"""Synthetic source evidence and the restricted safety-exit boundary."""

import re

from django.core.exceptions import ValidationError
from django.db import models

from career_codesk.domain import AppendOnlyRecord, DomainRecord


class Learner(DomainRecord):
    """Synthetic fixture identity, deliberately separate from enrolment and case."""

    synthetic_identifier = models.CharField(max_length=128, unique=True)
    fixture_version = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(synthetic_identifier__startswith="synthetic-"),
                name="learner_identifier_is_synthetic",
            )
        ]


class Enrolment(DomainRecord):
    learner = models.ForeignKey(Learner, on_delete=models.PROTECT, related_name="enrolments")
    course_code = models.CharField(max_length=64)
    cohort_code = models.CharField(max_length=64)
    source_row = models.PositiveIntegerField()
    source_version = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("learner", "source_version", "source_row"),
                name="enrolment_source_row_once",
            )
        ]


class NeedCapture(AppendOnlyRecord):
    """A verbatim source statement; corrections are new records, never edits."""

    SOURCE_TYPES = (("csv", "CSV"), ("learner", "Learner"), ("adviser", "Adviser"))

    learner = models.ForeignKey(Learner, on_delete=models.PROTECT, related_name="need_captures")
    enrolment = models.ForeignKey(
        Enrolment, null=True, blank=True, on_delete=models.PROTECT, related_name="need_captures"
    )
    case_id = models.CharField(max_length=32, db_index=True)
    source_type = models.CharField(max_length=16, choices=SOURCE_TYPES)
    source_payload = models.JSONField()
    source_version = models.CharField(max_length=64)
    source_row = models.PositiveIntegerField(null=True, blank=True)
    field_allowlist_passed = models.BooleanField()
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="corrections"
    )

    def clean(self):
        super().clean()
        # `case_id` remains a string to keep the provenance boundary independent
        # of the operational case app, but it must still identify this learner's
        # real case.
        from career_codesk.modules.casework.models import Case

        case = Case.objects.filter(pk=self.case_id).only("learner_id").first()
        if case is None or case.learner_id != self.learner_id:
            raise ValidationError("Capture case must belong to its learner")
        if self.supersedes_id and self.supersedes.case_id != self.case_id:
            raise ValidationError("A correction must stay within the same case")
        if self.enrolment_id and self.enrolment.learner_id != self.learner_id:
            raise ValidationError("Capture enrolment must belong to its learner")

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.full_clean()
        return super().save(*args, **kwargs)


class SafetyExit(AppendOnlyRecord):
    """Restricted simulated handoff marker; it intentionally has no score or case relation."""

    source_capture = models.OneToOneField(NeedCapture, on_delete=models.PROTECT, related_name="+")
    signal_metadata = models.JSONField()
    restricted_access_marker = models.BooleanField(default=True, editable=False)
    human_handling_status = models.CharField(default="restricted_human_handling", max_length=64)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(restricted_access_marker=True), name="safety_exit_is_restricted"
            )
        ]

    def clean(self):
        super().clean()
        if _contains_score_like_metadata(self.signal_metadata):
            raise ValidationError("Safety-exit metadata must not contain a score-like value")

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.full_clean()
        return super().save(*args, **kwargs)


def _contains_score_like_metadata(value):
    """Reject anything outside the minimal qualitative restricted metadata schema.

    Safety exits retain one free-text signal only.  This prevents nested or numeric
    payloads from becoming an alternative scoring channel while preserving the
    minimal handoff context allowed by the domain model.
    """
    if not isinstance(value, dict) or set(value) != {"signal"}:
        return True

    signal = value["signal"]
    if not isinstance(signal, str) or not signal.strip():
        return True

    score_terms = ("score", "risk", "rating", "rank", "confidence", "probability")
    normalised_signal = signal.lower().replace("_", " ").replace("-", " ")
    if any(re.search(rf"\b{term}\b", normalised_signal) for term in score_terms):
        return True

    # Qualitative text must not encode a numeric value, including decimal values.
    return bool(re.search(r"\d", signal))
