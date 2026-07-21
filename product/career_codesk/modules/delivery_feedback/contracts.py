"""Published delivery/feedback interface for append-only event persistence."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DeliveryFeedbackConvention:
    """The boundary a future delivery and feedback module must preserve."""

    feedback_persisted: bool = False
    delivery_status: str = "deferred"


class FeedbackRecorder(Protocol):
    """Describes feedback availability without accepting an event at foundation stage."""

    def convention(self) -> DeliveryFeedbackConvention:
        """Return the deferred delivery/feedback boundary."""


class DeferredFeedbackRecorder:
    """Compatibility name for the original foundation placeholder."""

    def convention(self) -> DeliveryFeedbackConvention:
        return DeliveryFeedbackConvention()
