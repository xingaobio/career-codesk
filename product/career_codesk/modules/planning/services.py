"""Deterministic feasibility and the narrow lifecycle for allocation proposals."""

import json
from collections import defaultdict
from dataclasses import dataclass

from django.db import transaction

from career_codesk.domain import DomainInvariantError, _authorize_projection_state_change
from career_codesk.modules.ai_gateway.contracts import (
    AiRequest,
    SourceReference,
    canonical_request_digest,
    payload_errors,
    validate_request,
)
from career_codesk.modules.ai_gateway.contracts import (
    canonical_digest as ai_canonical_digest,
)
from career_codesk.modules.ai_gateway.models import NeedHypothesis
from career_codesk.modules.casework.models import Case
from career_codesk.modules.intake_provenance.models import NeedCapture
from career_codesk.modules.intake_provenance.services import case_has_safety_exit

from .contracts import (
    CapacitySlot,
    FeasibilityPlan,
    PlannedAllocation,
    PlannerIdentity,
    PlanningRequest,
    PlanningResult,
    ResourceConsumption,
    UnmetDemand,
    canonical_digest,
    canonical_json,
)
from .models import InterventionAllocation, Need, PlannerRun


@dataclass(frozen=True)
class _Choice:
    demand_id: str
    slot: CapacitySlot
    route_code: str


class DeterministicPlanningService:
    """Deterministic planner over explicit synthetic policy inputs.

    It is intentionally pure: persistence timestamps and IDs do not take part in
    feasibility.  Alternative output is bounded by policy while preserving the
    primary plan's achieved minimum entitlements.
    """

    algorithm_version = "capacity-planner-v1"
    seed = 20260720

    @classmethod
    def identity(cls, policy_version="planning-policy-v1"):
        return PlannerIdentity(cls.algorithm_version, policy_version, cls.seed)

    @classmethod
    def plan(cls, request: PlanningRequest) -> PlanningResult:
        identity = cls.identity(request.policy.version)
        demands = tuple(
            sorted(
                request.demands,
                key=lambda item: (
                    not item.minimum_entitlement,
                    item.deadline,
                    item.demand_id,
                ),
            )
        )
        slots = tuple(
            sorted(
                request.capacity_slots,
                key=lambda item: (item.available_on, item.resource_id, item.route_code),
            )
        )
        candidates = {
            demand.demand_id: cls._candidates(demand, slots, request) for demand in demands
        }
        primary = cls._render(request, cls._optimal_primary(request, demands, candidates))
        alternatives = cls._entitlement_preserving_alternatives(
            request, demands, candidates, primary
        )
        return PlanningResult(identity=identity, primary=primary, alternatives=alternatives)

    @staticmethod
    def _candidates(demand, slots, request):
        approved_routes = tuple(
            sorted(set(demand.route_options) & set(request.policy.approved_intervention_types))
        )
        if not approved_routes:
            return ()
        return tuple(
            _Choice(demand.demand_id, slot, route)
            for route in approved_routes
            for slot in slots
            if slot.route_code == route
            and demand.requested_on <= slot.available_on <= demand.deadline
            and min(slot.seats, slot.adviser_hours, slot.room_capacity) > 0
        )

    @classmethod
    def _optimal_primary(cls, request, demands, candidates):
        """Return the globally ranked plan without applying the alternative bound.

        The bounded DFS below exists only to retain useful alternatives.  It cannot
        participate in primary selection because its route-first traversal could
        otherwise stop before reaching a route needed for a mandatory demand.
        """

        best_choices = ()
        best_rank = None

        def search(position, choices, groups):
            nonlocal best_choices, best_rank
            if position == len(demands):
                rank = cls._rank(cls._render(request, choices), demands)
                if best_rank is None or rank < best_rank:
                    best_choices = choices
                    best_rank = rank
                return

            demand = demands[position]
            for choice in candidates[demand.demand_id]:
                if not cls._choice_fits(request, demand, choice, groups):
                    continue
                slot_key = (
                    choice.slot.resource_id,
                    choice.slot.route_code,
                    choice.slot.available_on,
                )
                next_groups = dict(groups)
                next_groups[slot_key] = next_groups.get(slot_key, ()) + (demand,)
                search(position + 1, choices + (choice,), next_groups)
            # An unmet demand is a valid, explicit outcome, including when no
            # allocation can satisfy an entitlement.
            search(position + 1, choices, groups)

        search(0, (), {})
        return best_choices

    @classmethod
    def _entitlement_preserving_alternatives(cls, request, demands, candidates, primary):
        """Find distinct alternatives without relaxing achieved entitlements.

        The remaining-mandatory bound skips branches which cannot match the
        primary's entitlement count.  Search stops only after the policy output
        limit is met, or all qualifying branches have been considered.
        """

        primary_canonical = canonical_json(primary.canonical())
        primary_demand_ids = {item.demand_id for item in primary.allocations}
        mandatory_target = sum(
            demand.minimum_entitlement and demand.demand_id in primary_demand_ids
            for demand in demands
        )
        remaining_mandatory = [0] * (len(demands) + 1)
        for position in range(len(demands) - 1, -1, -1):
            remaining_mandatory[position] = remaining_mandatory[position + 1] + int(
                demands[position].minimum_entitlement
            )

        alternatives = {}

        def search(position, choices, groups, mandatory_allocated):
            if len(alternatives) >= request.policy.alternative_limit:
                return
            if mandatory_allocated + remaining_mandatory[position] < mandatory_target:
                return
            if position == len(demands):
                if mandatory_allocated != mandatory_target:
                    return
                plan = cls._render(request, choices)
                canonical = canonical_json(plan.canonical())
                if canonical != primary_canonical:
                    alternatives.setdefault(canonical, plan)
                return

            demand = demands[position]
            for choice in candidates[demand.demand_id]:
                if not cls._choice_fits(request, demand, choice, groups):
                    continue
                slot_key = (
                    choice.slot.resource_id,
                    choice.slot.route_code,
                    choice.slot.available_on,
                )
                next_groups = dict(groups)
                next_groups[slot_key] = next_groups.get(slot_key, ()) + (demand,)
                search(
                    position + 1,
                    choices + (choice,),
                    next_groups,
                    mandatory_allocated + int(demand.minimum_entitlement),
                )
            # An unmet demand is explicit, never a relaxed entitlement or dropped row.
            search(position + 1, choices, groups, mandatory_allocated)

        search(0, (), {}, 0)
        return tuple(sorted(alternatives.values(), key=lambda plan: cls._rank(plan, demands)))

    @staticmethod
    def _choice_fits(request, demand, choice, groups):
        slot_key = (choice.slot.resource_id, choice.slot.route_code, choice.slot.available_on)
        current = groups.get(slot_key, ())
        if len(current) >= min(
            choice.slot.seats,
            choice.slot.room_capacity,
            request.policy.maximum_group_size,
        ):
            return False
        if (
            sum(item.effort_hours for item in current) + demand.effort_hours
            > choice.slot.adviser_hours
        ):
            return False
        return all(
            request.policy.barriers_compatible(demand.barrier_key, item.barrier_key)
            for item in current
        )

    @staticmethod
    def _rank(plan, demands):
        allocated = {item.demand_id for item in plan.allocations}
        mandatory_met = sum(
            demand.minimum_entitlement and demand.demand_id in allocated for demand in demands
        )
        wait = sum(item.waiting_days for item in plan.allocations)
        lexical = tuple(
            (item.demand_id, item.resource_id, item.route_code, item.scheduled_on.isoformat())
            for item in plan.allocations
        )
        return (-mandatory_met, -len(plan.allocations), wait, lexical)

    @staticmethod
    def _render(request, choices):
        by_id = {demand.demand_id: demand for demand in request.demands}
        group_members = defaultdict(list)
        for choice in choices:
            key = (choice.slot.resource_id, choice.slot.route_code, choice.slot.available_on)
            group_members[key].append(by_id[choice.demand_id])
        allocations = []
        consumption = []
        for key in sorted(group_members):
            members = sorted(group_members[key], key=lambda item: item.demand_id)
            resource_id, route_code, scheduled_on = key
            slot = next(
                item
                for item in request.capacity_slots
                if (item.resource_id, item.route_code, item.available_on) == key
            )
            group_key = f"{resource_id}:{route_code}:{scheduled_on.isoformat()}"
            consumption.append(
                ResourceConsumption(
                    resource_id=resource_id,
                    route_code=route_code,
                    scheduled_on=scheduled_on,
                    seats_consumed=len(members),
                    adviser_hours_consumed=sum(item.effort_hours for item in members),
                    room_capacity_consumed=len(members),
                    external_provider=slot.external_provider,
                )
            )
            choices_for_key = {
                choice.demand_id: choice for choice in choices if choice.slot == slot
            }
            for demand in members:
                choice = choices_for_key[demand.demand_id]
                allocations.append(
                    PlannedAllocation(
                        demand_id=demand.demand_id,
                        case_id=demand.case_id,
                        need_code=demand.need_code,
                        route_code=choice.route_code,
                        resource_id=resource_id,
                        scheduled_on=scheduled_on,
                        group_key=group_key,
                        waiting_days=(scheduled_on - demand.requested_on).days,
                        human_review_required=demand.requires_human_review,
                    )
                )
        allocated_ids = {item.demand_id for item in allocations}
        unmet = tuple(
            UnmetDemand(
                demand_id=demand.demand_id,
                case_id=demand.case_id,
                reason_code=DeterministicPlanningService._unmet_reason(
                    demand, request, group_members
                ),
                minimum_entitlement=demand.minimum_entitlement,
                human_review_required=demand.requires_human_review,
            )
            for demand in sorted(request.demands, key=lambda item: item.demand_id)
            if demand.demand_id not in allocated_ids
        )
        bindings = tuple(sorted({item.reason_code for item in unmet}))
        return FeasibilityPlan(
            allocations=tuple(sorted(allocations, key=lambda item: item.demand_id)),
            unmet_demand=unmet,
            resource_consumption=tuple(consumption),
            binding_constraints=bindings,
        )

    @staticmethod
    def _unmet_reason(demand, request, group_members):
        approved = set(request.policy.approved_intervention_types)
        if not set(demand.route_options) & approved:
            return "unapproved_intervention_type"
        route_slots = [
            slot for slot in request.capacity_slots if slot.route_code in demand.route_options
        ]
        if not route_slots or all(
            min(slot.seats, slot.adviser_hours, slot.room_capacity) == 0 for slot in route_slots
        ):
            return "zero_capacity"
        timely = [
            slot
            for slot in route_slots
            if demand.requested_on <= slot.available_on <= demand.deadline
        ]
        if not timely:
            return "deadline_elapsed"
        for slot in timely:
            members = group_members.get((slot.resource_id, slot.route_code, slot.available_on), [])
            if members and not all(
                request.policy.barriers_compatible(demand.barrier_key, item.barrier_key)
                for item in members
            ):
                return "barrier_incompatible"
            if len(members) >= request.policy.maximum_group_size:
                return "group_limit"
            if len(members) >= min(slot.seats, slot.room_capacity):
                return "capacity_exhausted"
            if (
                sum(item.effort_hours for item in members) + demand.effort_hours
                > slot.adviser_hours
            ):
                return "adviser_hours"
        return "capacity_exhausted"


class PlannerRunService:
    """Persist append-only, reproducible evidence after pure feasibility succeeds."""

    @transaction.atomic
    def record(self, request: PlanningRequest, result: PlanningResult) -> PlannerRun:
        expected = DeterministicPlanningService.plan(request)
        if canonical_json(result.canonical()) != canonical_json(expected.canonical()):
            raise DomainInvariantError(
                "Planner evidence must contain the exact deterministic result"
            )
        return PlannerRun.objects.create(
            input_digest=canonical_digest(request.canonical()),
            policy_version=result.identity.policy_version,
            algorithm_version=result.identity.algorithm_version,
            seed_metadata={"seed": result.identity.seed},
            source_ids=sorted(
                {
                    source_id
                    for demand in request.demands
                    for source_id in (demand.source_record_ids or (demand.demand_id,))
                }
            ),
            canonical_input=json.loads(canonical_json(request.canonical())),
            canonical_result=json.loads(canonical_json(result.canonical())),
            result_digest=result.digest,
        )


class AllocationService:
    @transaction.atomic
    def propose(
        self,
        *,
        case_id,
        need,
        route_code,
        planner_run_id,
        planner_algorithm_version,
        planner_policy_version,
        hypothesis=None,
    ):
        if not Case.objects.filter(pk=case_id).exists():
            raise DomainInvariantError("An allocation must belong to an existing case")
        if case_has_safety_exit(case_id):
            raise DomainInvariantError("A safety-exited case cannot receive an allocation")
        need = Need.objects.select_for_update().get(pk=need.pk)
        if route_code not in need.permitted_routes:
            raise DomainInvariantError("Allocation route is not permitted by the need taxonomy")
        if hypothesis:
            hypothesis = NeedHypothesis.objects.select_related("gateway_output__attempt").get(
                pk=hypothesis.pk
            )
            if hypothesis.case_id != case_id:
                raise DomainInvariantError("Allocation hypothesis must belong to the stated case")
            self._require_validated_gateway_hypothesis(hypothesis, case_id)
        self._require_planner_run(
            planner_run_id,
            case_id,
            need.taxonomy_code,
            route_code,
            planner_algorithm_version,
            planner_policy_version,
        )
        return InterventionAllocation.objects.create(
            case_id=case_id,
            need=need,
            hypothesis=hypothesis,
            route_code=route_code,
            planner_run_id=planner_run_id,
            planner_algorithm_version=planner_algorithm_version,
            planner_policy_version=planner_policy_version,
        )

    @staticmethod
    def _require_planner_run(
        planner_run_id,
        case_id,
        need_code,
        route_code,
        algorithm_version,
        policy_version,
    ):
        try:
            run = PlannerRun.objects.get(pk=planner_run_id)
        except PlannerRun.DoesNotExist as error:
            raise DomainInvariantError(
                "Allocation proposals require persisted planner evidence"
            ) from error
        if (
            run.algorithm_version != algorithm_version
            or run.policy_version != policy_version
            or run.input_digest != canonical_digest(run.canonical_input)
            or run.result_digest != canonical_digest(run.canonical_result)
        ):
            raise DomainInvariantError("Allocation planner evidence digest or version is invalid")
        allocations = run.canonical_result.get("primary", {}).get("allocations", [])
        if not any(
            item.get("case_id") == case_id
            and item.get("need_code") == need_code
            and item.get("route_code") == route_code
            for item in allocations
        ):
            raise DomainInvariantError("Allocation must match a feasible planner result")

    @staticmethod
    def _require_validated_gateway_hypothesis(hypothesis, case_id):
        """Reject legacy or manually-created hypotheses at the planning boundary.

        ``NeedHypothesis`` is append-only but can still be inserted through the
        ORM.  Planning therefore independently verifies the immutable gateway
        output instead of trusting the relation merely because it is present.
        """
        output = hypothesis.gateway_output
        if output is None:
            raise DomainInvariantError("Allocation hypotheses require validated gateway evidence")
        attempt = output.attempt
        expected_payload = {
            "tags": hypothesis.tags,
            "explanation": hypothesis.explanation,
            "unknowns": hypothesis.unknowns,
            "confidence": "high",
        }
        input_ids = list(hypothesis.inputs.values_list("capture_id", flat=True))
        source_ids = attempt.source_record_ids
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
            raise DomainInvariantError("Allocation gateway request evidence is invalid") from error
        source_captures = {
            capture.id: capture for capture in NeedCapture.objects.filter(pk__in=source_ids)
        }
        expected_source_records = [
            {
                "record_id": source_id,
                "record_type": "need_capture",
                "source_version": source_captures[source_id].source_version,
            }
            for source_id in source_ids
            if source_id in source_captures
        ]
        expected_metadata = {"case_id": case_id, "capture_ids": source_ids}
        provenance_matches = (
            hypothesis.output_schema_version == attempt.output_schema_version
            and hypothesis.prompt_version == attempt.prompt_version
            and hypothesis.model_version == attempt.model_version
            and hypothesis.gateway_policy_version == attempt.policy_version
            and hypothesis.adapter_version == attempt.adapter_version
        )
        if (
            hypothesis.status != "provisional"
            or hypothesis.confidence_state != "high"
            or attempt.task_kind not in {"intake_interpretation", "need_hypothesis"}
            or attempt.disposition != "provisional_output"
            or output.authority != "provisional_no_decision_authority"
            or output.confidence != "high"
            or output.validated_payload != expected_payload
            or output.output_digest != ai_canonical_digest(expected_payload)
            or output.validation_errors
            or hypothesis.unknowns
            or payload_errors(attempt.task_kind, output.validated_payload)
            or not input_ids
            or len(input_ids) != len(set(input_ids))
            or len(source_ids) != len(set(source_ids))
            or source_ids != [source.record_id for source in persisted_request.source_records]
            or set(input_ids) != set(source_ids)
            or len(source_captures) != len(source_ids)
            or any(
                capture.case_id != case_id or not capture.field_allowlist_passed
                for capture in source_captures.values()
            )
            or attempt.source_records != expected_source_records
            or attempt.input_metadata != expected_metadata
            or attempt.input_digest != canonical_request_digest(persisted_request)
            or not provenance_matches
        ):
            raise DomainInvariantError(
                "Allocation hypotheses must exactly match high-confidence "
                "validated gateway evidence"
            )

    @transaction.atomic
    def activate_for_approval(self, allocation, decision):
        from career_codesk.modules.decisions.models import SupportDecision

        allocation = InterventionAllocation.objects.select_for_update().get(pk=allocation.pk)
        decision = SupportDecision.objects.select_for_update().get(pk=decision.pk)
        if (
            decision.action != "approve"
            or decision.allocation_id != allocation.id
            or decision.case_id != allocation.case_id
        ):
            raise DomainInvariantError(
                "Only the matching approved decision can activate an allocation"
            )
        if case_has_safety_exit(allocation.case_id):
            raise DomainInvariantError("A safety-exited case cannot activate an allocation")
        if allocation.state != "proposed":
            raise DomainInvariantError("Only a proposed allocation can become active")
        self._set_state(allocation, "active")
        return allocation

    @transaction.atomic
    def retire_for_review(self, allocation, decision):
        """Make a later adviser amendment or rejection operationally effective.

        The immutable decision remains the audit record; the proposal projection is
        retired so an earlier approval cannot continue to authorise delivery.
        """
        from career_codesk.modules.decisions.models import SupportDecision

        allocation = InterventionAllocation.objects.select_for_update().get(pk=allocation.pk)
        decision = SupportDecision.objects.select_for_update().get(pk=decision.pk)
        if (
            decision.action not in {"amend", "reject"}
            or decision.allocation_id != allocation.id
            or decision.case_id != allocation.case_id
        ):
            raise DomainInvariantError(
                "Only a matching amendment or rejection can retire an allocation"
            )
        if allocation.state != "inactive":
            self._set_state(allocation, "inactive")
        return allocation

    @staticmethod
    def _set_state(allocation, state):
        with _authorize_projection_state_change():
            allocation.state = state
            allocation.save(update_fields=("state",))
