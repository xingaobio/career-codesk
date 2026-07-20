"""Application services for source evidence and restricted safety handling."""

from django.db import transaction

from career_codesk.domain import DomainInvariantError

from .models import NeedCapture, SafetyExit


class OrdinaryCaptureRepository:
    """The ordinary-workflow read path deliberately cannot return safety exits."""

    def for_case(self, case_id):
        return NeedCapture.objects.filter(case_id=case_id).order_by("created_at", "id")


class RestrictedSafetyExitRepository:
    """The only repository that returns restricted handoff records."""

    def get_for_capture(self, capture_id):
        return SafetyExit.objects.get(source_capture_id=capture_id)

    def exists_for_capture(self, capture_id):
        return SafetyExit.objects.filter(source_capture_id=capture_id).exists()


def capture_is_safety_exited(capture_id):
    """Expose a boolean gate without leaking a restricted handoff record."""
    return SafetyExit.objects.filter(source_capture_id=capture_id).exists()


def case_has_safety_exit(case_id):
    return SafetyExit.objects.filter(source_capture__case_id=case_id).exists()


class CaptureService:
    @transaction.atomic
    def correct(self, capture, *, source_payload, source_version, actor_type="learner"):
        capture = NeedCapture.objects.select_for_update().get(pk=capture.pk)
        if not capture.field_allowlist_passed:
            raise DomainInvariantError("Only allowlisted source evidence may be corrected")
        return NeedCapture.objects.create(
            learner=capture.learner,
            enrolment=capture.enrolment,
            case_id=capture.case_id,
            source_type=actor_type,
            source_payload=source_payload,
            source_version=source_version,
            field_allowlist_passed=True,
            supersedes=capture,
            schema_version=capture.schema_version,
            fixture_scope=capture.fixture_scope,
        )

    @transaction.atomic
    def record_safety_exit(self, capture, *, signal_metadata):
        capture = NeedCapture.objects.select_for_update().get(pk=capture.pk)
        if not capture.field_allowlist_passed:
            raise DomainInvariantError("A rejected source cannot create a safety exit")
        if case_has_safety_exit(capture.case_id):
            raise DomainInvariantError("A case already has a restricted safety exit")
        return SafetyExit.objects.create(source_capture=capture, signal_metadata=signal_metadata)
