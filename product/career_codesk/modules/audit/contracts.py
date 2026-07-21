"""Published audit interface; no event store is introduced by the foundation."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AuditConvention:
    """The boundary a future audit projection must preserve."""

    events_persisted: bool = False
    evaluation_status: str = "local_evaluation_pack"


class AuditProjection(Protocol):
    """Describes audit availability without introducing an event store."""

    def convention(self) -> AuditConvention:
        """Return the deferred audit and evaluation boundary."""


class LocalEvaluationPackProjection:
    """Expose local evaluation availability without creating an event store."""

    def convention(self) -> AuditConvention:
        return AuditConvention()
