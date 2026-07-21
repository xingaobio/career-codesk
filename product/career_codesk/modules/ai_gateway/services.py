"""Transactional orchestration of provisional gateway evidence."""

from django.db import transaction

from career_codesk.domain import DomainInvariantError
from career_codesk.modules.casework.models import Case
from career_codesk.modules.intake_provenance.models import NeedCapture, SafetyExit

from .contracts import (
    AdapterFailure,
    AdapterTimeout,
    AiProvenance,
    AiRequest,
    AiResult,
    SourceReference,
    StructuredModelAdapter,
    adapter_provenance,
    canonical_digest,
    canonical_request_digest,
    json_container_snapshot,
    payload_errors,
    validate_request,
    validated_result,
)
from .models import AiGatewayAttempt, AiGatewayOutput, NeedHypothesis, NeedHypothesisInput


class AiGatewayService:
    """The server-side boundary that validates, fails closed, and appends evidence."""

    def __init__(self, adapter: StructuredModelAdapter):
        self._adapter = adapter

    @transaction.atomic
    def interpret(self, request: AiRequest) -> AiResult:
        validate_request(request)
        source_ids = tuple(source.record_id for source in request.source_records)
        captures = tuple(
            NeedCapture.objects.select_for_update()
            .select_related("enrolment")
            .filter(pk__in=source_ids)
        )
        source_versions = {
            source.record_id: source.source_version for source in request.source_records
        }
        if (
            len(captures) != len(source_ids)
            or any(not capture.field_allowlist_passed for capture in captures)
            or any(capture.source_version != source_versions[capture.id] for capture in captures)
        ):
            raise DomainInvariantError("AI requests require persisted allowlisted capture evidence")
        if request.task_kind != "cohort_explanation" and any(
            capture.case_id != request.input_metadata["case_id"] for capture in captures
        ):
            raise DomainInvariantError("AI case metadata must match every cited capture")
        if request.task_kind == "cohort_explanation" and any(
            capture.enrolment_id is None
            or capture.enrolment.cohort_code != request.input_metadata["cohort_id"]
            for capture in captures
        ):
            raise DomainInvariantError(
                "AI cohort metadata must match persisted enrolment for every cited capture"
            )
        # Capture a single bounded provenance value before any closed result.
        # This includes an already-restricted case, so a broken adapter identity
        # cannot prevent persistence of its safety disposition.
        try:
            provenance = adapter_provenance(request, self._adapter)
        except DomainInvariantError:
            provenance = self._invalid_adapter_provenance(request)
            provenance_errors = ("adapter_provenance_invalid",)
        else:
            provenance_errors = ()
        # A safety exit applies to the whole case, not merely the capture that
        # caused it.  This is deliberately checked before adapter invocation so
        # a cohort request cannot bypass restricted human handling by citing a
        # different capture from the same case.
        cited_case_ids = {capture.case_id for capture in captures}
        if SafetyExit.objects.filter(source_capture__case_id__in=cited_case_ids).exists():
            result = self._result(
                request,
                "restricted_safety_escalation",
                validation_errors=provenance_errors,
                provenance=provenance,
            )
            return self._persist(request, result, captures, raw_digest="")
        if provenance_errors:
            # Invalid adapter configuration is not an invocation.  Persist a
            # bounded sentinel so the failed attempt remains auditable without
            # accepting unbounded or empty adapter-supplied provenance.
            result = self._result(
                request,
                "adapter_error",
                validation_errors=provenance_errors,
                provenance=provenance,
            )
            return self._persist(request, result, captures, raw_digest="")
        raw_digest = ""
        try:
            raw_payload = self._adapter.generate(request)
        except AdapterTimeout:
            result = self._result(request, "timeout", provenance=provenance)
        except AdapterFailure:
            result = self._result(request, "adapter_error", provenance=provenance)
        except Exception:
            result = self._result(request, "adapter_error", provenance=provenance)
        else:
            try:
                # Snapshot before examining, digesting, or validating.  Adapter
                # containers are untrusted and may be non-plain or stateful.
                payload_snapshot = json_container_snapshot(raw_payload)
            except ValueError:
                result = self._result(
                    request,
                    "schema_failure",
                    validation_errors=("payload_non_primitive",),
                    provenance=provenance,
                )
            else:
                raw_digest = canonical_digest(payload_snapshot)
                if isinstance(payload_snapshot, dict) and payload_snapshot.get("unsafe") is True:
                    # Retain only a digest: unsafe material never becomes ordinary output.
                    result = self._result(
                        request, "restricted_safety_escalation", provenance=provenance
                    )
                else:
                    result = validated_result(request, payload_snapshot, provenance=provenance)
        return self._persist(request, result, captures, raw_digest=raw_digest)

    def _result(self, request, disposition, *, validation_errors=(), provenance=None):
        if provenance is None:
            raise DomainInvariantError("Gateway results require captured provenance")
        return AiResult(
            request.task_kind,
            request.source_records,
            disposition,
            provenance,
            validation_errors=validation_errors,
        )

    @staticmethod
    def _invalid_adapter_provenance(request):
        return AiProvenance(
            request.prompt_version,
            request.output_schema_version,
            "invalid-adapter-configuration-v1",
            "invalid-adapter-configuration-v1",
            request.policy_version,
        )

    def _persist(self, request, result, captures, *, raw_digest):
        attempt = AiGatewayAttempt.objects.create(
            task_kind=request.task_kind,
            source_record_ids=[source.record_id for source in request.source_records],
            source_records=[
                {
                    "record_id": source.record_id,
                    "record_type": source.record_type,
                    "source_version": source.source_version,
                }
                for source in request.source_records
            ],
            input_metadata=dict(request.input_metadata),
            input_digest=canonical_request_digest(request),
            disposition=result.disposition,
            prompt_version=result.provenance.prompt_version,
            output_schema_version=result.provenance.output_schema_version,
            model_version=result.provenance.model_version,
            adapter_version=result.provenance.adapter_version,
            policy_version=result.provenance.policy_version,
        )
        output = AiGatewayOutput.objects.create(
            attempt=attempt,
            validated_payload=result.payload
            if result.disposition in ("provisional_output", "human_review_required")
            else None,
            output_digest=canonical_digest(result.payload)
            if result.payload is not None
            else raw_digest,
            validation_errors=list(result.validation_errors),
            confidence=result.confidence,
            authority=result.authority,
        )
        return AiResult(**{**result.__dict__, "attempt_id": attempt.id, "output_id": output.id})


class HypothesisService:
    @transaction.atomic
    def record(self, *, case_id, captures, gateway_result: AiResult):
        # The caller may construct an AiResult.  It is a receipt only: every
        # consequential field below is reloaded from append-only gateway evidence.
        if gateway_result.output_id is None or gateway_result.attempt_id is None:
            raise DomainInvariantError("Hypotheses require a persisted gateway result receipt")
        capture_ids = tuple(capture.pk for capture in captures)
        captures = tuple(NeedCapture.objects.select_for_update().get(pk=pk) for pk in capture_ids)
        if (
            not Case.objects.filter(pk=case_id).exists()
            or SafetyExit.objects.filter(source_capture__case_id=case_id).exists()
        ):
            raise DomainInvariantError(
                "A safety-exited or missing case cannot receive a hypothesis"
            )
        if any(
            capture.case_id != case_id or not capture.field_allowlist_passed for capture in captures
        ):
            raise DomainInvariantError(
                "Hypothesis inputs must be allowlisted captures for the case"
            )
        try:
            output = AiGatewayOutput.objects.select_related("attempt").get(
                pk=gateway_result.output_id
            )
        except AiGatewayOutput.DoesNotExist as error:
            raise DomainInvariantError("Hypothesis gateway receipt does not exist") from error
        attempt = output.attempt
        if attempt.id != gateway_result.attempt_id:
            raise DomainInvariantError("Hypothesis gateway receipt IDs do not match")
        source_records = [
            {
                "record_id": capture.id,
                "record_type": "need_capture",
                "source_version": capture.source_version,
            }
            for capture in captures
        ]
        expected_metadata = {"case_id": case_id, "capture_ids": list(capture_ids)}
        try:
            persisted_request = AiRequest(
                task_kind=attempt.task_kind,
                source_records=tuple(
                    SourceReference(**source) for source in attempt.source_records
                ),
                input_metadata=attempt.input_metadata,
                prompt_version=attempt.prompt_version,
                output_schema_version=attempt.output_schema_version,
                policy_version=attempt.policy_version,
            )
            validate_request(persisted_request)
        except (DomainInvariantError, TypeError) as error:
            raise DomainInvariantError("Persisted gateway request evidence is invalid") from error
        payload = output.validated_payload
        persisted_receipt = AiResult(
            task_kind=attempt.task_kind,
            source_records=persisted_request.source_records,
            disposition=attempt.disposition,
            provenance=AiProvenance(
                attempt.prompt_version,
                attempt.output_schema_version,
                attempt.model_version,
                attempt.adapter_version,
                attempt.policy_version,
            ),
            payload=payload,
            confidence=output.confidence,
            validation_errors=tuple(output.validation_errors),
            output_id=output.id,
            attempt_id=attempt.id,
            authority=output.authority,
        )
        if (
            gateway_result != persisted_receipt
            or attempt.task_kind not in ("intake_interpretation", "need_hypothesis")
            or attempt.disposition != "provisional_output"
            or output.authority != "provisional_no_decision_authority"
            or output.confidence != "high"
            or output.validation_errors
            or payload_errors(attempt.task_kind, payload)
            or payload.get("unknowns")
            or output.output_digest != canonical_digest(payload)
            or attempt.source_record_ids != list(capture_ids)
            or attempt.source_records != source_records
            or attempt.input_metadata != expected_metadata
            or attempt.input_digest != canonical_request_digest(persisted_request)
            or output.hypotheses.exists()
        ):
            raise DomainInvariantError(
                "Hypothesis gateway evidence must be an exact validated output"
            )
        hypothesis = NeedHypothesis.objects.create(
            case_id=case_id,
            tags=payload["tags"],
            explanation=payload["explanation"],
            confidence=None,
            confidence_state=output.confidence,
            unknowns=payload["unknowns"],
            output_schema_version=attempt.output_schema_version,
            prompt_version=attempt.prompt_version,
            model_version=attempt.model_version,
            gateway_policy_version=attempt.policy_version,
            adapter_version=attempt.adapter_version,
            gateway_output=output,
        )
        NeedHypothesisInput.objects.bulk_create(
            [NeedHypothesisInput(hypothesis=hypothesis, capture=c) for c in captures]
        )
        return hypothesis
