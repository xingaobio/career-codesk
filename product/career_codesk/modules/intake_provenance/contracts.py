"""Published intake/provenance interface; processing is deferred to a later task."""

from dataclasses import dataclass

SOURCE_LABEL = "Synthetic mock source — no MIS connection."


@dataclass(frozen=True)
class IntakeConvention:
    source_label: str = SOURCE_LABEL
    synthetic_only: bool = True


class ProvenanceIntake:
    def convention(self) -> IntakeConvention:
        return IntakeConvention()
