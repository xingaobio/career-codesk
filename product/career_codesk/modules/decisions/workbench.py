"""Read models and commands for the local, adviser-owned decision workbench.

The workbench deliberately reads immutable evidence from the shared store.  It
does not create a second case profile, make an AI decision, or treat an HTML
form actor value as authentication.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.db import transaction

from career_codesk.domain import DomainInvariantError
from career_codesk.identity import SimulatedActor
from career_codesk.modules.ai_gateway.models import NeedHypothesis
from career_codesk.modules.intake_provenance.models import NeedCapture, SafetyExit
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

from .models import SupportDecision
from .services import SupportDecisionService


class StaleWorkbenchInput(DomainInvariantError):
    """The screen was rendered from an older planner or decision history."""


@dataclass(frozen=True)
class DecisionOutcome:
    decision: SupportDecision
    replanned_run: PlannerRun
    next_proposal: Optional[InterventionAllocation] = None

    @property
    def remaining_plan(self):
        return self.replanned_run.canonical_result["primary"]

    @property
    def remaining_capacity(self):
        consumption = {
            (item["resource_id"], item["route_code"], item["scheduled_on"]): item
            for item in self.remaining_plan["resource_consumption"]
        }
        return tuple(
            {
                "resource_id": slot["resource_id"],
                "route_code": slot["route_code"],
                "scheduled_on": slot["available_on"],
                "seats": max(
                    0,
                    slot["seats"]
                    - consumption.get(
                        (slot["resource_id"], slot["route_code"], slot["available_on"]), {}
                    ).get("seats_consumed", 0),
                ),
                "adviser_hours": max(
                    0,
                    slot["adviser_hours"]
                    - consumption.get(
                        (slot["resource_id"], slot["route_code"], slot["available_on"]), {}
                    ).get("adviser_hours_consumed", 0),
                ),
            }
            for slot in self.replanned_run.canonical_input["capacity_slots"]
        )


class WorkbenchQueryService:
    """Small, deterministic projection for ordinary (never restricted) review."""

    def __init__(self, *, as_of: date = date(2026, 7, 20)):
        self.as_of = as_of

    @staticmethod
    def restricted_case_ids():
        return set(
            NeedCapture.objects.filter(
                pk__in=SafetyExit.objects.values("source_capture_id")
            ).values_list("case_id", flat=True)
        )

    def queue(self, *, sort="age"):
        sort_fields = {
            "age": ("created_at", "id"),
            "wait": ("waiting_days", "created_at", "id"),
            "case": ("case_id", "id"),
            "route": ("route_code", "id"),
        }
        if sort not in sort_fields:
            sort = "age"
        allocations = (
            InterventionAllocation.objects.select_related("need", "hypothesis")
            .filter(state="proposed")
            .exclude(case_id__in=self.restricted_case_ids())
            .order_by(*sort_fields[sort])
        )
        return [self.detail(allocation) for allocation in allocations]

    def get(self, allocation_id):
        allocation = (
            InterventionAllocation.objects.select_related("need", "hypothesis")
            .filter(pk=allocation_id)
            .exclude(case_id__in=self.restricted_case_ids())
            .first()
        )
        return self.detail(allocation) if allocation else None

    def detail(self, allocation):
        captures = list(
            NeedCapture.objects.filter(case_id=allocation.case_id)
            .exclude(pk__in=SafetyExit.objects.values("source_capture_id"))
            .order_by("created_at", "id")
        )
        hypotheses = list(
            NeedHypothesis.objects.filter(case_id=allocation.case_id)
            .prefetch_related("inputs")
            .order_by("created_at", "id")
        )
        run = PlannerRun.objects.get(pk=allocation.planner_run_id)
        plans = [run.canonical_result["primary"], *run.canonical_result.get("alternatives", [])]
        plan = plans[allocation.plan_variant]
        alternatives = []
        for index, alternative in enumerate(plans):
            selected = next(
                (
                    item
                    for item in alternative["allocations"]
                    if item["demand_id"] == allocation.demand_id
                ),
                None,
            )
            if selected and index != allocation.plan_variant:
                alternatives.append(
                    {
                        "index": index,
                        "allocation": selected,
                        "capacity": self._capacity_effect(run, alternative, selected),
                    }
                )
        capacity = self._capacity_effect(
            run,
            plan,
            {
                "resource_id": allocation.resource_id,
                "route_code": allocation.route_code,
                "scheduled_on": allocation.scheduled_on.isoformat(),
            },
        )
        age_days = max(0, (self.as_of - allocation.created_at.date()).days)
        latest = (
            SupportDecision.objects.filter(allocation=allocation)
            .order_by("created_at", "id")
            .last()
        )
        inherited = None
        if latest is None and allocation.supersedes_id:
            inherited = (
                SupportDecision.objects.filter(allocation_id=allocation.supersedes_id)
                .order_by("created_at", "id")
                .last()
            )
        return {
            "allocation": allocation,
            "captures": captures,
            "hypotheses": hypotheses,
            "run": run,
            "plan": plan,
            "alternatives": alternatives,
            "queue_age_days": age_days,
            "unmet_demand": plan["unmet_demand"],
            "capacity": capacity,
            "decision_token": (latest or inherited).id if (latest or inherited) else "root",
            "planner_digest": run.result_digest,
        }

    @staticmethod
    def _capacity_effect(run, plan, allocation):
        slot = next(
            (
                item
                for item in run.canonical_input["capacity_slots"]
                if item["resource_id"] == allocation["resource_id"]
                and item["route_code"] == allocation["route_code"]
                and item["available_on"] == allocation["scheduled_on"]
            ),
            None,
        )
        consumed = next(
            (
                item
                for item in plan["resource_consumption"]
                if item["resource_id"] == allocation["resource_id"]
                and item["route_code"] == allocation["route_code"]
                and item["scheduled_on"] == allocation["scheduled_on"]
            ),
            None,
        )
        return {
            "slot": slot,
            "consumed": consumed,
            "remaining_seats": max(
                0, (slot or {}).get("seats", 0) - (consumed or {}).get("seats_consumed", 0)
            ),
            "remaining_adviser_hours": max(
                0,
                (slot or {}).get("adviser_hours", 0)
                - (consumed or {}).get("adviser_hours_consumed", 0),
            ),
        }


class DecisionWorkbenchService:
    """Stale-safe command boundary that always recalculates deterministic evidence."""

    @transaction.atomic
    def decide(
        self,
        *,
        allocation_id,
        action,
        actor: SimulatedActor,
        reason,
        reviewed_inputs,
        expected_planner_digest,
        expected_decision_token,
        alternative_index=None,
    ):
        allocation = InterventionAllocation.objects.select_for_update().get(pk=allocation_id)
        can_retire_active = allocation.state == "active" and action in {"amend", "reject"}
        if allocation.state != "proposed" and not can_retire_active:
            raise StaleWorkbenchInput("This proposal is no longer awaiting review")
        run = PlannerRun.objects.select_for_update().get(pk=allocation.planner_run_id)
        latest = (
            SupportDecision.objects.filter(allocation=allocation)
            .order_by("created_at", "id")
            .last()
        )
        inherited = None
        if latest is None and allocation.supersedes_id:
            inherited = (
                SupportDecision.objects.filter(allocation_id=allocation.supersedes_id)
                .order_by("created_at", "id")
                .last()
            )
        predecessor = latest or inherited
        actual_token = predecessor.id if predecessor else "root"
        if run.result_digest != expected_planner_digest or actual_token != expected_decision_token:
            raise StaleWorkbenchInput("The plan or decision history changed; review it again")
        if not reason or not reason.strip():
            raise DomainInvariantError("A decision reason is required")
        if not reviewed_inputs:
            raise DomainInvariantError("Reviewed source and provisional evidence are required")

        decision = SupportDecisionService().record(
            case_id=allocation.case_id,
            allocation=allocation,
            action=action,
            actor=actor,
            reason=reason.strip(),
            reviewed_inputs=reviewed_inputs,
            policy_version=run.policy_version,
            planner_version=run.algorithm_version,
            predecessor=predecessor,
        )
        selected_plan_index = None
        if action == "amend":
            selected_plan_index = self._selected_plan_index(allocation, run, alternative_index)
        replanned_run = self._replan(
            run,
            excluded_demand_id=allocation.demand_id if action == "reject" else None,
            selected_plan_index=selected_plan_index,
        )
        refreshed = self._refresh_remaining_proposals(
            replanned_run,
            successor_for=allocation if action == "amend" else None,
        )
        next_proposal = refreshed.get((allocation.case_id, allocation.demand_id))
        return DecisionOutcome(
            decision=decision, replanned_run=replanned_run, next_proposal=next_proposal
        )

    @staticmethod
    def _selected_plan_index(allocation, run, alternative_index):
        try:
            selected = int(alternative_index)
        except (TypeError, ValueError) as error:
            raise DomainInvariantError("Choose a feasible alternative before amending") from error
        plans = [run.canonical_result["primary"], *run.canonical_result.get("alternatives", [])]
        if selected < 0 or selected >= len(plans) or selected == allocation.plan_variant:
            raise DomainInvariantError("Choose a feasible alternative before amending")
        if not any(
            item["demand_id"] == allocation.demand_id for item in plans[selected]["allocations"]
        ):
            raise DomainInvariantError("The selected alternative does not serve this demand")
        return selected

    def _replan(self, source_run, *, excluded_demand_id=None, selected_plan_index=None):
        request = self._request_from_canonical(source_run.canonical_input)
        source_demand_ids = {item.demand_id for item in request.demands}
        active = InterventionAllocation.objects.filter(
            state="active", demand_id__in=source_demand_ids
        ).exclude(demand_id="legacy-unbound")
        active_ids = set(active.values_list("demand_id", flat=True))
        excluded = active_ids | ({excluded_demand_id} if excluded_demand_id else set())
        slots = []
        for slot in request.capacity_slots:
            matching = [
                item
                for item in active
                if item.resource_id == slot.resource_id
                and item.route_code == slot.route_code
                and item.scheduled_on == slot.available_on
            ]
            slots.append(
                CapacitySlot(
                    slot.resource_id,
                    slot.route_code,
                    slot.available_on,
                    max(0, slot.seats - len(matching)),
                    max(0, slot.adviser_hours - sum(item.effort_hours for item in matching)),
                    max(0, slot.room_capacity - len(matching)),
                    slot.external_provider,
                )
            )
        replanning_request = PlanningRequest(
            request.policy,
            tuple(item for item in request.demands if item.demand_id not in excluded),
            tuple(slots),
        )
        if selected_plan_index is not None:
            return PlannerRunService().record_selected_plan(
                replanning_request, source_run, selected_plan_index
            )
        result = DeterministicPlanningService.plan(replanning_request)
        return PlannerRunService().record(replanning_request, result)

    @staticmethod
    def _refresh_remaining_proposals(replanned_run, *, successor_for=None):
        """Replace stale pending projections with evidence from the new planner run."""
        primary = replanned_run.canonical_result["primary"]["allocations"]
        covered_bindings = {
            (item["case_id"], item["demand_id"])
            for item in replanned_run.canonical_input["demands"]
        }
        stale = list(
            InterventionAllocation.objects.select_related("need", "hypothesis")
            .filter(
                state="proposed",
                case_id__in={case_id for case_id, _ in covered_bindings},
                demand_id__in={demand_id for _, demand_id in covered_bindings},
            )
            .order_by("created_at", "id")
        )
        prior_by_demand = {}
        for proposal in stale:
            if (proposal.case_id, proposal.demand_id) not in covered_bindings:
                continue
            AllocationService().retire_stale_proposal(proposal)
            prior_by_demand[(proposal.case_id, proposal.demand_id)] = proposal
        if successor_for is not None:
            prior_by_demand[(successor_for.case_id, successor_for.demand_id)] = successor_for
        refreshed = {}
        for planned in primary:
            demand_id = planned["demand_id"]
            prior = prior_by_demand.get((planned["case_id"], demand_id))
            need = (
                prior.need
                if prior
                else Need.objects.filter(taxonomy_code=planned["need_code"])
                .order_by("taxonomy_version", "id")
                .first()
            )
            if need is None:
                raise DomainInvariantError("Replanned demand has no persisted need taxonomy record")
            proposal = AllocationService().propose(
                case_id=planned["case_id"],
                need=need,
                route_code=planned["route_code"],
                planner_run_id=replanned_run.id,
                planner_algorithm_version=replanned_run.algorithm_version,
                planner_policy_version=replanned_run.policy_version,
                hypothesis=prior.hypothesis if prior else None,
                demand_id=demand_id,
                supersedes=prior,
            )
            refreshed[(planned["case_id"], demand_id)] = proposal
        return refreshed

    @staticmethod
    def _request_from_canonical(value):
        policy = value["policy"]
        return PlanningRequest(
            PlanningPolicy(
                policy["version"],
                tuple(policy["approved_intervention_types"]),
                policy["maximum_group_size"],
                tuple(tuple(pair) for pair in policy["compatible_barrier_pairs"]),
                policy["alternative_limit"],
            ),
            tuple(
                Demand(
                    demand_id=item["demand_id"],
                    case_id=item["case_id"],
                    need_code=item["need_code"],
                    route_code=item["route_code"],
                    barrier_key=item["barrier_key"],
                    requested_on=date.fromisoformat(item["requested_on"]),
                    deadline=date.fromisoformat(item["deadline"]),
                    minimum_entitlement=item["minimum_entitlement"],
                    evidence_status=item["evidence_status"],
                    human_review_required=item["human_review_required"],
                    alternative_route_codes=tuple(item["alternative_route_codes"]),
                    source_record_ids=tuple(item["source_record_ids"]),
                    effort_hours=item["effort_hours"],
                )
                for item in value["demands"]
            ),
            tuple(
                CapacitySlot(
                    item["resource_id"],
                    item["route_code"],
                    date.fromisoformat(item["available_on"]),
                    item["seats"],
                    item["adviser_hours"],
                    item["room_capacity"],
                    item["external_provider"],
                )
                for item in value["capacity_slots"]
            ),
        )
