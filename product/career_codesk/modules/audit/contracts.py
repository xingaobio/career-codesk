"""Published audit interface; no event store is introduced by the foundation."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AuditConvention:
    """The boundary a future audit projection must preserve."""

    events_persisted: bool = False
    evaluation_status: str = "deferred"


class AuditProjection(Protocol):
    """Describes audit availability without introducing an event store."""

    def convention(self) -> AuditConvention:
        """Return the deferred audit and evaluation boundary."""


class DeferredAuditProjection:
    """Foundation implementation that deliberately records no audit events."""

    def convention(self) -> AuditConvention:
        return AuditConvention()
