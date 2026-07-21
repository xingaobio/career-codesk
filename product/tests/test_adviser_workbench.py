"""HTTP integration evidence for the bounded adviser decision workbench."""

from datetime import date

from django.test import TestCase

from career_codesk.modules.ai_gateway.contracts import (
    AiRequest,
    DeterministicFakeAdapter,
    SourceReference,
)
from career_codesk.modules.ai_gateway.services import AiGatewayService, HypothesisService
from career_codesk.modules.casework.models import Case
from career_codesk.modules.decisions.models import ReviewedInput, SupportDecision
from career_codesk.modules.intake_provenance.models import Enrolment, Learner, NeedCapture
from career_codesk.modules.intake_provenance.services import CaptureService
from career_codesk.modules.planning.contracts import (
    CapacitySlot,
    Demand,
    PlanningPolicy,
    PlanningRequest,
)
from career_codesk.modules.planning.models import InterventionAllocation, Need, PlannerRun
from career_codesk.modules.planning.services import (
    AllocationService,
    DeterministicPlanningService,
    PlannerRunService,
)


class AdviserWorkbenchTests(TestCase):
    def setUp(self):
        learner = Learner.objects.create(
            synthetic_identifier="synthetic-workbench-001", fixture_version="workbench-v1"
        )
        enrolment = Enrolment.objects.create(
            learner=learner,
            course_code="SYN-WORKBENCH",
            cohort_code="SYN-QUEUE",
            source_row=1,
            source_version="workbench-csv-v1",
        )
        self.case = Case.objects.create(learner=learner, enrolment=enrolment)
        self.capture = NeedCapture.objects.create(
            learner=learner,
            enrolment=enrolment,
            case_id=self.case.id,
            source_type="csv",
            source_payload={"statement": "Synthetic learner needs route comparison support."},
            source_version="workbench-csv-v1",
            source_row=1,
            field_allowlist_passed=True,
        )
        self.need = Need.objects.create(
            taxonomy_code="route-comparison",
            taxonomy_version="taxonomy-v1",
            permitted_routes=["guide"],
        )
        result = AiGatewayService(DeterministicFakeAdapter()).interpret(
            AiRequest(
                task_kind="need_hypothesis",
                source_records=(
                    SourceReference(self.capture.id, "need_capture", self.capture.source_version),
                ),
                input_metadata={"case_id": self.case.id, "capture_ids": [self.capture.id]},
                prompt_version="workbench-prompt-v1",
                output_schema_version="schema-v1",
                policy_version="workbench-ai-policy-v1",
            )
        )
        self.hypothesis = HypothesisService().record(
            case_id=self.case.id, captures=[self.capture], gateway_result=result
        )
        request = PlanningRequest(
            PlanningPolicy("workbench-policy-v1", ("guide",), 1),
            (
                Demand(
                    demand_id="workbench-demand-001",
                    case_id=self.case.id,
                    need_code=self.need.taxonomy_code,
                    route_code="guide",
                    barrier_key="route",
                    requested_on=date(2026, 7, 20),
                    deadline=date(2026, 7, 23),
                    minimum_entitlement=True,
                    source_record_ids=(self.capture.id,),
                    effort_hours=1,
                ),
            ),
            (
                CapacitySlot("adviser-a", "guide", date(2026, 7, 20), 1, 1, 1),
                CapacitySlot("adviser-b", "guide", date(2026, 7, 21), 1, 1, 1),
            ),
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
            demand_id="workbench-demand-001",
        )

    def _decision_data(self, allocation=None, **changes):
        allocation = allocation or self.proposal
        return {
            "action": "approve",
            "actor": "adviser",
            "reason": "The simulated adviser reviewed the source, inference, and capacity effect.",
            "planner_digest": PlannerRun.objects.get(pk=allocation.planner_run_id).result_digest,
            "decision_token": "root",
            **changes,
        }

    def _multi_demand_proposals(self):
        demand_ids = ("workbench-demand-a", "workbench-demand-b", "workbench-demand-c")
        request = PlanningRequest(
            PlanningPolicy("workbench-policy-v1", ("guide",), 1),
            tuple(
                Demand(
                    demand_id=demand_id,
                    case_id=self.case.id,
                    need_code=self.need.taxonomy_code,
                    route_code="guide",
                    barrier_key="route",
                    requested_on=date(2026, 7, 20),
                    deadline=date(2026, 7, 23),
                    minimum_entitlement=True,
                    source_record_ids=(self.capture.id,),
                    effort_hours=1,
                )
                for demand_id in demand_ids
            ),
            (
                CapacitySlot("adviser-a", "guide", date(2026, 7, 20), 1, 1, 1),
                CapacitySlot("adviser-b", "guide", date(2026, 7, 21), 1, 1, 1),
                CapacitySlot("adviser-c", "guide", date(2026, 7, 22), 1, 1, 1),
            ),
        )
        run = PlannerRunService().record(request, DeterministicPlanningService().plan(request))
        proposals = {
            demand_id: AllocationService().propose(
                case_id=self.case.id,
                need=self.need,
                route_code="guide",
                planner_run_id=run.id,
                planner_algorithm_version=run.algorithm_version,
                planner_policy_version=run.policy_version,
                hypothesis=self.hypothesis,
                demand_id=demand_id,
            )
            for demand_id in demand_ids
        }
        return proposals

    def _optional_demand_proposals(self):
        demand_ids = ("workbench-demand-required", "workbench-demand-optional")
        request = PlanningRequest(
            PlanningPolicy("workbench-policy-v1", ("guide",), 1, alternative_limit=8),
            (
                Demand(
                    demand_id=demand_ids[0],
                    case_id=self.case.id,
                    need_code=self.need.taxonomy_code,
                    route_code="guide",
                    barrier_key="route",
                    requested_on=date(2026, 7, 20),
                    deadline=date(2026, 7, 21),
                    minimum_entitlement=True,
                    source_record_ids=(self.capture.id,),
                ),
                Demand(
                    demand_id=demand_ids[1],
                    case_id=self.case.id,
                    need_code=self.need.taxonomy_code,
                    route_code="guide",
                    barrier_key="route",
                    requested_on=date(2026, 7, 20),
                    deadline=date(2026, 7, 21),
                    minimum_entitlement=False,
                    source_record_ids=(self.capture.id,),
                ),
            ),
            (
                CapacitySlot("adviser-a", "guide", date(2026, 7, 20), 1, 1, 1),
                CapacitySlot("adviser-b", "guide", date(2026, 7, 21), 1, 1, 1),
            ),
        )
        run = PlannerRunService().record(request, DeterministicPlanningService().plan(request))
        proposals = {
            demand_id: AllocationService().propose(
                case_id=self.case.id,
                need=self.need,
                route_code="guide",
                planner_run_id=run.id,
                planner_algorithm_version=run.algorithm_version,
                planner_policy_version=run.policy_version,
                hypothesis=self.hypothesis,
                demand_id=demand_id,
            )
            for demand_id in demand_ids
        }
        return proposals

    def test_review_queue_keeps_source_inference_uncertainty_and_rationale_separate(self):
        queue = self.client.get("/workbench/?sort=wait")
        self.assertContains(queue, "Sortable ordinary decision queue")
        self.assertContains(queue, "aria-sort", html=False)
        response = self.client.get(f"/workbench/{self.proposal.id}/")
        self.assertContains(response, "Synthetic mock source — no MIS connection.")
        self.assertContains(response, "Provisional AI inference")
        self.assertContains(response, "Provisional — no decision authority")
        self.assertContains(response, "Unknowns")
        self.assertContains(response, "Deterministic proposal and capacity effect")
        self.assertContains(response, "Feasible alternatives")
        self.assertContains(response, "Simulated identity only")

    def test_confirmed_approval_creates_audit_records_and_replans_capacity(self):
        preview = self.client.post(f"/workbench/{self.proposal.id}/confirm/", self._decision_data())
        self.assertContains(preview, "Confirm approve decision")
        response = self.client.post(f"/workbench/{self.proposal.id}/decide/", self._decision_data())
        self.assertContains(response, "Decision recorded")
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.state, "active")
        self.assertEqual(SupportDecision.objects.count(), 1)
        self.assertGreaterEqual(ReviewedInput.objects.count(), 2)
        replanned = PlannerRun.objects.exclude(pk=self.run.id).get()
        self.assertEqual(replanned.canonical_input["capacity_slots"][0]["seats"], 0)
        self.assertEqual(replanned.canonical_result["primary"]["allocations"], [])

    def test_amendment_selects_a_feasible_alternative_without_activation(self):
        confirmation = self.client.post(
            f"/workbench/{self.proposal.id}/confirm/",
            self._decision_data(action="amend", alternative_index="1"),
        )
        self.assertContains(confirmation, "Selected amendment target")
        self.assertContains(confirmation, "adviser-b")
        self.assertContains(confirmation, "2026-07-21")
        self.assertContains(confirmation, "1 waiting day")
        self.assertContains(confirmation, "0 remaining seats")
        response = self.client.post(
            f"/workbench/{self.proposal.id}/decide/",
            self._decision_data(action="amend", alternative_index="1"),
        )
        self.assertContains(response, "Amendment follow-up")
        self.assertContains(response, "adviser-b on 2026-07-21")
        self.assertContains(response, "0 seats")
        self.proposal.refresh_from_db()
        replacement = InterventionAllocation.objects.exclude(pk=self.proposal.id).get()
        self.assertEqual(self.proposal.state, "inactive")
        self.assertEqual(replacement.state, "proposed")
        self.assertEqual(replacement.supersedes_id, self.proposal.id)
        self.assertEqual(replacement.resource_id, "adviser-b")
        amended_run = PlannerRun.objects.get(pk=replacement.planner_run_id)
        self.assertEqual(
            amended_run.canonical_result["primary"]["allocations"][0]["resource_id"], "adviser-b"
        )
        self.assertEqual(
            amended_run.canonical_result["primary"]["allocations"][0]["waiting_days"], 1
        )
        self.assertEqual(
            amended_run.canonical_result["primary"]["resource_consumption"][0]["seats_consumed"], 1
        )
        approval = self.client.post(
            f"/workbench/{replacement.id}/decide/",
            self._decision_data(
                replacement,
                decision_token=SupportDecision.objects.get(allocation=self.proposal).id,
            ),
        )
        self.assertContains(approval, "Approve event recorded")
        replacement.refresh_from_db()
        self.assertEqual(replacement.state, "active")
        self.assertEqual(
            SupportDecision.objects.get(allocation=replacement).predecessor_id,
            SupportDecision.objects.get(allocation=self.proposal).id,
        )
        reversal = self.client.post(
            f"/workbench/{replacement.id}/decide/",
            self._decision_data(
                replacement,
                action="amend",
                alternative_index="1",
                decision_token=SupportDecision.objects.get(allocation=replacement).id,
            ),
        )
        self.assertContains(reversal, "Amendment follow-up")
        self.assertContains(reversal, "adviser-a on 2026-07-20")
        reversed_proposal = InterventionAllocation.objects.get(supersedes=replacement)
        self.assertEqual(reversed_proposal.state, "proposed")
        self.assertEqual(reversed_proposal.resource_id, "adviser-a")
        reversed_run = PlannerRun.objects.get(pk=reversed_proposal.planner_run_id)
        self.assertEqual(
            reversed_run.canonical_result["primary"]["allocations"][0]["resource_id"], "adviser-a"
        )
        self.assertEqual(
            reversed_run.canonical_result["primary"]["allocations"][0]["waiting_days"], 0
        )
        self.assertEqual(
            SupportDecision.objects.get(allocation=replacement, action="amend").predecessor_id,
            SupportDecision.objects.get(allocation=replacement, action="approve").id,
        )

    def test_surviving_queue_proposals_rebind_to_each_replanning_run(self):
        original = self._multi_demand_proposals()
        self.client.post(
            f"/workbench/{original['workbench-demand-a'].id}/decide/",
            self._decision_data(original["workbench-demand-a"]),
        )
        first_b = InterventionAllocation.objects.get(supersedes=original["workbench-demand-b"])
        first_c = InterventionAllocation.objects.get(supersedes=original["workbench-demand-c"])
        self.assertEqual(original["workbench-demand-b"].state, "proposed")
        original["workbench-demand-b"].refresh_from_db()
        original["workbench-demand-c"].refresh_from_db()
        self.assertEqual(original["workbench-demand-b"].state, "inactive")
        self.assertEqual(original["workbench-demand-c"].state, "inactive")
        self.assertEqual(first_b.waiting_days, 1)
        self.assertEqual(first_c.waiting_days, 2)
        self.assertNotEqual(first_b.planner_run_id, original["workbench-demand-b"].planner_run_id)

        self.client.post(
            f"/workbench/{first_b.id}/decide/",
            self._decision_data(first_b, action="reject"),
        )
        first_c.refresh_from_db()
        refreshed_c = InterventionAllocation.objects.get(supersedes=first_c)
        self.assertEqual(first_c.state, "inactive")
        self.assertEqual(refreshed_c.waiting_days, 1)
        self.assertNotEqual(refreshed_c.planner_run_id, first_c.planner_run_id)
        review = self.client.get(f"/workbench/{refreshed_c.id}/")
        self.assertContains(review, "1 day")
        self.assertContains(review, "0 seats")

    def test_amendment_retires_a_proposal_that_becomes_explicit_unmet_demand(self):
        original = self._optional_demand_proposals()
        response = self.client.post(
            f"/workbench/{original['workbench-demand-required'].id}/decide/",
            self._decision_data(
                original["workbench-demand-required"],
                action="amend",
                alternative_index="2",
            ),
        )
        self.assertContains(response, "Explicit unmet demand")
        original["workbench-demand-optional"].refresh_from_db()
        self.assertEqual(original["workbench-demand-optional"].state, "inactive")
        self.assertFalse(
            InterventionAllocation.objects.filter(
                state="proposed", demand_id="workbench-demand-optional"
            ).exists()
        )
        replacement = InterventionAllocation.objects.get(
            supersedes=original["workbench-demand-required"]
        )
        selected_run = PlannerRun.objects.get(pk=replacement.planner_run_id)
        self.assertEqual(
            selected_run.canonical_result["primary"]["unmet_demand"][0]["demand_id"],
            "workbench-demand-optional",
        )

    def test_initial_rejection_releases_the_demand_and_stale_or_forged_posts_do_not_mutate(self):
        stale = self.client.post(
            f"/workbench/{self.proposal.id}/decide/",
            self._decision_data(planner_digest="stale"),
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(SupportDecision.objects.count(), 0)
        forged = self.client.post(
            f"/workbench/{self.proposal.id}/decide/",
            self._decision_data(actor="manager"),
        )
        self.assertEqual(forged.status_code, 400)
        self.assertEqual(SupportDecision.objects.count(), 0)
        response = self.client.post(
            f"/workbench/{self.proposal.id}/decide/", self._decision_data(action="reject")
        )
        self.assertContains(response, "Reject event recorded")
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.state, "inactive")
        replanned = PlannerRun.objects.exclude(pk=self.run.id).get()
        self.assertEqual(replanned.canonical_result["primary"]["unmet_demand"], [])

    def test_restricted_safety_case_is_absent_from_queue_and_ordinary_detail(self):
        CaptureService().record_safety_exit(
            self.capture, signal_metadata={"signal": "synthetic-sensitive-signal"}
        )
        queue = self.client.get("/workbench/")
        self.assertNotContains(queue, self.proposal.id)
        response = self.client.get(f"/workbench/{self.proposal.id}/")
        self.assertEqual(response.status_code, 404)
