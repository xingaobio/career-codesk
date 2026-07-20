"""Deterministic simulated local identity; explicitly not an auth system."""

from dataclasses import dataclass


class UnsupportedRoleError(ValueError):
    """Raised when a role outside the two demo actors is requested."""


@dataclass(frozen=True)
class SimulatedActor:
    id: str
    role: str
    display_name: str


_ACTORS = {
    "manager": SimulatedActor("actor-manager-001", "manager", "Synthetic Manager"),
    "adviser": SimulatedActor("actor-adviser-001", "adviser", "Synthetic Adviser"),
}


def actor_for(role: str) -> SimulatedActor:
    try:
        return _ACTORS[role]
    except KeyError as error:
        raise UnsupportedRoleError(f"Unsupported simulated role: {role}") from error


def available_actors() -> tuple[SimulatedActor, SimulatedActor]:
    return (_ACTORS["manager"], _ACTORS["adviser"])
