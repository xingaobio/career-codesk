"""Published casework interface; no case records are created by the foundation."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CaseworkConvention:
    """The boundary a future casework module must preserve."""

    records_persisted: bool = False
    workflow_status: str = "deferred"


class CaseworkService(Protocol):
    """Describes whether casework records and workflows are available."""

    def convention(self) -> CaseworkConvention:
        """Return the current casework boundary without creating a case record."""


class DeferredCaseworkService:
    """Foundation implementation that explicitly creates no casework data."""

    def convention(self) -> CaseworkConvention:
        return CaseworkConvention()
