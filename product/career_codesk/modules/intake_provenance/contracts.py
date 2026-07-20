"""Published intake/provenance interface for attested local synthetic CSV files."""

from dataclasses import dataclass

SOURCE_LABEL = "Synthetic mock source — no MIS connection."


@dataclass(frozen=True)
class IntakeConvention:
    source_label: str = SOURCE_LABEL
    synthetic_only: bool = True


class ProvenanceIntake:
    def convention(self) -> IntakeConvention:
        return IntakeConvention()

    def import_csv(self, csv_bytes: bytes, manifest: dict):
        """Validate and import a local attested CSV; implemented by the composition root."""
        from .services import SyntheticCsvIntakeService

        return SyntheticCsvIntakeService().import_csv(csv_bytes, manifest)
