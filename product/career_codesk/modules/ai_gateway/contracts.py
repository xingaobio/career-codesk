"""Published, server-side contracts for bounded provisional AI interpretation.

This module deliberately contains no provider SDK or provider-specific vocabulary.
Only the gateway service may invoke a structured adapter, and its results never
carry decision authority.
"""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Optional, Protocol

from career_codesk.domain import DomainInvariantError

TASK_KINDS = (
    "intake_interpretation",
    "need_hypothesis",
    "cohort_explanation",
    "adviser_draft",
)
DISPOSITIONS = (
    "provisional_output",
    "human_review_required",
    "restricted_safety_escalation",
    "schema_failure",
    "timeout",
    "adapter_error",
)
CONFIDENCE_STATES = ("high", "low", "unknown")
# The fake and every future adapter may only emit this published, non-clinical
# taxonomy.  This is deliberately versioned with the output contract rather
# than treating a syntactically valid string as a supported interpretation.
NEED_TAG_TAXONOMY_VERSION = "need-tags-v1"
ALLOWED_NEED_TAGS = frozenset(("route-comparison",))
# ``test-schema-v1`` is a separately named, published deterministic fixture
# contract used by the domain suite; arbitrary caller-provided versions remain
# rejected.
SUPPORTED_OUTPUT_SCHEMA_VERSIONS = frozenset(("schema-v1", "test-schema-v1"))
MAX_SOURCE_RECORDS = 20
MAX_TAGS = 8
MAX_UNKNOWNS = 8
MAX_IDENTIFIER_LENGTH = 64
MAX_TEXT_LENGTH = 2000
MAX_PROVENANCE_VERSION_LENGTH = 64


@dataclass(frozen=True)
class SourceReference:
    """An exact, allowlisted source record, never a free-text learner identity."""

    record_id: str
    record_type: str
    source_version: str


@dataclass(frozen=True)
class AiRequest:
    task_kind: str
    source_records: tuple[SourceReference, ...]
    input_metadata: Mapping[str, Any]
    prompt_version: str
    output_schema_version: str
    policy_version: str


@dataclass(frozen=True)
class AiProvenance:
    prompt_version: str
    output_schema_version: str
    model_version: str
    adapter_version: str
    policy_version: str


@dataclass(frozen=True)
class AiResult:
    task_kind: str
    source_records: tuple[SourceReference, ...]
    disposition: str
    provenance: AiProvenance
    payload: Optional[Mapping[str, Any]] = None
    confidence: str = "unknown"
    validation_errors: tuple[str, ...] = ()
    output_id: Optional[str] = None
    attempt_id: Optional[str] = None
    authority: str = "provisional_no_decision_authority"

    @property
    def is_validated_provisional_output(self) -> bool:
        return self.disposition == "provisional_output" and self.payload is not None


class StructuredModelAdapter(Protocol):
    """Private-to-server seam for a structured response transport."""

    version: str
    model_version: str

    def generate(self, request: AiRequest) -> Mapping[str, Any]:
        """Return a mapping which the gateway must validate before use."""


class AiGateway(Protocol):
    """The only AI application contract available to user-facing code."""

    def interpret(self, request: AiRequest) -> AiResult:
        """Return a non-decisional, source-linked result or a safe disposition."""


class AdapterTimeout(Exception):
    """A bounded adapter timeout, mapped to a non-consequential result."""


class AdapterFailure(Exception):
    """A bounded adapter failure, mapped to a non-consequential result."""


class DeterministicFakeAdapter:
    """No-network, no-credential fake with stable responses for every task."""

    version = "deterministic-fake-adapter-v1"
    model_version = "deterministic-fake-model-v1"

    def generate(self, request: AiRequest) -> Mapping[str, Any]:
        payloads = {
            "intake_interpretation": {
                "tags": ["route-comparison"],
                "explanation": "Provisional interpretation of the cited synthetic source.",
                "unknowns": [],
                "confidence": "high",
            },
            "need_hypothesis": {
                "tags": ["route-comparison"],
                "explanation": "Provisional need hypothesis from the cited synthetic source.",
                "unknowns": [],
                "confidence": "high",
            },
            "cohort_explanation": {
                "summary": "Provisional explanation of the cited synthetic cohort inputs.",
                "unknowns": [],
                "confidence": "high",
            },
            "adviser_draft": {
                "draft": "Draft for adviser review based on the cited synthetic source.",
                "unknowns": [],
                "confidence": "high",
            },
        }
        return payloads[request.task_kind]


def canonical_digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def json_container_snapshot(value: Any) -> Any:
    """Return one stable, plain JSON-container copy of untrusted adapter output.

    ``Mapping`` permits implementations such as ``UserDict`` whose concrete
    representation cannot be passed to ``json.dumps``.  Read each container
    once and convert it to ordinary ``dict``/``list`` values before either
    digesting or validating it.  This also prevents a stateful mapping from
    presenting one payload for validation and another for persistence.
    """
    try:
        return _json_container_snapshot(value)
    except Exception as error:
        raise ValueError("adapter payload is not a stable JSON container") from error


def _json_container_snapshot(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        raise ValueError("non-finite number")
    if isinstance(value, (list, tuple)):
        return [_json_container_snapshot(item) for item in value]
    if isinstance(value, Mapping):
        # Materialise ``items`` exactly once: arbitrary Mapping implementations
        # may be stateful, and subsequent reads must not affect this result.
        items = tuple(value.items())
        snapshot = {}
        for key, item in items:
            if not isinstance(key, str):
                raise ValueError("JSON object key is not a string")
            if key in snapshot:
                raise ValueError("JSON object key is duplicated")
            snapshot[key] = _json_container_snapshot(item)
        return snapshot
    raise ValueError("value is not JSON-compatible")


def is_json_primitive(value: Any) -> bool:
    """Return whether ``value`` is safe to canonicalise as ordinary JSON.

    Adapter output is untrusted.  In particular, do not let a set, custom
    object, or non-finite number turn schema validation into an adapter error
    merely because JSON serialisation happened first.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, (list, tuple)):
        try:
            return all(is_json_primitive(item) for item in value)
        except Exception:
            return False
    if isinstance(value, Mapping):
        try:
            return all(
                isinstance(key, str) and is_json_primitive(item) for key, item in value.items()
            )
        except Exception:
            return False
    return False


def adapter_provenance(request: AiRequest, adapter: StructuredModelAdapter) -> AiProvenance:
    """Read the adapter identity only after enforcing its persisted contract."""
    try:
        model_version = adapter.model_version
        adapter_version = adapter.version
    except Exception as error:
        raise DomainInvariantError("AI adapter provenance is unavailable") from error
    if any(
        not isinstance(version, str)
        or not version.strip()
        or len(version) > MAX_PROVENANCE_VERSION_LENGTH
        for version in (model_version, adapter_version)
    ):
        raise DomainInvariantError("AI adapter provenance must be bounded non-empty strings")
    return AiProvenance(
        request.prompt_version,
        request.output_schema_version,
        model_version,
        adapter_version,
        request.policy_version,
    )


def validate_request(request: AiRequest) -> None:
    if request.task_kind not in TASK_KINDS:
        raise DomainInvariantError("Unsupported AI task")
    if not request.source_records or len(request.source_records) > MAX_SOURCE_RECORDS:
        raise DomainInvariantError("AI requests require exact source records")
    ids = []
    for source in request.source_records:
        if (
            source.record_type != "need_capture"
            or not isinstance(source.record_id, str)
            or not source.record_id.strip()
            or len(source.record_id) > MAX_IDENTIFIER_LENGTH
            or not isinstance(source.source_version, str)
            or not source.source_version.strip()
            or len(source.source_version) > MAX_IDENTIFIER_LENGTH
        ):
            raise DomainInvariantError("AI source records must be exact allowlisted captures")
        ids.append(source.record_id)
    if len(ids) != len(set(ids)):
        raise DomainInvariantError("AI source records must not be duplicated")
    if request.output_schema_version not in SUPPORTED_OUTPUT_SCHEMA_VERSIONS:
        raise DomainInvariantError("AI output schema version is unsupported")
    for version in (request.prompt_version, request.output_schema_version, request.policy_version):
        if not isinstance(version, str) or not version.strip() or len(version) > 64:
            raise DomainInvariantError("AI provenance versions must be bounded non-empty strings")
    _validate_input_metadata(request)


def _validate_input_metadata(request: AiRequest) -> None:
    metadata = request.input_metadata
    if not isinstance(metadata, Mapping):
        raise DomainInvariantError("AI input metadata must be an object")
    expected = {
        "intake_interpretation": {"case_id", "capture_ids"},
        "need_hypothesis": {"case_id", "capture_ids"},
        "cohort_explanation": {"cohort_id", "capture_ids"},
        "adviser_draft": {"case_id", "capture_ids"},
    }[request.task_kind]
    if set(metadata) != expected:
        raise DomainInvariantError("AI input metadata is not allowlisted for this task")
    identity_key = "cohort_id" if request.task_kind == "cohort_explanation" else "case_id"
    if (
        not isinstance(metadata[identity_key], str)
        or not metadata[identity_key].strip()
        or len(metadata[identity_key]) > MAX_IDENTIFIER_LENGTH
    ):
        raise DomainInvariantError("AI input identity is invalid")
    capture_ids = metadata["capture_ids"]
    if (
        not isinstance(capture_ids, (list, tuple))
        or len(capture_ids) > MAX_SOURCE_RECORDS
        or not all(isinstance(value, str) and value.strip() for value in capture_ids)
        or tuple(capture_ids) != tuple(source.record_id for source in request.source_records)
    ):
        raise DomainInvariantError("AI input capture IDs must exactly match source records")


def canonical_request_digest(request: AiRequest) -> str:
    """Digest the complete bounded request, including source versions and provenance."""
    return canonical_digest(
        {
            "task_kind": request.task_kind,
            "source_records": [
                {
                    "record_id": source.record_id,
                    "record_type": source.record_type,
                    "source_version": source.source_version,
                }
                for source in request.source_records
            ],
            "input_metadata": dict(request.input_metadata),
            "prompt_version": request.prompt_version,
            "output_schema_version": request.output_schema_version,
            "policy_version": request.policy_version,
        }
    )


def validated_result(
    request: AiRequest,
    raw_payload: Mapping[str, Any],
    adapter: Optional[StructuredModelAdapter] = None,
    *,
    provenance: Optional[AiProvenance] = None,
) -> AiResult:
    """Validate output using the provenance captured before adapter invocation.

    ``adapter`` remains a compatibility seam for isolated contract callers;
    gateway orchestration must pass the previously validated provenance so an
    adapter cannot change (or fail to expose) its identity after generation.
    """
    errors = payload_errors(request.task_kind, raw_payload)
    if provenance is None:
        if adapter is None:
            raise DomainInvariantError("AI result provenance is required")
        provenance = adapter_provenance(request, adapter)
    if errors:
        return AiResult(
            request.task_kind,
            request.source_records,
            "schema_failure",
            provenance,
            validation_errors=tuple(errors),
        )
    confidence = raw_payload["confidence"]
    if confidence in ("low", "unknown") or raw_payload["unknowns"]:
        return AiResult(
            request.task_kind,
            request.source_records,
            "human_review_required",
            provenance,
            payload=dict(raw_payload),
            confidence=confidence,
        )
    return AiResult(
        request.task_kind,
        request.source_records,
        "provisional_output",
        provenance,
        payload=dict(raw_payload),
        confidence=confidence,
    )


def payload_errors(task_kind: str, payload: Any) -> list[str]:
    if task_kind not in TASK_KINDS:
        return ["task_kind_unsupported"]
    if not isinstance(payload, Mapping):
        return ["payload_not_object"]
    if not is_json_primitive(payload):
        return ["payload_non_primitive"]
    expected = {
        "intake_interpretation": {"tags", "explanation", "unknowns", "confidence"},
        "need_hypothesis": {"tags", "explanation", "unknowns", "confidence"},
        "cohort_explanation": {"summary", "unknowns", "confidence"},
        "adviser_draft": {"draft", "unknowns", "confidence"},
    }[task_kind]
    if set(payload) != expected:
        return ["payload_not_allowlisted"]
    errors = []
    if payload.get("confidence") not in CONFIDENCE_STATES:
        errors.append("confidence_invalid")
    unknowns = payload.get("unknowns")
    if (
        not isinstance(unknowns, list)
        or len(unknowns) > MAX_UNKNOWNS
        or not all(isinstance(item, str) and item.strip() and len(item) <= 160 for item in unknowns)
        or len(unknowns) != len(set(unknowns))
    ):
        errors.append("unknowns_invalid")
    if "tags" in expected:
        tags = payload.get("tags")
        if (
            not isinstance(tags, list)
            or not tags
            or len(tags) > MAX_TAGS
            or not all(isinstance(item, str) for item in tags)
        ):
            errors.append("tags_invalid")
        elif len(tags) != len(set(tags)):
            errors.append("tags_duplicated")
        elif any(tag not in ALLOWED_NEED_TAGS for tag in tags):
            # Unsupported and safety-sensitive classifications fail closed;
            # they cannot become a provisional operational hypothesis.
            errors.append("tags_not_in_approved_taxonomy")
    text_key = next((key for key in ("explanation", "summary", "draft") if key in expected), None)
    if (
        not isinstance(payload.get(text_key), str)
        or not payload[text_key].strip()
        or len(payload[text_key]) > MAX_TEXT_LENGTH
    ):
        errors.append("text_invalid")
    return errors
