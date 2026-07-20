"""Table-driven acceptance evidence for the deterministic capacity planner."""

from datetime import date

from django.test import SimpleTestCase

from career_codesk.modules.planning.contracts import (
    CapacitySlot,
    Demand,
    PlanningPolicy,
    PlanningRequest,
)
from career_codesk.modules.planning.services import DeterministicPlanningService

TODAY = date(2026, 7, 20)


def demand(
    demand_id,
    *,
    required=True,
    route="guide",
    barrier="route",
    deadline=date(2026, 7, 21),
    provisional=False,
    alternatives=(),
):
    return Demand(
        demand_id=demand_id,
        case_id="case-" + demand_id,
        need_code="synthetic-route-comparison",
        route_code=route,
        barrier_key=barrier,
        requested_on=TODAY,
        deadline=deadline,
        minimum_entitlement=required,
        evidence_status="provisional" if provisional else "approved",
        alternative_route_codes=alternatives,
    )


def slot(resource_id, *, route="guide", on=TODAY, seats=2, hours=2, room=2, external=False):
    return CapacitySlot(resource_id, route, on, seats, hours, room, external)


class CapacityPlannerTests(SimpleTestCase):
    def setUp(self):
        self.planner = DeterministicPlanningService()
        self.policy = PlanningPolicy("demo-policy-v1", ("guide", "workshop"), 2)

    def plan(self, demands, slots, policy=None):
        request = PlanningRequest(policy or self.policy, tuple(demands), tuple(slots))
        return self.planner.plan(request)

    def test_named_capacity_scenarios(self):
        scenarios = (
            {
                "name": "zero capacity",
                "demands": (demand("zero"),),
                "slots": (slot("room-0", seats=0, hours=0, room=0),),
                "allocated": (),
                "reasons": ("zero_capacity",),
            },
            {
                "name": "over capacity preserves minimum entitlement",
                "demands": (demand("mandatory"), demand("optional", required=False)),
                "slots": (slot("adviser-1", seats=1, hours=1, room=1),),
                "allocated": ("mandatory",),
                "reasons": ("capacity_exhausted",),
            },
            {
                "name": "deadline tie uses stable demand identifier",
                "demands": (demand("b"), demand("a")),
                "slots": (slot("adviser-1", seats=1, hours=1, room=1),),
                "allocated": ("a",),
                "reasons": ("capacity_exhausted",),
            },
            {
                "name": "maximum group limit",
                "demands": (demand("one"), demand("two"), demand("three")),
                "slots": (slot("workshop-1"),),
                "allocated": ("one", "three"),
                "reasons": ("group_limit",),
            },
            {
                "name": "approved external capacity",
                "demands": (demand("external"),),
                "slots": (slot("provider-demo", external=True),),
                "allocated": ("external",),
                "reasons": (),
            },
            {
                "name": "impossible unapproved intervention",
                "demands": (demand("impossible", route="unapproved"),),
                "slots": (slot("adviser-1", route="unapproved"),),
                "allocated": (),
                "reasons": ("unapproved_intervention_type",),
            },
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]):
                result = self.plan(scenario["demands"], scenario["slots"])
                self.assertEqual(
                    tuple(item.demand_id for item in result.primary.allocations),
                    scenario["allocated"],
                )
                self.assertEqual(
                    tuple(item.reason_code for item in result.primary.unmet_demand),
                    scenario["reasons"],
                )
                self.assertEqual(result.primary.binding_constraints, scenario["reasons"])

    def test_permutations_are_byte_equivalent_and_provisional_review_is_visible(self):
        demands = (demand("second", provisional=True), demand("first"))
        slots = (slot("room-b"), slot("room-a"))
        first = self.plan(demands, slots)
        second = self.plan(tuple(reversed(demands)), tuple(reversed(slots)))
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.canonical(), second.canonical())
        provisional = next(item for item in first.primary.allocations if item.demand_id == "second")
        self.assertTrue(provisional.human_review_required)

    def test_nested_route_alternative_permutations_are_byte_equivalent(self):
        policy = PlanningPolicy("route-policy-v1", ("a", "b"), 1)
        slots = (
            slot("route-a", route="a", seats=1, hours=1, room=1),
            slot("route-b", route="b", seats=1, hours=1, room=1),
        )
        first = self.plan((demand("choice", route="base", alternatives=("b", "a")),), slots, policy)
        second = self.plan(
            (demand("choice", route="base", alternatives=("a", "b")),), slots, policy
        )
        self.assertEqual(first.canonical(), second.canonical())
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.primary.allocations[0].route_code, "a")

    def test_primary_ranking_preserves_restricted_minimum_entitlement(self):
        policy = PlanningPolicy("entitlement-policy-v1", ("a", "b"), 1)
        result = self.plan(
            (
                demand("flexible", route="a", alternatives=("b",)),
                demand("restricted", route="a"),
            ),
            (
                slot("route-a", route="a", seats=1, hours=1, room=1),
                slot("route-b", route="b", seats=1, hours=1, room=1),
            ),
            policy,
        )
        self.assertEqual(
            tuple((item.demand_id, item.route_code) for item in result.primary.allocations),
            (("flexible", "b"), ("restricted", "a")),
        )
        self.assertFalse(result.primary.unmet_demand)

    def test_primary_entitlement_optimization_is_not_limited_by_alternative_search(self):
        policy = PlanningPolicy("bounded-alternatives-policy-v1", ("a", "b", "optional"), 5)
        # The route-a branch has 4**5 terminal combinations (three optional
        # resources plus an unmet choice for each optional demand), so the
        # 512-plan alternative search never reaches flexible route b.
        optional_demands = tuple(
            demand(f"optional-{number}", required=False, route="optional") for number in range(5)
        )
        result = self.plan(
            (
                demand("flexible", route="a", alternatives=("b",)),
                demand("restricted", route="a"),
                *optional_demands,
            ),
            (
                slot("route-a", route="a", seats=1, hours=1, room=1),
                slot("route-b", route="b", seats=1, hours=1, room=1),
                slot("optional-1", route="optional", seats=5, hours=5, room=5),
                slot("optional-2", route="optional", seats=5, hours=5, room=5),
                slot("optional-3", route="optional", seats=5, hours=5, room=5),
            ),
            policy,
        )
        allocations = {item.demand_id: item.route_code for item in result.primary.allocations}
        self.assertEqual(allocations["flexible"], "b")
        self.assertEqual(allocations["restricted"], "a")
        self.assertFalse(result.primary.unmet_demand)
        self.assertTrue(result.alternatives)
        for alternative in result.alternatives:
            alternative_ids = {item.demand_id for item in alternative.allocations}
            self.assertIn("flexible", alternative_ids)
            self.assertIn("restricted", alternative_ids)
            self.assertNotEqual(alternative.canonical(), result.primary.canonical())

    def test_barriers_deadlines_and_adviser_hours_are_hard_constraints(self):
        incompatible = self.plan(
            (demand("route", barrier="route"), demand("finance", barrier="finance")),
            (slot("adviser-1"),),
        )
        self.assertEqual(len(incompatible.primary.allocations), 1)
        self.assertEqual(incompatible.primary.unmet_demand[0].reason_code, "barrier_incompatible")

        expired = self.plan(
            (demand("late", deadline=TODAY),),
            (slot("adviser-1", on=date(2026, 7, 21)),),
        )
        self.assertEqual(expired.primary.unmet_demand[0].reason_code, "deadline_elapsed")

        hours = self.plan(
            (demand("long"), demand("other")),
            (slot("adviser-1", seats=2, hours=1, room=2),),
        )
        self.assertEqual(hours.primary.unmet_demand[0].reason_code, "adviser_hours")

    def test_consumption_waiting_and_distinct_feasible_alternative_are_exposed(self):
        result = self.plan(
            (demand("waiting"),),
            (
                slot("room-b", on=date(2026, 7, 21), external=True),
                slot("room-a", on=date(2026, 7, 21)),
            ),
        )
        allocation = result.primary.allocations[0]
        self.assertEqual(allocation.waiting_days, 1)
        self.assertEqual(result.primary.resource_consumption[0].seats_consumed, 1)
        self.assertTrue(result.alternatives)
        self.assertNotEqual(
            result.primary.allocations[0].resource_id,
            result.alternatives[0].allocations[0].resource_id,
        )
