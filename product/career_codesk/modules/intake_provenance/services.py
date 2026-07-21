"""Application services for source evidence and restricted safety handling."""

import csv
import hashlib
import io
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from django.db import transaction

from career_codesk.domain import DomainInvariantError

from .models import Enrolment, ImportBatch, ImportRowResult, Learner, NeedCapture, SafetyExit

logger = logging.getLogger(__name__)

REQUIRED_HEADERS = ("synthetic_identifier", "course_code", "cohort_code", "need_statement")
REQUIRED_MANIFEST_FIELDS = (
    "schema_version",
    "fixture_version",
    "source_version",
    "clock_utc",
    "seed",
    "source_label",
    "synthetic_data_attestation",
)
SOURCE_LABEL = "Synthetic mock source — no MIS connection."
MAXIMUM_LENGTHS = {
    "synthetic_identifier": 128,
    "course_code": 64,
    "cohort_code": 64,
    "need_statement": 2000,
}


@dataclass(frozen=True)
class IntakeRowSummary:
    row_number: int
    status: str
    error_codes: tuple[str, ...]
    fields: tuple[str, ...]


@dataclass(frozen=True)
class IntakeSummary:
    batch_id: Optional[str]
    replayed: bool
    source_version_conflict: bool
    rows: tuple[IntakeRowSummary, ...]

    @property
    def accepted(self):
        return sum(row.status == "accepted" for row in self.rows)

    @property
    def rejected(self):
        return sum(row.status == "rejected" for row in self.rows)

    @property
    def quarantined(self):
        return sum(row.status == "quarantined" for row in self.rows)


class SyntheticCsvIntakeService:
    """The sole CSV seam: raw input never escapes it when rejected."""

    def import_csv(self, csv_bytes: bytes, manifest: dict) -> IntakeSummary:
        digest = hashlib.sha256(csv_bytes).hexdigest()
        manifest_digest = self._manifest_digest(manifest)
        metadata_errors = self._manifest_errors(manifest)
        if metadata_errors:
            # A rejected manifest may itself contain disallowed content.  Preserve
            # only a digest of the submitted bytes and fixed redacted markers.
            # Their digest is the replay identity; raw manifest data is never
            # stored or emitted in normal logs.
            batch_metadata = {
                "source_label": "Rejected manifest — redacted",
                "schema_version": "invalid",
                "fixture_version": "invalid",
                "source_version": f"rejected-{manifest_digest[:55]}",
                "fixed_clock_utc": "invalid",
                "seed": "invalid",
                "synthetic_data_attestation": False,
            }
        else:
            batch_metadata = {
                "source_label": manifest["source_label"],
                "schema_version": manifest["schema_version"],
                "fixture_version": manifest["fixture_version"],
                "source_version": manifest["source_version"],
                "fixed_clock_utc": manifest["clock_utc"],
                "seed": manifest["seed"],
                "synthetic_data_attestation": True,
            }
        existing = ImportBatch.objects.filter(
            source_label=batch_metadata["source_label"],
            source_version=batch_metadata["source_version"],
        ).first()
        if existing:
            if self._replay_matches(existing, manifest_digest, digest):
                return self._summary(existing, replayed=True)
            return IntakeSummary(None, False, True, ())

        with transaction.atomic():
            batch = ImportBatch.objects.create(
                **batch_metadata,
                payload_digest=digest,
                manifest_digest=manifest_digest,
            )
            if metadata_errors:
                self._record(batch, 0, "rejected", metadata_errors, ())
                return self._summary(batch)
            try:
                text = csv_bytes.decode("utf-8")
                # `strict=True` is essential here: without it, the stdlib CSV
                # reader silently accepts an unterminated quoted field and can
                # turn a malformed source row into ordinary learner evidence.
                reader = csv.DictReader(io.StringIO(text), restkey="__extra__", strict=True)
                header_errors = self._header_errors(reader.fieldnames)
                rows = list(reader)
            except (UnicodeDecodeError, csv.Error):
                self._record(batch, 0, "rejected", ("csv_malformed",), ())
                return self._summary(batch)
            if header_errors:
                self._record(batch, 0, "rejected", header_errors, ())
                return self._summary(batch)
            seen_identifiers = set()
            for row_number, row in enumerate(rows, start=2):
                self._process_row(batch, row_number, row, seen_identifiers, manifest)
            return self._summary(batch)

    def _manifest_errors(self, manifest):
        if not isinstance(manifest, dict):
            return ("manifest_invalid",)
        missing = [field for field in REQUIRED_MANIFEST_FIELDS if field not in manifest]
        if missing:
            return ("manifest_missing_required",)
        if set(manifest) != set(REQUIRED_MANIFEST_FIELDS):
            return ("manifest_not_allowlisted",)
        if (
            not all(
                isinstance(manifest[field], str)
                for field in (
                    "schema_version",
                    "fixture_version",
                    "source_version",
                    "clock_utc",
                    "source_label",
                )
            )
            or not isinstance(manifest["seed"], int)
            or isinstance(manifest["seed"], bool)
        ):
            return ("manifest_value_invalid",)
        if manifest["source_label"] != SOURCE_LABEL:
            return ("source_label_invalid",)
        if manifest["schema_version"] != "intake-csv-v1":
            return ("schema_version_unsupported",)
        if manifest["synthetic_data_attestation"] is not True:
            return ("synthetic_attestation_required",)
        if any(
            not manifest[field].strip()
            for field in REQUIRED_MANIFEST_FIELDS
            if field in manifest and isinstance(manifest[field], str)
        ):
            return ("manifest_value_invalid",)
        if any(
            self._contains_sensitive_value(str(manifest[field]))
            for field in REQUIRED_MANIFEST_FIELDS
            if field != "synthetic_data_attestation"
        ):
            return ("manifest_value_invalid",)
        bounded = {
            "fixture_version": 64,
            "source_version": 64,
            "clock_utc": 32,
            "seed": 32,
            "source_label": 96,
        }
        if any(len(str(manifest[field])) > maximum for field, maximum in bounded.items()):
            return ("manifest_value_invalid",)
        clock_utc = manifest["clock_utc"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", clock_utc):
            return ("manifest_value_invalid",)
        try:
            datetime.strptime(clock_utc, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return ("manifest_value_invalid",)
        if not 0 <= manifest["seed"] <= 2_147_483_647:
            return ("manifest_value_invalid",)
        return ()

    def _manifest_digest(self, manifest):
        """Return a stable opaque identity without retaining submitted metadata."""
        try:
            canonical = json.dumps(
                manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
        except (TypeError, ValueError):
            # The caller contract is JSON-like.  Invalid non-JSON values are
            # still rejected, and this fallback avoids logging or persisting them.
            canonical = f"non-json-manifest:{type(manifest).__qualname__}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _replay_matches(self, batch, manifest_digest, digest):
        return batch.payload_digest == digest and batch.manifest_digest == manifest_digest

    def _header_errors(self, headers):
        if not headers:
            return ("header_missing",)
        if len(headers) != len(set(headers)):
            return ("header_duplicate",)
        header_set = set(headers)
        forbidden = header_set & {
            "name",
            "email",
            "email_address",
            "phone",
            "telephone",
            "address",
            "dob",
            "date_of_birth",
            "send",
            "medical",
            "safeguarding",
            "welfare",
        }
        if forbidden:
            return ("forbidden_header",)
        if header_set != set(REQUIRED_HEADERS):
            return ("header_not_allowlisted",)
        return ()

    def _process_row(self, batch, row_number, row, seen_identifiers, manifest):
        fields = tuple(field for field in REQUIRED_HEADERS if not str(row.get(field, "")).strip())
        errors = []
        if row.get("__extra__") is not None:
            errors.append("row_shape_invalid")
        if fields:
            errors.append("required_value_missing")
        overlong = tuple(
            field
            for field in REQUIRED_HEADERS
            if len(str(row.get(field, ""))) > MAXIMUM_LENGTHS[field]
        )
        if overlong:
            fields = tuple(sorted(set(fields + overlong)))
            errors.append("value_too_long")
        identifier = str(row.get("synthetic_identifier", ""))
        if identifier and not identifier.startswith("synthetic-"):
            errors.append("synthetic_identifier_invalid")
        if identifier in seen_identifiers:
            errors.append("duplicate_row")
        if errors:
            self._record(batch, row_number, "rejected", tuple(errors), fields)
            return
        statement = str(row["need_statement"])
        direct_identifier_fields = self._direct_identifier_fields(row)
        # Safety is an exit from ordinary processing, not an ordinary sensitive-data
        # rejection. Direct identifiers remain unrecoverably rejected so the restricted
        # handoff cannot retain them.
        if self._is_safety_like(statement):
            if direct_identifier_fields:
                self._record(
                    batch,
                    row_number,
                    "rejected",
                    ("sensitive_value_detected",),
                    direct_identifier_fields,
                )
                return
            seen_identifiers.add(identifier)
            self._create_restricted(batch, row_number, row, manifest)
            self._record(
                batch, row_number, "quarantined", ("restricted_safety_exit",), ("need_statement",)
            )
            return
        sensitive_fields = self._sensitive_fields(row)
        if sensitive_fields:
            self._record(
                batch, row_number, "rejected", ("sensitive_value_detected",), sensitive_fields
            )
            return
        seen_identifiers.add(identifier)
        self._create_ordinary(batch, row_number, row, manifest)
        self._record(batch, row_number, "accepted", (), ())

    def _create_ordinary(self, batch, row_number, row, manifest):
        learner, _ = Learner.objects.get_or_create(
            synthetic_identifier=row["synthetic_identifier"],
            defaults={"fixture_version": manifest["fixture_version"]},
        )
        enrolment = Enrolment.objects.create(
            learner=learner,
            course_code=row["course_code"],
            cohort_code=row["cohort_code"],
            source_row=row_number,
            source_version=manifest["source_version"],
            import_batch=batch,
        )
        from career_codesk.modules.casework.models import Case

        case = Case.objects.create(learner=learner, enrolment=enrolment)
        NeedCapture.objects.create(
            learner=learner,
            enrolment=enrolment,
            case_id=case.id,
            source_type="csv",
            source_payload={"statement": row["need_statement"]},
            source_version=manifest["source_version"],
            source_row=row_number,
            field_allowlist_passed=True,
            import_batch=batch,
        )

    def _create_restricted(self, batch, row_number, row, manifest):
        learner, _ = Learner.objects.get_or_create(
            synthetic_identifier=row["synthetic_identifier"],
            defaults={"fixture_version": manifest["fixture_version"]},
        )
        enrolment = Enrolment.objects.create(
            learner=learner,
            course_code=row["course_code"],
            cohort_code=row["cohort_code"],
            source_row=row_number,
            source_version=manifest["source_version"],
            import_batch=batch,
        )
        from career_codesk.modules.casework.models import Case

        case = Case.objects.create(learner=learner, enrolment=enrolment)
        capture = NeedCapture.objects.create(
            learner=learner,
            enrolment=enrolment,
            case_id=case.id,
            source_type="csv",
            source_payload={"statement": row["need_statement"]},
            source_version=manifest["source_version"],
            source_row=row_number,
            field_allowlist_passed=True,
            import_batch=batch,
        )
        SafetyExit.objects.create(
            source_capture=capture, signal_metadata={"signal": "synthetic-safety-like-content"}
        )

    def _sensitive_fields(self, row):
        found = []
        for field, value in row.items():
            if self._contains_sensitive_value(str(value)):
                found.append(field)
        return tuple(found)

    def _direct_identifier_fields(self, row):
        return tuple(
            field for field, value in row.items() if self._contains_direct_identifier(str(value))
        )

    def _contains_sensitive_value(self, text):
        return self._contains_direct_identifier(text) or bool(
            re.search(
                r"\b(?:diagnos(?:is|ed)|medical|medication|SEND|safeguard(?:ing)?|welfare)\b",
                text,
                re.I,
            )
        )

    def _contains_direct_identifier(self, text):
        return bool(
            re.search(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", text)
            or re.search(
                r"(?<!\w)(?:\+44\s*(?:\(0\)\s*)?|0)7\d{3}[\s.-]?\d{3}[\s.-]?\d{3}\b",
                text,
            )
            or re.search(
                r"\b(?:full\s+name|name)\s*:\s*[A-Za-z][A-Za-z' -]{1,80}\b",
                text,
                re.I,
            )
            or re.search(
                r"\b(?:dob|date\s+of\s+birth)\s*:\s*"
                r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b",
                text,
                re.I,
            )
            or re.search(
                r"\b(?:home\s+address|address)\s*:\s*\d{1,5}\s+"
                r"[A-Za-z0-9][A-Za-z0-9 .'-]{2,80}\b",
                text,
                re.I,
            )
        )

    def _is_safety_like(self, statement):
        pattern = (
            r"\b(?:unsafe|harm myself|self-harm|suicide|hurt myself|"
            r"(?:do not|don't|dont|not) feel safe|not safe at home|"
            r"someone is hurting me|being hurt)\b"
        )
        return bool(re.search(pattern, statement, re.I))

    def _record(self, batch, row_number, status, codes, fields):
        logger.info(
            "synthetic intake row=%s status=%s codes=%s fields=%s",
            row_number,
            status,
            ",".join(codes),
            ",".join(fields),
        )
        ImportRowResult.objects.create(
            import_batch=batch,
            row_number=row_number,
            status=status,
            error_codes=list(codes),
            fields=list(fields),
        )

    def _summary(self, batch, replayed=False):
        rows = tuple(
            IntakeRowSummary(
                result.row_number, result.status, tuple(result.error_codes), tuple(result.fields)
            )
            for result in batch.row_results.order_by("row_number", "id")
        )
        return IntakeSummary(batch.id, replayed, False, rows)


class OrdinaryCaptureRepository:
    """The ordinary-workflow read path deliberately cannot return safety exits."""

    def for_case(self, case_id):
        return (
            NeedCapture.objects.filter(case_id=case_id)
            .exclude(id__in=SafetyExit.objects.values("source_capture_id"))
            .order_by("created_at", "id")
        )


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
