"""Contract matrix for the deterministic, non-decisional AI gateway."""

from collections import UserDict
from collections.abc import Mapping
from dataclasses import replace

from django.test import TestCase

from career_codesk.domain import DomainInvariantError, ImmutableRecordError
from career_codesk.modules.ai_gateway.contracts import (
    AdapterFailure,
    AdapterTimeout,
    AiRequest,
    SourceReference,
    canonical_digest,
)
from career_codesk.modules.ai_gateway.models import (
    AiGatewayAttempt,
    AiGatewayOutput,
    NeedHypothesis,
    NeedHypothesisInput,
)
from career_codesk.modules.ai_gateway.services import AiGatewayService, HypothesisService
from career_codesk.modules.casework.models import Case
from career_codesk.modules.intake_provenance.models import (
    Enrolment,
    Learner,
    NeedCapture,
    SafetyExit,
)
from career_codesk.modules.planning.models import Need
from career_codesk.modules.planning.services import AllocationService


class ScriptedAdapter:
    version = "scripted-adapter-v1"
    model_version = "scripted-model-v1"

    def __init__(self, outcome):
        self.outcome = outcome
        self.called = False

    def generate(self, request):
        self.called = True
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class ChangingProvenanceAdapter(ScriptedAdapter):
    """Exposes identity once, then proves result paths do not reread it."""

    def __init__(self, outcome):
        super().__init__(outcome)
        self._provenance_reads = 0

    @property
    def version(self):
        self._provenance_reads += 1
        if self._provenance_reads > 1:
            raise RuntimeError("provenance must not be read again")
        return "changing-adapter-v1"

    @property
    def model_version(self):
        return "changing-model-v1"


class StatefulPayloadMapping(Mapping):
    """Returns a valid payload only from its one permitted ``items`` read."""

    def __init__(self, payload):
        self.payload = payload
        self.items_reads = 0

    def __getitem__(self, key):
        raise AssertionError("gateway must snapshot through items()")

    def __iter__(self):
        raise AssertionError("gateway must snapshot through items()")

    def __len__(self):
        return len(self.payload)

    def items(self):
        self.items_reads += 1
        if self.items_reads > 1:
            return (("unexpected", "second read"),)
        return tuple(self.payload.items())


class AiGatewayTests(TestCase):
    def setUp(self):
        learner = Learner.objects.create(
            synthetic_identifier="synthetic-ai-gateway-001", fixture_version="fixture-v1"
        )
        enrolment = Enrolment.objects.create(
            learner=learner,
            course_code="SYN",
            cohort_code="SYN-COHORT",
            source_row=1,
            source_version="csv-v1",
        )
        self.case = Case.objects.create(learner=learner, enrolment=enrolment)
        self.capture = NeedCapture.objects.create(
            learner=learner,
            enrolment=enrolment,
            case_id=self.case.id,
            source_type="csv",
            source_payload={"statement": "Synthetic request for route comparison."},
            source_version="csv-v1",
            source_row=1,
            field_allowlist_passed=True,
        )
        self.need = Need.objects.create(
            taxonomy_code="route-comparison",
            taxonomy_version="taxonomy-v1",
            permitted_routes=["guide"],
        )

    def request(self, task_kind="need_hypothesis"):
        identity = "cohort_id" if task_kind == "cohort_explanation" else "case_id"
        identity_value = (
            self.capture.enrolment.cohort_code if identity == "cohort_id" else self.case.id
        )
        return AiRequest(
            task_kind=task_kind,
            source_records=(SourceReference(self.capture.id, "need_capture", "csv-v1"),),
            input_metadata={identity: identity_value, "capture_ids": [self.capture.id]},
            prompt_version="prompt-v1",
            output_schema_version="schema-v1",
            policy_version="policy-v1",
        )

    def test_each_authorised_task_persists_validated_provisional_provenance(self):
        outcomes = {
            "intake_interpretation": {
                "tags": ["route-comparison"],
                "explanation": "Provisional.",
                "unknowns": [],
                "confidence": "high",
            },
            "need_hypothesis": {
                "tags": ["route-comparison"],
                "explanation": "Provisional.",
                "unknowns": [],
                "confidence": "high",
            },
            "cohort_explanation": {"summary": "Provisional.", "unknowns": [], "confidence": "high"},
            "adviser_draft": {"draft": "Provisional.", "unknowns": [], "confidence": "high"},
        }
        for task, payload in outcomes.items():
            result = AiGatewayService(ScriptedAdapter(payload)).interpret(self.request(task))
            self.assertTrue(result.is_validated_provisional_output)
            self.assertEqual(result.authority, "provisional_no_decision_authority")
            self.assertEqual(result.source_records[0].record_id, self.capture.id)
            self.assertEqual(result.provenance.prompt_version, "prompt-v1")
        self.assertEqual(AiGatewayAttempt.objects.count(), 4)
        self.assertEqual(AiGatewayOutput.objects.count(), 4)

    def test_schema_failure_timeout_and_adapter_error_are_append_only_and_non_consequential(self):
        for outcome, disposition in (
            ({"unexpected": "shape"}, "schema_failure"),
            (AdapterTimeout(), "timeout"),
            (AdapterFailure(), "adapter_error"),
        ):
            result = AiGatewayService(ScriptedAdapter(outcome)).interpret(self.request())
            self.assertEqual(result.disposition, disposition)
            self.assertFalse(result.is_validated_provisional_output)
        output = AiGatewayOutput.objects.filter(attempt__disposition="schema_failure").get()
        self.assertIsNone(output.validated_payload)
        self.assertTrue(output.validation_errors)
        self.assertEqual(len(output.output_digest), 64)
        with self.assertRaises(ImmutableRecordError):
            output.delete()
        self.assertEqual(NeedHypothesis.objects.count(), 0)

    def test_non_json_primitive_payload_is_schema_failure_not_adapter_error(self):
        result = AiGatewayService(
            ScriptedAdapter(
                {
                    "tags": ["route-comparison"],
                    "explanation": "Malformed value must not escape validation.",
                    "unknowns": {"a set is not JSON"},
                    "confidence": "high",
                }
            )
        ).interpret(self.request())
        self.assertEqual(result.disposition, "schema_failure")
        self.assertIn("payload_non_primitive", result.validation_errors)
        output = AiGatewayOutput.objects.get(pk=result.output_id)
        self.assertIsNone(output.validated_payload)
        self.assertEqual(output.output_digest, "")

    def test_plain_snapshot_handles_userdict_and_stateful_mapping_once(self):
        payload = {
            "tags": ["route-comparison"],
            "explanation": "Snapshot the adapter response once.",
            "unknowns": [],
            "confidence": "high",
        }
        for outcome in (UserDict(payload), StatefulPayloadMapping(payload)):
            with self.subTest(outcome=type(outcome).__name__):
                result = AiGatewayService(ScriptedAdapter(outcome)).interpret(self.request())
                self.assertEqual(result.disposition, "provisional_output")
                output = AiGatewayOutput.objects.get(pk=result.output_id)
                self.assertEqual(output.validated_payload, payload)
                self.assertEqual(output.output_digest, canonical_digest(payload))
                if isinstance(outcome, StatefulPayloadMapping):
                    self.assertEqual(outcome.items_reads, 1)

    def test_invalid_adapter_provenance_fails_closed_before_invocation(self):
        adapter = ScriptedAdapter(
            {
                "tags": ["route-comparison"],
                "explanation": "Must not run.",
                "unknowns": [],
                "confidence": "high",
            }
        )
        adapter.version = ""
        adapter.model_version = "m" * 65
        result = AiGatewayService(adapter).interpret(self.request())
        self.assertEqual(result.disposition, "adapter_error")
        self.assertIn("adapter_provenance_invalid", result.validation_errors)
        self.assertFalse(adapter.called)
        self.assertEqual(result.provenance.adapter_version, "invalid-adapter-configuration-v1")

    def test_invalid_provenance_does_not_block_preexisting_safety_exit_persistence(self):
        SafetyExit.objects.create(
            source_capture=self.capture, signal_metadata={"signal": "restricted"}
        )
        adapter = ScriptedAdapter({"unsafe": True})
        adapter.version = ""
        result = AiGatewayService(adapter).interpret(self.request())
        self.assertEqual(result.disposition, "restricted_safety_escalation")
        self.assertIn("adapter_provenance_invalid", result.validation_errors)
        self.assertFalse(adapter.called)
        self.assertEqual(result.provenance.adapter_version, "invalid-adapter-configuration-v1")

    def test_captured_provenance_is_used_for_timeout_and_adapter_failure(self):
        for outcome, disposition in (
            (AdapterTimeout(), "timeout"),
            (AdapterFailure(), "adapter_error"),
        ):
            with self.subTest(disposition=disposition):
                result = AiGatewayService(ChangingProvenanceAdapter(outcome)).interpret(
                    self.request()
                )
                self.assertEqual(result.disposition, disposition)
                self.assertEqual(result.provenance.adapter_version, "changing-adapter-v1")

    def test_unsupported_and_safety_sensitive_tags_fail_closed(self):
        for tag in ("diagnosis", "neet-risk"):
            with self.subTest(tag=tag):
                result = AiGatewayService(
                    ScriptedAdapter(
                        {
                            "tags": [tag],
                            "explanation": "Must not be classified.",
                            "unknowns": [],
                            "confidence": "high",
                        }
                    )
                ).interpret(self.request())
                self.assertEqual(result.disposition, "schema_failure")
                self.assertIn("tags_not_in_approved_taxonomy", result.validation_errors)

    def test_unknown_and_low_confidence_are_human_review_only(self):
        for confidence in ("unknown", "low"):
            payload = {
                "tags": ["route-comparison"],
                "explanation": "Review needed.",
                "unknowns": [],
                "confidence": confidence,
            }
            result = AiGatewayService(ScriptedAdapter(payload)).interpret(self.request())
            self.assertEqual(result.disposition, "human_review_required")
            with self.assertRaises(DomainInvariantError):
                HypothesisService().record(
                    case_id=self.case.id, captures=[self.capture], gateway_result=result
                )

    def test_non_empty_unknowns_require_human_review_even_when_confidence_is_high(self):
        result = AiGatewayService(
            ScriptedAdapter(
                {
                    "tags": ["route-comparison"],
                    "explanation": "Do not guess.",
                    "unknowns": ["Whether the learner has compared routes."],
                    "confidence": "high",
                }
            )
        ).interpret(self.request())
        self.assertEqual(result.disposition, "human_review_required")
        self.assertIsNotNone(AiGatewayOutput.objects.get(pk=result.output_id).validated_payload)

    def test_bounded_collections_and_duplicate_values_fail_schema_validation(self):
        for payload in (
            {
                "tags": ["route-comparison", "route-comparison"],
                "explanation": "Duplicated tags.",
                "unknowns": [],
                "confidence": "high",
            },
            {
                "tags": ["route-comparison"],
                "explanation": "Too many unknowns.",
                "unknowns": [str(index) for index in range(9)],
                "confidence": "high",
            },
        ):
            result = AiGatewayService(ScriptedAdapter(payload)).interpret(self.request())
            self.assertEqual(result.disposition, "schema_failure")

    def test_safety_exit_prevents_adapter_invocation_and_hypothesis_creation(self):
        SafetyExit.objects.create(
            source_capture=self.capture, signal_metadata={"signal": "restricted"}
        )
        adapter = ScriptedAdapter(
            {
                "tags": ["route-comparison"],
                "explanation": "Ignored.",
                "unknowns": [],
                "confidence": "high",
            }
        )
        result = AiGatewayService(adapter).interpret(self.request())
        self.assertEqual(result.disposition, "restricted_safety_escalation")
        self.assertFalse(adapter.called)
        self.assertIsNone(AiGatewayOutput.objects.get(pk=result.output_id).validated_payload)

    def test_structural_adapter_safety_signal_with_extra_fields_is_restricted(self):
        result = AiGatewayService(
            ScriptedAdapter({"unsafe": True, "reason": "restricted synthetic signal"})
        ).interpret(self.request())
        self.assertEqual(result.disposition, "restricted_safety_escalation")
        output = AiGatewayOutput.objects.get(pk=result.output_id)
        self.assertIsNone(output.validated_payload)
        self.assertEqual(len(output.output_digest), 64)

    def test_case_safety_exit_on_an_uncited_capture_prevents_adapter_invocation(self):
        other_capture = NeedCapture.objects.create(
            learner=self.capture.learner,
            enrolment=self.capture.enrolment,
            case_id=self.case.id,
            source_type="csv",
            source_payload={"statement": "Separate synthetic source."},
            source_version="csv-v1",
            source_row=2,
            field_allowlist_passed=True,
        )
        SafetyExit.objects.create(
            source_capture=other_capture, signal_metadata={"signal": "restricted"}
        )
        adapter = ScriptedAdapter(
            {
                "tags": ["route-comparison"],
                "explanation": "Must not be generated.",
                "unknowns": [],
                "confidence": "high",
            }
        )

        result = AiGatewayService(adapter).interpret(self.request())

        self.assertEqual(result.disposition, "restricted_safety_escalation")
        self.assertFalse(adapter.called)
        self.assertEqual(AiGatewayAttempt.objects.count(), 1)
        self.assertEqual(AiGatewayOutput.objects.count(), 1)
        self.assertIsNone(AiGatewayOutput.objects.get(pk=result.output_id).validated_payload)

    def test_cohort_request_requires_matching_persisted_enrolment_context(self):
        adapter = ScriptedAdapter({"summary": "Provisional.", "unknowns": [], "confidence": "high"})
        cases = (
            ("unknown cohort", "NOT-A-COHORT"),
            ("case id", self.case.id),
        )
        for label, cohort_id in cases:
            with self.subTest(label=label), self.assertRaises(DomainInvariantError):
                request = self.request("cohort_explanation")
                request = AiRequest(
                    **{
                        **request.__dict__,
                        "input_metadata": {
                            "cohort_id": cohort_id,
                            "capture_ids": [self.capture.id],
                        },
                    }
                )
                AiGatewayService(adapter).interpret(request)
        self.assertFalse(adapter.called)

    def test_cohort_request_rejects_missing_or_mixed_enrolment(self):
        no_enrolment = NeedCapture.objects.create(
            learner=self.capture.learner,
            case_id=self.case.id,
            source_type="learner",
            source_payload={"statement": "Synthetic source without cohort context."},
            source_version="learner-v1",
            field_allowlist_passed=True,
        )
        adapter = ScriptedAdapter({"summary": "Provisional.", "unknowns": [], "confidence": "high"})
        other_learner = Learner.objects.create(
            synthetic_identifier="synthetic-ai-gateway-002", fixture_version="fixture-v1"
        )
        other_enrolment = Enrolment.objects.create(
            learner=other_learner,
            course_code="SYN",
            cohort_code="OTHER-COHORT",
            source_row=2,
            source_version="csv-v1",
        )
        other_case = Case.objects.create(learner=other_learner, enrolment=other_enrolment)
        other_capture = NeedCapture.objects.create(
            learner=other_learner,
            enrolment=other_enrolment,
            case_id=other_case.id,
            source_type="csv",
            source_payload={"statement": "Synthetic source from another cohort."},
            source_version="csv-v1",
            source_row=2,
            field_allowlist_passed=True,
        )
        for captures in ((no_enrolment,), (self.capture, other_capture)):
            request = AiRequest(
                task_kind="cohort_explanation",
                source_records=tuple(
                    SourceReference(capture.id, "need_capture", capture.source_version)
                    for capture in captures
                ),
                input_metadata={
                    "cohort_id": self.capture.enrolment.cohort_code,
                    "capture_ids": [capture.id for capture in captures],
                },
                prompt_version="prompt-v1",
                output_schema_version="schema-v1",
                policy_version="policy-v1",
            )
            with self.assertRaises(DomainInvariantError):
                AiGatewayService(adapter).interpret(request)
        self.assertFalse(adapter.called)

    def test_unsafe_adapter_response_is_restricted_and_never_stored_as_output(self):
        result = AiGatewayService(ScriptedAdapter({"unsafe": True})).interpret(self.request())
        self.assertEqual(result.disposition, "restricted_safety_escalation")
        output = AiGatewayOutput.objects.get(pk=result.output_id)
        self.assertIsNone(output.validated_payload)
        self.assertEqual(len(output.output_digest), 64)

    def test_only_validated_result_can_create_source_linked_hypothesis(self):
        payload = {
            "tags": ["route-comparison"],
            "explanation": "Provisional.",
            "unknowns": [],
            "confidence": "high",
        }
        result = AiGatewayService(ScriptedAdapter(payload)).interpret(self.request())
        hypothesis = HypothesisService().record(
            case_id=self.case.id, captures=[self.capture], gateway_result=result
        )
        self.assertEqual(hypothesis.status, "provisional")
        self.assertEqual(hypothesis.gateway_output_id, result.output_id)
        self.assertEqual(hypothesis.prompt_version, "prompt-v1")
        self.assertEqual(
            list(hypothesis.inputs.values_list("capture_id", flat=True)), [self.capture.id]
        )

    def test_forged_or_replayed_gateway_receipts_cannot_create_hypotheses(self):
        result = AiGatewayService(
            ScriptedAdapter(
                {
                    "tags": ["route-comparison"],
                    "explanation": "Persisted evidence only.",
                    "unknowns": [],
                    "confidence": "high",
                }
            )
        ).interpret(self.request())
        with self.assertRaises(DomainInvariantError):
            HypothesisService().record(
                case_id=self.case.id,
                captures=[self.capture],
                gateway_result=replace(result, confidence="low"),
            )
        HypothesisService().record(
            case_id=self.case.id, captures=[self.capture], gateway_result=result
        )
        with self.assertRaises(DomainInvariantError):
            HypothesisService().record(
                case_id=self.case.id, captures=[self.capture], gateway_result=result
            )

    def test_unlinked_or_mismatched_hypothesis_cannot_feed_allocation_planning(self):
        def propose(hypothesis):
            return AllocationService().propose(
                case_id=self.case.id,
                need=self.need,
                route_code="guide",
                planner_run_id=f"planner-{NeedHypothesis.objects.count()}",
                planner_algorithm_version="planner-v1",
                planner_policy_version="policy-v1",
                hypothesis=hypothesis,
            )

        unlinked = NeedHypothesis.objects.create(
            case_id=self.case.id,
            tags=["route-comparison"],
            explanation="Legacy row without gateway evidence.",
            unknowns=[],
            output_schema_version="schema-v1",
            gateway_policy_version="policy-v1",
            adapter_version="adapter-v1",
        )
        with self.assertRaises(DomainInvariantError):
            propose(unlinked)

        result = AiGatewayService(
            ScriptedAdapter(
                {
                    "tags": ["route-comparison"],
                    "explanation": "Validated content.",
                    "unknowns": [],
                    "confidence": "high",
                }
            )
        ).interpret(self.request())
        mismatched = NeedHypothesis.objects.create(
            case_id=self.case.id,
            tags=["route-comparison"],
            explanation="Tampered content.",
            unknowns=[],
            output_schema_version=result.provenance.output_schema_version,
            prompt_version=result.provenance.prompt_version,
            model_version=result.provenance.model_version,
            gateway_policy_version=result.provenance.policy_version,
            adapter_version=result.provenance.adapter_version,
            confidence_state="high",
            gateway_output_id=result.output_id,
        )
        with self.assertRaises(DomainInvariantError):
            propose(mismatched)

    def test_cross_case_orm_forgery_cannot_replay_gateway_evidence_in_planning(self):
        result = AiGatewayService(
            ScriptedAdapter(
                {
                    "tags": ["route-comparison"],
                    "explanation": "Case A evidence.",
                    "unknowns": [],
                    "confidence": "high",
                }
            )
        ).interpret(self.request())
        learner = Learner.objects.create(
            synthetic_identifier="synthetic-ai-gateway-002", fixture_version="fixture-v1"
        )
        enrolment = Enrolment.objects.create(
            learner=learner,
            course_code="SYN",
            cohort_code="SYN-COHORT",
            source_row=2,
            source_version="csv-v1",
        )
        other_case = Case.objects.create(learner=learner, enrolment=enrolment)
        forged = NeedHypothesis.objects.create(
            case_id=other_case.id,
            tags=["route-comparison"],
            explanation="Case A evidence.",
            unknowns=[],
            output_schema_version=result.provenance.output_schema_version,
            prompt_version=result.provenance.prompt_version,
            model_version=result.provenance.model_version,
            gateway_policy_version=result.provenance.policy_version,
            adapter_version=result.provenance.adapter_version,
            confidence_state="high",
            gateway_output_id=result.output_id,
        )
        NeedHypothesisInput.objects.create(hypothesis=forged, capture=self.capture)
        with self.assertRaises(DomainInvariantError):
            AllocationService().propose(
                case_id=other_case.id,
                need=self.need,
                route_code="guide",
                planner_run_id="planner-cross-case",
                planner_algorithm_version="planner-v1",
                planner_policy_version="policy-v1",
                hypothesis=forged,
            )
