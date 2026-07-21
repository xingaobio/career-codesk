"""Acceptance evidence for approval-gated plans, local exports, and learner feedback."""

from datetime import date

from django.test import TestCase

from career_codesk.domain import DomainInvariantError
from career_codesk.modules.ai_gateway.contracts import (
    AiRequest,
    DeterministicFakeAdapter,
    SourceReference,
)
from career_codesk.modules.ai_gateway.services import AiGatewayService, HypothesisService
from career_codesk.modules.casework.models import Case
from career_codesk.modules.delivery_feedback.models import (
    DeliveryEvent,
    LearnerActionFeedback,
    OutcomeConfirmation,
)
from career_codesk.modules.export.models import StructuredExport
from career_codesk.modules.export.services import WritebackService
from career_codesk.modules.intake_provenance.models import Enrolment, Learner, NeedCapture
from career_codesk.modules.planning.contracts import (
    CapacitySlot,
    Demand,
    PlanningPolicy,
    PlanningRequest,
)
from career_codesk.modules.planning.models import (
    AdviserBrief,
    InterventionAllocation,
    Need,
    WeeklyPlanEntry,
)
from career_codesk.modules.planning.services import (
    AllocationService,
    DeterministicPlanningService,
    ExecutionPackageService,
    PlannerRunService,
)


class PlanExportFeedbackTests(TestCase):
    def setUp(self):
        learner = Learner.objects.create(
            synthetic_identifier="synthetic-plan-feedback-001", fixture_version="plan-feedback-v1"
        )
        enrolment = Enrolment.objects.create(
            learner=learner,
            course_code="SYN-PLAN",
            cohort_code="SYN-QUEUE",
            source_row=1,
            source_version="plan-feedback-csv-v1",
        )
        self.case = Case.objects.create(learner=learner, enrolment=enrolment)
        self.capture = NeedCapture.objects.create(
            learner=learner,
            enrolment=enrolment,
            case_id=self.case.id,
            source_type="csv",
            source_payload={"statement": "Synthetic learner needs help comparing routes."},
            source_version="plan-feedback-csv-v1",
            source_row=1,
            field_allowlist_passed=True,
        )
        self.need = Need.objects.create(
            taxonomy_code="route-comparison",
            taxonomy_version="plan-feedback-v1",
            permitted_routes=["guide"],
        )
        gateway = AiGatewayService(DeterministicFakeAdapter()).interpret(
            AiRequest(
                task_kind="need_hypothesis",
                source_records=(
                    SourceReference(self.capture.id, "need_capture", self.capture.source_version),
                ),
                input_metadata={"case_id": self.case.id, "capture_ids": [self.capture.id]},
                prompt_version="plan-feedback-prompt-v1",
                output_schema_version="schema-v1",
                policy_version="plan-feedback-ai-policy-v1",
            )
        )
        self.hypothesis = HypothesisService().record(
            case_id=self.case.id, captures=[self.capture], gateway_result=gateway
        )
        request = PlanningRequest(
            PlanningPolicy("plan-feedback-policy-v1", ("guide",), 1),
            (
                Demand(
                    demand_id="plan-feedback-demand",
                    case_id=self.case.id,
                    need_code=self.need.taxonomy_code,
                    route_code="guide",
                    barrier_key="route",
                    requested_on=date(2026, 7, 20),
                    deadline=date(2026, 7, 24),
                    minimum_entitlement=True,
                    source_record_ids=(self.capture.id,),
                    effort_hours=2,
                ),
            ),
            (CapacitySlot("synthetic-adviser", "guide", date(2026, 7, 21), 1, 2, 1),),
        )
        self.run = PlannerRunService().record(request, DeterministicPlanningService().plan(request))
        self.proposal = AllocationService().propose(
            case_id=self.case.id,
            need=self.need,
            route_code="guide",
            planner_run_id=self.run.id,
            planner_algorithm_version=self.run.algorithm_version,
            planner_policy_version=self.run.policy_version,
            hypothesis=self.hypothesis,
            demand_id="plan-feedback-demand",
        )

    def _approval_data(self):
        return {
            "action": "approve",
            "actor": "adviser",
            "reason": "Reviewed source, provisional interpretation and capacity.",
            "planner_digest": self.run.result_digest,
            "decision_token": "root",
        }

    def test_only_approved_active_allocation_creates_one_execution_package(self):
        self.assertEqual(WeeklyPlanEntry.objects.count(), 0)
        self.assertEqual(StructuredExport.objects.count(), 0)
        response = self.client.post(f"/workbench/{self.proposal.id}/decide/", self._approval_data())
        self.assertContains(response, "Decision recorded")
        entry = WeeklyPlanEntry.objects.get()
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.state, "active")
        self.assertEqual(entry.need_id, self.need.id)
        self.assertEqual(entry.decision.action, "approve")
        self.assertEqual(entry.planner_run_id, self.run.id)
        self.assertEqual(entry.deadline.isoformat(), "2026-07-24")
        self.assertEqual(entry.reviewed_capture_ids, [self.capture.id])
        self.assertEqual(entry.reviewed_hypothesis_ids, [self.hypothesis.id])
        self.assertEqual(AdviserBrief.objects.count(), 1)
        self.assertIn("Source capture", entry.adviser_brief.known_facts)
        self.assertIn("Do not treat provisional", entry.adviser_brief.assumptions_prohibited)
        replay = ExecutionPackageService().create_or_replay(decision=entry.decision)
        self.assertEqual(replay[0].id, entry.id)
        self.assertEqual(WeeklyPlanEntry.objects.count(), 1)
        detail = self.client.get(f"/plans/{entry.id}/")
        self.assertContains(detail, f"/workbench/{entry.allocation_id}/")
        self.assertContains(detail, f"/learner/{entry.case_id}/")
        approval_evidence = self.client.get(f"/workbench/{entry.allocation_id}/")
        self.assertContains(approval_evidence, "Review approved guide route")
        self.assertContains(approval_evidence, "Decision already recorded")
        self.assertNotContains(approval_evidence, "Record an adviser decision")

    def test_export_is_canonical_retryable_and_terminal_success_replays(self):
        self.client.post(f"/workbench/{self.proposal.id}/decide/", self._approval_data())
        export = StructuredExport.objects.get()
        self.assertEqual(export.destination, "local-mock-outbox")
        self.assertEqual(
            export.payload_digest,
            WritebackService()
            .create_or_replay_export(
                weekly_entry=export.weekly_entry,
                decision=export.decision,
                allocation=export.allocation,
            )
            .payload_digest,
        )
        pending = WritebackService().record_attempt(
            allocation=export.allocation,
            decision=export.decision,
            payload=export.canonical_payload,
            payload_version=export.payload_version,
            result="pending",
        )
        self.assertEqual(pending.structured_export_id, export.id)
        self.assertEqual(pending.payload_digest, export.payload_digest)
        with self.assertRaisesRegex(DomainInvariantError, "canonical structured export"):
            WritebackService().record_attempt(
                allocation=export.allocation,
                decision=export.decision,
                payload={"different": "payload"},
                result="failed",
            )
        failed = WritebackService().record_attempt(
            allocation=export.allocation,
            decision=export.decision,
            structured_export=export,
            result="failed",
            failure_reason="simulated local persistence failure",
        )
        succeeded = WritebackService().record_attempt(
            allocation=export.allocation,
            decision=export.decision,
            structured_export=export,
            result="succeeded",
        )
        replay = WritebackService().record_attempt(
            allocation=export.allocation,
            decision=export.decision,
            structured_export=export,
            result="succeeded",
        )
        self.assertEqual(
            (pending.attempt_number, failed.attempt_number, succeeded.attempt_number), (1, 2, 3)
        )
        self.assertEqual(replay.id, succeeded.id)
        self.assertEqual(
            WritebackService().reconcile_local_state(structured_export=export), "succeeded"
        )

    def test_http_approval_to_learner_unresolved_feedback_reopens_with_history(self):
        self.client.post(f"/workbench/{self.proposal.id}/decide/", self._approval_data())
        entry = WeeklyPlanEntry.objects.get()
        attempt = WritebackService().record_attempt(
            allocation=entry.allocation,
            decision=entry.decision,
            structured_export=entry.structured_export,
            result="not_sent",
        )
        self.assertEqual(attempt.result, "not_sent")
        learner = self.client.get(f"/learner/{self.case.id}/")
        self.assertContains(learner, "Your one approved next action")
        self.assertContains(learner, "Reviewed source, provisional interpretation and capacity.")
        self.assertContains(learner, "about 2 hours")
        self.assertContains(learner, "Request human help")
        self.assertContains(learner, "Correct a source statement")
        response = self.client.post(
            f"/learner/actions/{entry.id}/feedback/",
            {"kind": "unresolved", "response": "The synthetic route choice is still unresolved."},
        )
        self.assertContains(response, "Feedback recorded")
        self.case.refresh_from_db()
        self.assertEqual(self.case.state, "open")
        feedback = LearnerActionFeedback.objects.get(kind="unresolved")
        delivery = DeliveryEvent.objects.get(
            case_id=self.case.id,
            allocation=entry.allocation,
            actor_id="synthetic-learner-local-view",
        )
        outcome = OutcomeConfirmation.objects.get(delivery_event=delivery)
        review = self.case.review_requests.get(feedback_id=feedback.id)
        self.assertEqual(feedback.weekly_entry_id, entry.id)
        self.assertEqual(outcome.response, "unresolved")
        self.assertEqual(outcome.exact_response, feedback.exact_response)
        self.assertEqual(review.case_id, self.case.id)
        self.client.post(
            f"/learner/actions/{entry.id}/feedback/",
            {"kind": "human_help", "response": "Please ask an adviser to help."},
        )
        correction = self.client.post(
            f"/learner/actions/{entry.id}/feedback/",
            {
                "kind": "correction",
                "correction_statement": "Synthetic learner now needs a different route comparison.",
            },
        )
        self.assertContains(correction, "Feedback recorded")
        correction_feedback = LearnerActionFeedback.objects.get(kind="correction")
        self.assertEqual(correction_feedback.correction_capture.supersedes_id, self.capture.id)
        self.assertEqual(self.case.review_requests.count(), 3)
        self.assertEqual(InterventionAllocation.objects.get(pk=self.proposal.id).state, "active")
        export = entry.structured_export
        self.assertEqual(export.decision_id, entry.decision_id)
        self.assertEqual(export.allocation_id, entry.allocation_id)
        self.assertLessEqual(self.capture.created_at, self.hypothesis.created_at)
        self.assertLessEqual(self.hypothesis.created_at, entry.decision.created_at)
        self.assertLessEqual(entry.decision.created_at, entry.created_at)
        self.assertLessEqual(entry.created_at, export.created_at)
        self.assertLessEqual(export.created_at, attempt.created_at)
        self.assertLessEqual(attempt.created_at, feedback.created_at)
        self.assertLessEqual(feedback.created_at, delivery.created_at)
        self.assertLessEqual(delivery.created_at, outcome.created_at)
        self.assertLessEqual(outcome.created_at, review.created_at)
