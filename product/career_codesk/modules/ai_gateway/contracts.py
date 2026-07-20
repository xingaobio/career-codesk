"""Published deterministic fake-AI seam. It cannot make operational decisions."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class HypothesisPreview:
    input_ids: tuple[str, ...]
    adapter_version: str
    policy_version: str
    status: str = "provisional"


class AiGateway(Protocol):
    """Creates a provisional preview from source-qualified input identifiers."""

    def preview(self, *input_ids: str) -> HypothesisPreview:
        """Return an AI hypothesis that cannot be treated as a decision or fact."""


class DeterministicFakeAiGateway:
    """Local adapter with no model, credentials, network access, or operational authority."""

    version = "fake-ai-foundation-v1"
    policy_version = "ai-policy-foundation-v1"

    def preview(self, *input_ids: str) -> HypothesisPreview:
        return HypothesisPreview(
            input_ids=tuple(input_ids),
            adapter_version=self.version,
            policy_version=self.policy_version,
        )
