"""Acceptance evidence for the provenance-aware synthetic domain model."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from career_codesk.domain import DomainInvariantError, ImmutableRecordError
from career_codesk.identity import SimulatedActor, actor_for
from career_codesk.modules.ai_gateway.contracts import (
    AiRequest,
    DeterministicFakeAdapter,
    SourceReference,
)
from career_codesk.modules.ai_gateway.models import NeedHypothesis, NeedHypothesisInput
from career_codesk.modules.ai_gateway.services import AiGatewayService, HypothesisService
from career_codesk.modules.casework.models import Case, CaseTransition
from career_codesk.modules.casework.services import CaseWorkflowService
from career_codesk.modules.decisions.models import ReviewedInput, SupportDecision
from career_codesk.modules.decisions.services import SupportDecisionService
from career_codesk.modules.delivery_feedback.models import OutcomeConfirmation
from career_codesk.modules.delivery_feedback.services import DeliveryFeedbackService
from career_codesk.modules.export.models import WritebackAttempt
from career_codesk.modules.export.services import WritebackService
from career_codesk.modules.intake_provenance.models import (
    Enrolment,
    Learner,
    NeedCapture,
    SafetyExit,
)
from career_codesk.modules.intake_provenance.services import (
    CaptureService,
    OrdinaryCaptureRepository,
    RestrictedSafetyExitRepository,
)
from career_codesk.modules.planning.models import InterventionAllocation, Need
from career_codesk.modules.planning.services import AllocationService


class ProvenanceDomainTests(TestCase):
    def setUp(self):
        self.learner = Learner.objects.create(
            synthetic_identifier="synthetic-learner-provenance-001", fixture_version="demo-v1"
        )
        self.enrolment = Enrolment.objects.create(
            learner=self.learner,
            course_code="SYN-COURSE",
            cohort_code="SYN-COHORT",
            source_row=1,
            source_version="csv-v1",
        )
        self.case = Case.objects.create(learner=self.learner, enrolment=self.enrolment)
        self.capture = NeedCapture.objects.create(
            learner=self.learner,
            enrolment=self.enrolment,
            case_id=self.case.id,
            source_type="csv",
            source_payload={"statement": "Needs help comparing synthetic routes."},
            source_version="csv-v1",
            source_row=1,
            field_allowlist_passed=True,
        )
        self.need = Need.objects.create(
            taxonomy_code="route-comparison",
            taxonomy_version="taxonomy-v1",
            permitted_routes=["guide"],
        )

    def _hypothesis(self):
        result = self._gateway_result(self.capture)
        return HypothesisService().record(
            case_id=self.case.id,
            captures=[self.capture],
            gateway_result=result,
        )

    def _gateway_result(self, capture):
        request = AiRequest(
            task_kind="need_hypothesis",
            source_records=(SourceReference(capture.id, "need_capture", capture.source_version),),
            input_metadata={"case_id": self.case.id, "capture_ids": [capture.id]},
            prompt_version="test-prompt-v1",
            output_schema_version="test-schema-v1",
            policy_version="test-policy-v1",
        )
        return AiGatewayService(DeterministicFakeAdapter()).interpret(request)

    def _proposal(self):
        return AllocationService().propose(
            case_id=self.case.id,
            need=self.need,
            route_code="guide",
            planner_run_id=f"planner-run-{InterventionAllocation.objects.count() + 1:03d}",
            planner_algorithm_version="planner-v1",
            planner_policy_version="policy-v1",
            hypothesis=self._hypothesis(),
        )

    def _approve(self, allocation=None):
        allocation = allocation or self._proposal()
        return SupportDecisionService().record(
            case_id=self.case.id,
            allocation=allocation,
            action="approve",
            actor=actor_for("adviser"),
            reason="The simulated adviser reviewed the stated source and proposal.",
            reviewed_inputs=[("capture", self.capture.id)],
            policy_version="decision-policy-v1",
            planner_version="planner-v1",
        )

    def test_learner_enrolment_need_and_case_have_distinct_stable_identity(self):
        second_case = Case.objects.create(learner=self.learner, enrolment=self.enrolment)
        self.assertEqual(self.enrolment.learner_id, self.learner.id)
        self.assertEqual(self.case.learner_id, self.learner.id)
        self.assertNotEqual(self.case.id, second_case.id)
        self.assertNotEqual(self.need.id, self.case.id)
        self.assertEqual(len(self.case.id), 32)
        self.enrolment.course_code = "SYN-CHANGED-CONTEXT"
        self.enrolment.save(update_fields=("course_code",))
        self.case.refresh_from_db()
        self.assertEqual(self.case.learner_id, self.learner.id)
        self.assertEqual(self.case.state, "open")

    def test_conflicting_captures_and_correction_preserve_the_original_source(self):
        conflict = NeedCapture.objects.create(
            learner=self.learner,
            enrolment=self.enrolment,
            case_id=self.case.id,
            source_type="adviser",
            source_payload={"statement": "Synthetic adviser sees a different route preference."},
            source_version="adviser-v1",
            field_allowlist_passed=True,
        )
        correction = CaptureService().correct(
            self.capture,
            source_payload={"statement": "Corrected synthetic source statement."},
            source_version="learner-correction-v1",
        )
        self.assertEqual(correction.supersedes_id, self.capture.id)
        self.assertEqual(OrdinaryCaptureRepository().for_case(self.case.id).count(), 3)
        self.capture.refresh_from_db()
        self.assertIn("Needs help", self.capture.source_payload["statement"])
        self.assertNotEqual(conflict.source_payload, correction.source_payload)
        with self.assertRaises(ImmutableRecordError):
            self.capture.source_payload = {"statement": "rewritten"}
            self.capture.save()
        with self.assertRaises(ImmutableRecordError):
            NeedCapture.objects.filter(pk=self.capture.id).update(source_version="rewritten")
        with self.assertRaises(ImmutableRecordError):
            self.capture.delete()

    def test_hypotheses_cite_exact_capture_versions_and_never_replace_sources(self):
        first = self._hypothesis()
        correction = CaptureService().correct(
            self.capture,
            source_payload={"statement": "Corrected synthetic need."},
            source_version="learner-correction-v1",
        )
        later = HypothesisService().record(
            case_id=self.case.id,
            captures=[correction],
            gateway_result=self._gateway_result(correction),
        )
        self.assertEqual(list(first.inputs.values_list("capture_id", flat=True)), [self.capture.id])
        self.assertEqual(list(later.inputs.values_list("capture_id", flat=True)), [correction.id])
        self.assertEqual(NeedHypothesis.objects.count(), 2)
        self.assertEqual(NeedHypothesisInput.objects.count(), 2)
        with self.assertRaises(ImmutableRecordError):
            first.explanation = "fact"
            first.save()

    def test_adviser_owns_immutable_approve_amend_and_reject_history(self):
        proposal = self._proposal()
        with self.assertRaises(DomainInvariantError):
            SupportDecisionService().record(
                case_id=self.case.id,
                allocation=proposal,
                action="approve",
                actor=actor_for("manager"),
                reason="Manager cannot decide.",
                reviewed_inputs=[("capture", self.capture.id)],
                policy_version="decision-policy-v1",
                planner_version="planner-v1",
            )
        approved = self._approve(proposal)
        proposal.refresh_from_db()
        self.assertEqual(proposal.state, "active")
        amended = SupportDecisionService().record(
            case_id=self.case.id,
            allocation=proposal,
            action="amend",
            actor=actor_for("adviser"),
            reason="Later adviser amendment remains an event.",
            reviewed_inputs=[("hypothesis", proposal.hypothesis_id)],
            policy_version="decision-policy-v2",
            planner_version="planner-v1",
            predecessor=approved,
        )
        rejected = SupportDecisionService().record(
            case_id=self.case.id,
            allocation=proposal,
            action="reject",
            actor=actor_for("adviser"),
            reason="Later adviser rejection remains an event.",
            reviewed_inputs=[("capture", self.capture.id)],
            policy_version="decision-policy-v3",
            planner_version="planner-v1",
            predecessor=amended,
        )
        self.assertEqual(rejected.predecessor_id, amended.id)
        self.assertEqual(SupportDecision.objects.count(), 3)
        self.assertEqual(ReviewedInput.objects.count(), 3)
        proposal.refresh_from_db()
        self.assertEqual(proposal.state, "inactive")
        with self.assertRaises(ImmutableRecordError):
            approved.reason = "changed"
            approved.save()

    def test_decisions_reload_proposals_and_require_a_linear_predecessor_history(self):
        proposal = self._proposal()
        with self.assertRaises(DomainInvariantError):
            SupportDecisionService().record(
                case_id=self.case.id,
                allocation=proposal,
                action="amend",
                actor=actor_for("adviser"),
                reason="An amendment cannot be an unrelated root.",
                reviewed_inputs=[("capture", self.capture.id)],
                policy_version="decision-policy-v1",
                planner_version="planner-v1",
            )
        approved = self._approve(proposal)
        amended = SupportDecisionService().record(
            case_id=self.case.id,
            allocation=proposal,
            action="amend",
            actor=actor_for("adviser"),
            reason="A linear successor.",
            reviewed_inputs=[("capture", self.capture.id)],
            policy_version="decision-policy-v2",
            planner_version="planner-v1",
            predecessor=approved,
        )
        with self.assertRaises(DomainInvariantError):
            SupportDecisionService().record(
                case_id=self.case.id,
                allocation=proposal,
                action="reject",
                actor=actor_for("adviser"),
                reason="A second successor would branch history.",
                reviewed_inputs=[("capture", self.capture.id)],
                policy_version="decision-policy-v3",
                planner_version="planner-v1",
                predecessor=approved,
            )
        other_case = Case.objects.create(learner=self.learner, enrolment=self.enrolment)
        proposal.case_id = other_case.id  # A caller can mutate an in-memory projection.
        with self.assertRaises(DomainInvariantError):
            SupportDecisionService().record(
                case_id=other_case.id,
                allocation=proposal,
                action="reject",
                actor=actor_for("adviser"),
                reason="The persisted proposal remains authoritative.",
                reviewed_inputs=[("capture", self.capture.id)],
                policy_version="decision-policy-v3",
                planner_version="planner-v1",
                predecessor=amended,
            )

    def test_forged_adviser_cannot_approve_or_move_a_case(self):
        forged_adviser = SimulatedActor(
            "actor-forged-adviser-001", "adviser", "Forged Synthetic Adviser"
        )
        proposal = self._proposal()
        with self.assertRaises(DomainInvariantError):
            SupportDecisionService().record(
                case_id=self.case.id,
                allocation=proposal,
                action="approve",
                actor=forged_adviser,
                reason="A role label does not establish simulated adviser ownership.",
                reviewed_inputs=[("capture", self.capture.id)],
                policy_version="decision-policy-v1",
                planner_version="planner-v1",
            )
        with self.assertRaises(DomainInvariantError):
            CaseWorkflowService().transition(
                self.case.id, "active", forged_adviser, "Forged adviser movement."
            )
        self.case.refresh_from_db()
        proposal.refresh_from_db()
        self.assertEqual(self.case.state, "open")
        self.assertEqual(proposal.state, "proposed")
        self.assertEqual(CaseTransition.objects.count(), 0)
        self.assertEqual(SupportDecision.objects.count(), 0)

    def test_direct_projection_mutators_cannot_bypass_services_or_history(self):
        proposal = self._proposal()
        with self.assertRaises(AttributeError):
            self.case.apply_transition("active")
        with self.assertRaises(AttributeError):
            proposal.activate()
        with self.assertRaises(DomainInvariantError):
            self.case.state = "active"
            self.case.save(update_fields=("state", "updated_at"))
        with self.assertRaises(DomainInvariantError):
            proposal.state = "active"
            proposal.save(update_fields=("state",))
        self.case.refresh_from_db()
        proposal.refresh_from_db()
        self.assertEqual(self.case.state, "open")
        self.assertEqual(proposal.state, "proposed")
        self.assertEqual(CaseTransition.objects.count(), 0)
        self.assertEqual(SupportDecision.objects.count(), 0)

    def test_safety_exit_is_restricted_and_stops_ordinary_processing(self):
        exit_record = CaptureService().record_safety_exit(
            self.capture, signal_metadata={"signal": "synthetic-sensitive-signal"}
        )
        self.assertTrue(exit_record.restricted_access_marker)
        self.assertEqual(
            RestrictedSafetyExitRepository().get_for_capture(self.capture.id), exit_record
        )
        self.assertFalse(hasattr(OrdinaryCaptureRepository(), "safety_exits"))
        # A safety-exited source is not an ordinary workflow input at all.
        # The restricted repository above is the sole read path for its handoff.
        self.assertEqual(OrdinaryCaptureRepository().for_case(self.case.id).count(), 0)
        self.assertNotIn("score", {field.name for field in SafetyExit._meta.fields})
        self.assertNotIn("case", {field.name for field in SafetyExit._meta.fields})
        with self.assertRaises(DomainInvariantError):
            self._hypothesis()
        with self.assertRaises(DomainInvariantError):
            self._proposal()
        self.assertEqual(NeedHypothesis.objects.count(), 0)
        self.assertEqual(InterventionAllocation.objects.count(), 0)
        self.assertEqual(WritebackAttempt.objects.count(), 0)

    def test_capture_services_reload_persisted_source_before_correction_and_safety_exit(self):
        other_case = Case.objects.create(learner=self.learner, enrolment=self.enrolment)
        self.capture.case_id = other_case.id
        self.capture.field_allowlist_passed = False
        correction = CaptureService().correct(
            self.capture,
            source_payload={"statement": "Correction uses the persisted source scope."},
            source_version="learner-correction-v1",
        )
        self.assertEqual(correction.case_id, self.case.id)
        self.assertTrue(correction.field_allowlist_passed)

        self.capture.case_id = other_case.id
        self.capture.field_allowlist_passed = False
        safety_exit = CaptureService().record_safety_exit(
            self.capture, signal_metadata={"signal": "synthetic-sensitive-signal"}
        )
        self.assertEqual(safety_exit.source_capture_id, self.capture.id)
        self.assertTrue(RestrictedSafetyExitRepository().exists_for_capture(self.capture.id))

    def test_hypothesis_and_route_checks_reload_persisted_instances(self):
        other_case = Case.objects.create(learner=self.learner, enrolment=self.enrolment)
        self.capture.case_id = other_case.id
        self.capture.field_allowlist_passed = False
        hypothesis = self._hypothesis()
        self.assertEqual(hypothesis.case_id, self.case.id)
        self.assertEqual(hypothesis.inputs.get().capture_id, self.capture.id)

        self.need.permitted_routes = ["forged-route"]
        with self.assertRaises(DomainInvariantError):
            AllocationService().propose(
                case_id=self.case.id,
                need=self.need,
                route_code="forged-route",
                planner_run_id="forged-route-run",
                planner_algorithm_version="planner-v1",
                planner_policy_version="policy-v1",
            )
        self.assertEqual(InterventionAllocation.objects.count(), 0)

    def test_safety_exit_rejects_score_metadata_and_late_ordinary_work(self):
        with self.assertRaises(ValidationError):
            CaptureService().record_safety_exit(
                self.capture, signal_metadata={"nested": {"risk_score": 0.8}}
            )
        with self.assertRaises(ValidationError):
            CaptureService().record_safety_exit(self.capture, signal_metadata={"signal": 0.8})
        with self.assertRaises(ValidationError):
            CaptureService().record_safety_exit(
                self.capture, signal_metadata={"signal": "risk score: 0.8"}
            )

        allocation = self._proposal()
        approved = self._approve(allocation)
        workflow = CaseWorkflowService()
        workflow.transition(self.case.id, "active", actor_for("adviser"), "begin work")
        workflow.transition(self.case.id, "closed", actor_for("adviser"), "await outcome")
        delivery = DeliveryFeedbackService().record_delivery(
            case_id=self.case.id,
            allocation=allocation,
            actor_id=actor_for("adviser").id,
            result="completed",
            source="synthetic delivery record",
        )
        CaptureService().record_safety_exit(
            self.capture, signal_metadata={"signal": "synthetic-sensitive-signal"}
        )

        with self.assertRaises(DomainInvariantError):
            self._hypothesis()
        with self.assertRaises(DomainInvariantError):
            AllocationService().propose(
                case_id=self.case.id,
                need=self.need,
                route_code="guide",
                planner_run_id="late-run",
                planner_algorithm_version="planner-v1",
                planner_policy_version="policy-v1",
            )
        with self.assertRaises(DomainInvariantError):
            SupportDecisionService().record(
                case_id=self.case.id,
                allocation=allocation,
                action="reject",
                actor=actor_for("adviser"),
                reason="ordinary workflow is unavailable",
                reviewed_inputs=[("capture", self.capture.id)],
                policy_version="decision-policy-v2",
                planner_version="planner-v1",
                predecessor=approved,
            )
        with self.assertRaises(DomainInvariantError):
            workflow.transition(self.case.id, "open", actor_for("adviser"), "ordinary reopen")
        with self.assertRaises(DomainInvariantError):
            DeliveryFeedbackService().record_delivery(
                case_id=self.case.id,
                allocation=allocation,
                actor_id=actor_for("adviser").id,
                result="late",
                source="synthetic delivery record",
            )
        with self.assertRaises(DomainInvariantError):
            DeliveryFeedbackService().record_outcome(
                delivery_event=delivery,
                actor_id="synthetic-learner-001",
                response="unresolved",
                exact_response="The synthetic action remains unresolved.",
            )
        with self.assertRaises(DomainInvariantError):
            WritebackService().record_attempt(
                allocation=allocation, decision=approved, payload={"mock": "payload"}
            )

    def test_capture_rejects_a_case_owned_by_another_learner(self):
        other_learner = Learner.objects.create(
            synthetic_identifier="synthetic-learner-provenance-002", fixture_version="demo-v1"
        )
        other_case = Case.objects.create(learner=other_learner)
        with self.assertRaises(ValidationError):
            NeedCapture.objects.create(
                learner=self.learner,
                enrolment=self.enrolment,
                case_id=other_case.id,
                source_type="csv",
                source_payload={"statement": "Invalid cross-case source."},
                source_version="csv-v1",
                field_allowlist_passed=True,
            )

    def test_invalid_manual_movement_is_rejected_and_close_reopen_history_is_ordered(self):
        workflow = CaseWorkflowService()
        with self.assertRaises(DomainInvariantError):
            workflow.transition(self.case.id, "closed", actor_for("manager"), "not authorised")
        with self.assertRaises(DomainInvariantError):
            workflow.transition(self.case.id, "open", actor_for("adviser"), "no movement")
        workflow.transition(self.case.id, "active", actor_for("adviser"), "begin work")
        workflow.transition(self.case.id, "closed", actor_for("adviser"), "awaiting outcome")
        with self.assertRaises(DomainInvariantError):
            self.case.state = "open"
            self.case.save()
        delivery = DeliveryFeedbackService().record_delivery(
            case_id=self.case.id,
            allocation=self._activate_for_delivery(),
            actor_id=actor_for("adviser").id,
            result="completed",
            source="synthetic delivery record",
        )
        DeliveryFeedbackService().record_outcome(
            delivery_event=delivery,
            actor_id="synthetic-learner-001",
            response="unresolved",
            exact_response="The synthetic action remains unresolved.",
        )
        self.case.refresh_from_db()
        self.assertEqual(self.case.state, "open")
        self.assertEqual(
            list(self.case.transitions.values_list("from_state", "to_state")),
            [("open", "active"), ("active", "closed"), ("closed", "open")],
        )
        self.assertEqual(OutcomeConfirmation.objects.count(), 1)
        with self.assertRaises(ImmutableRecordError):
            CaseTransition.objects.filter(case=self.case).delete()

    def test_reopen_requires_the_exact_unresolved_outcome_for_the_closed_case(self):
        workflow = CaseWorkflowService()
        workflow.transition(self.case.id, "active", actor_for("adviser"), "begin work")
        workflow.transition(self.case.id, "closed", actor_for("adviser"), "awaiting outcome")
        delivery = DeliveryFeedbackService().record_delivery(
            case_id=self.case.id,
            allocation=self._activate_for_delivery(),
            actor_id=actor_for("adviser").id,
            result="completed",
            source="synthetic delivery record",
        )
        helped = DeliveryFeedbackService().record_outcome(
            delivery_event=delivery,
            actor_id="synthetic-learner-001",
            response="helped",
            exact_response="The synthetic action helped.",
        )
        with self.assertRaises(DomainInvariantError):
            workflow.reopen_from_unresolved(
                case_id=self.case.id,
                actor_id="synthetic-learner-001",
                reason="A direct reopen is not evidence-led.",
                outcome_confirmation_id=helped.id,
            )
        self.assertEqual(self.case.transitions.count(), 2)

    def _activate_for_delivery(self):
        allocation = self._proposal()
        self._approve(allocation)
        allocation.refresh_from_db()
        return allocation

    def test_only_approved_active_allocations_create_local_mock_writeback_history(self):
        proposal = self._proposal()
        approval_before_rejection = self._approve(proposal)
        rejected = SupportDecisionService().record(
            case_id=self.case.id,
            allocation=proposal,
            action="reject",
            actor=actor_for("adviser"),
            reason="Rejected proposal.",
            reviewed_inputs=[("capture", self.capture.id)],
            policy_version="decision-policy-v1",
            planner_version="planner-v1",
            predecessor=approval_before_rejection,
        )
        with self.assertRaises(DomainInvariantError):
            WritebackService().record_attempt(
                allocation=proposal, decision=rejected, payload={"mock": "payload"}
            )
        approved = self._approve(self._proposal())
        active = InterventionAllocation.objects.get(pk=approved.allocation_id)
        first = WritebackService().record_attempt(
            allocation=active,
            decision=approved,
            payload={"mock": "payload"},
            result="failed",
            failure_reason="local simulated failure",
        )
        retry = WritebackService().record_attempt(
            allocation=active,
            decision=approved,
            payload={"mock": "payload"},
            result="succeeded",
        )
        self.assertEqual(first.idempotency_key, retry.idempotency_key)
        self.assertEqual((first.attempt_number, retry.attempt_number), (1, 2))
        self.assertEqual(retry.result, "succeeded")
        with self.assertRaises(ImmutableRecordError):
            retry.result = "failed"
            retry.save()

    def test_stale_instances_cannot_cross_cases_for_activation_outcomes_or_writeback(self):
        first = self._proposal()
        first_approval = self._approve(first)
        second = self._proposal()
        first_approval.allocation_id = second.id
        with self.assertRaises(DomainInvariantError):
            AllocationService().activate_for_approval(second, first_approval)
        self.assertEqual(InterventionAllocation.objects.get(pk=second.id).state, "proposed")

        delivery = DeliveryFeedbackService().record_delivery(
            case_id=self.case.id,
            allocation=first,
            actor_id=actor_for("adviser").id,
            result="completed",
            source="synthetic delivery record",
        )
        other_case = Case.objects.create(learner=self.learner, enrolment=self.enrolment)
        delivery.case_id = other_case.id
        CaptureService().record_safety_exit(
            self.capture, signal_metadata={"signal": "synthetic-sensitive-signal"}
        )
        with self.assertRaises(DomainInvariantError):
            DeliveryFeedbackService().record_outcome(
                delivery_event=delivery,
                actor_id="synthetic-learner-001",
                response="confirmed",
                exact_response="Must use the persisted delivery case.",
            )
        first_approval.allocation_id = second.id
        with self.assertRaises(DomainInvariantError):
            WritebackService().record_attempt(
                allocation=second, decision=first_approval, payload={"mock": "payload"}
            )

    def test_database_constraints_and_transactions_do_not_leave_partial_evidence(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Enrolment.objects.create(
                    learner=self.learner,
                    course_code="SYN-DUPLICATE",
                    cohort_code="SYN-COHORT",
                    source_row=1,
                    source_version="csv-v1",
                )
        proposal = self._proposal()
        with self.assertRaises(DomainInvariantError):
            SupportDecisionService().record(
                case_id=self.case.id,
                allocation=proposal,
                action="approve",
                actor=actor_for("adviser"),
                reason="No reviewed inputs means rollback.",
                reviewed_inputs=[],
                policy_version="decision-policy-v1",
                planner_version="planner-v1",
            )
        self.assertEqual(SupportDecision.objects.count(), 0)
        proposal.refresh_from_db()
        self.assertEqual(proposal.state, "proposed")
