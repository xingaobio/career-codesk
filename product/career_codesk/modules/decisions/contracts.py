"""Published human-decision interface."""

from typing import Protocol

from career_codesk.identity import SimulatedActor


class DecisionGate(Protocol):
    """Guards consequential actions until an adviser has approved them."""

    def may_decide(self, actor: SimulatedActor) -> bool:
        """Return whether this simulated actor is permitted to make a decision."""


class AdviserDecisionGate:
    def may_decide(self, actor: SimulatedActor) -> bool:
        return actor.role == "adviser"
