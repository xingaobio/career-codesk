"""Pure, deterministic contracts for synthetic cohort-capacity planning.

These values deliberately contain every institutional choice the planner uses.  They
are demo-policy inputs, rather than hidden defaults or inferred learner facts.
"""

import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from typing import Protocol


def _canonical(value):
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    return value


def canonical_json(value) -> str:
    """Serialize a feasibility value without runtime IDs, clocks, or hash order."""
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"))


def canonical_digest(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PlannerIdentity:
    algorithm_version: str
    policy_version: str
    seed: int


@dataclass(frozen=True)
class Demand:
    """One source-qualified proposed need; it is never a reservation or decision."""

    demand_id: str
    case_id: str
    need_code: str
    route_code: str
    barrier_key: str
    requested_on: date
    deadline: date
    minimum_entitlement: bool
    evidence_status: str = "approved"
    human_review_required: bool = False
    alternative_route_codes: tuple[str, ...] = ()
    source_record_ids: tuple[str, ...] = ()
    effort_hours: int = 1

    def __post_init__(self):
        if not all(
            (self.demand_id, self.case_id, self.need_code, self.route_code, self.barrier_key)
        ):
            raise ValueError("Demand identifiers, route, and barrier key are required")
        if self.deadline < self.requested_on:
            raise ValueError("A demand deadline cannot precede its request date")
        if self.evidence_status not in {"approved", "provisional"}:
            raise ValueError("Demand evidence status must be approved or provisional")
        if self.effort_hours < 1:
            raise ValueError("Demand effort must be at least one adviser hour")
        if any(not source_id for source_id in self.source_record_ids):
            raise ValueError("Demand source record IDs cannot be empty")

    @property
    def requires_human_review(self) -> bool:
        return self.human_review_required or self.evidence_status == "provisional"

    @property
    def route_options(self) -> tuple[str, ...]:
        return (self.route_code,) + tuple(
            route for route in self.alternative_route_codes if route != self.route_code
        )


@dataclass(frozen=True)
class CapacitySlot:
    resource_id: str
    route_code: str
    available_on: date
    seats: int
    adviser_hours: int
    room_capacity: int
    external_provider: bool = False

    def __post_init__(self):
        if not self.resource_id or not self.route_code:
            raise ValueError("Capacity slots require a resource and route")
        if min(self.seats, self.adviser_hours, self.room_capacity) < 0:
            raise ValueError("Capacity values cannot be negative")


@dataclass(frozen=True)
class PlanningPolicy:
    version: str
    approved_intervention_types: tuple[str, ...]
    maximum_group_size: int
    compatible_barrier_pairs: tuple[tuple[str, str], ...] = ()
    alternative_limit: int = 8

    def __post_init__(self):
        if not self.version or not self.approved_intervention_types:
            raise ValueError("A policy version and approved intervention types are required")
        if self.maximum_group_size < 1 or self.alternative_limit < 1:
            raise ValueError("Group and alternative limits must be positive")

    def barriers_compatible(self, left: str, right: str) -> bool:
        return left == right or tuple(sorted((left, right))) in {
            tuple(sorted(pair)) for pair in self.compatible_barrier_pairs
        }


@dataclass(frozen=True)
class PlanningRequest:
    policy: PlanningPolicy
    demands: tuple[Demand, ...]
    capacity_slots: tuple[CapacitySlot, ...]

    def __post_init__(self):
        demand_ids = tuple(demand.demand_id for demand in self.demands)
        if len(demand_ids) != len(set(demand_ids)):
            raise ValueError("Demand IDs must be unique")
        resource_keys = tuple(
            (slot.resource_id, slot.route_code, slot.available_on.isoformat())
            for slot in self.capacity_slots
        )
        if len(resource_keys) != len(set(resource_keys)):
            raise ValueError("Capacity slots must have unique resource, route, and date keys")

    def canonical(self):
        return {
            "policy": {
                "version": self.policy.version,
                "approved_intervention_types": tuple(
                    sorted(self.policy.approved_intervention_types)
                ),
                "maximum_group_size": self.policy.maximum_group_size,
                "compatible_barrier_pairs": tuple(
                    sorted(tuple(sorted(pair)) for pair in self.policy.compatible_barrier_pairs)
                ),
                "alternative_limit": self.policy.alternative_limit,
            },
            "demands": tuple(
                {
                    "demand_id": demand.demand_id,
                    "case_id": demand.case_id,
                    "need_code": demand.need_code,
                    "route_code": demand.route_code,
                    "barrier_key": demand.barrier_key,
                    "requested_on": demand.requested_on,
                    "deadline": demand.deadline,
                    "minimum_entitlement": demand.minimum_entitlement,
                    "evidence_status": demand.evidence_status,
                    "human_review_required": demand.human_review_required,
                    "alternative_route_codes": tuple(sorted(demand.alternative_route_codes)),
                    "source_record_ids": tuple(sorted(demand.source_record_ids)),
                    "effort_hours": demand.effort_hours,
                }
                for demand in sorted(self.demands, key=lambda item: item.demand_id)
            ),
            "capacity_slots": tuple(
                {
                    "resource_id": slot.resource_id,
                    "route_code": slot.route_code,
                    "available_on": slot.available_on,
                    "seats": slot.seats,
                    "adviser_hours": slot.adviser_hours,
                    "room_capacity": slot.room_capacity,
                    "external_provider": slot.external_provider,
                }
                for slot in sorted(
                    self.capacity_slots,
                    key=lambda item: (item.resource_id, item.route_code, item.available_on),
                )
            ),
        }


@dataclass(frozen=True)
class PlannedAllocation:
    demand_id: str
    case_id: str
    need_code: str
    route_code: str
    resource_id: str
    scheduled_on: date
    group_key: str
    waiting_days: int
    human_review_required: bool

    def canonical(self):
        return self.__dict__


@dataclass(frozen=True)
class UnmetDemand:
    demand_id: str
    case_id: str
    reason_code: str
    minimum_entitlement: bool
    human_review_required: bool

    def canonical(self):
        return self.__dict__


@dataclass(frozen=True)
class ResourceConsumption:
    resource_id: str
    route_code: str
    scheduled_on: date
    seats_consumed: int
    adviser_hours_consumed: int
    room_capacity_consumed: int
    external_provider: bool

    def canonical(self):
        return self.__dict__


@dataclass(frozen=True)
class FeasibilityPlan:
    allocations: tuple[PlannedAllocation, ...]
    unmet_demand: tuple[UnmetDemand, ...]
    resource_consumption: tuple[ResourceConsumption, ...]
    binding_constraints: tuple[str, ...]

    def canonical(self):
        return {
            "allocations": tuple(item.canonical() for item in self.allocations),
            "unmet_demand": tuple(item.canonical() for item in self.unmet_demand),
            "resource_consumption": tuple(item.canonical() for item in self.resource_consumption),
            "binding_constraints": self.binding_constraints,
        }


@dataclass(frozen=True)
class PlanningResult:
    identity: PlannerIdentity
    primary: FeasibilityPlan
    alternatives: tuple[FeasibilityPlan, ...]

    def canonical(self):
        return {
            "algorithm_version": self.identity.algorithm_version,
            "policy_version": self.identity.policy_version,
            "seed": self.identity.seed,
            "primary": self.primary.canonical(),
            "alternatives": tuple(plan.canonical() for plan in self.alternatives),
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.canonical())


class Planner(Protocol):
    def identity(self) -> PlannerIdentity: ...

    def plan(self, request: PlanningRequest) -> PlanningResult: ...
