"""Published planning interface; no allocation algorithm is implemented here."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PlannerIdentity:
    """Stable metadata that makes a later deterministic run reproducible."""

    algorithm_version: str
    policy_version: str
    seed: int


class Planner(Protocol):
    """Identifies the deterministic planner; feasibility work is deferred."""

    def identity(self) -> PlannerIdentity:
        """Return the planner metadata without proposing or reserving an allocation."""


class DeterministicPlanner:
    algorithm_version = "planner-foundation-v1"
    policy_version = "planning-policy-foundation-v1"
    seed = 20260101

    def identity(self) -> PlannerIdentity:
        return PlannerIdentity(
            algorithm_version=self.algorithm_version,
            policy_version=self.policy_version,
            seed=self.seed,
        )
