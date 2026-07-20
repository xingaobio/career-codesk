"""The sole composition root for published module interfaces."""

from dataclasses import dataclass

from career_codesk.modules.ai_gateway.contracts import AiGateway, DeterministicFakeAiGateway
from career_codesk.modules.audit.contracts import AuditProjection, DeferredAuditProjection
from career_codesk.modules.casework.contracts import CaseworkService, DeferredCaseworkService
from career_codesk.modules.decisions.contracts import AdviserDecisionGate, DecisionGate
from career_codesk.modules.delivery_feedback.contracts import (
    DeferredFeedbackRecorder,
    FeedbackRecorder,
)
from career_codesk.modules.export.contracts import ExportGateway, LocalMockOutbox
from career_codesk.modules.intake_provenance.contracts import ProvenanceIntake
from career_codesk.modules.planning.contracts import DeterministicPlanner, Planner


@dataclass(frozen=True)
class Foundation:
    intake: ProvenanceIntake
    casework: CaseworkService
    ai_gateway: AiGateway
    planning: Planner
    decisions: DecisionGate
    delivery_feedback: FeedbackRecorder
    export: ExportGateway
    audit: AuditProjection

    @property
    def module_names(self) -> tuple[str, ...]:
        return (
            "Intake and provenance",
            "Casework",
            "AI gateway (deterministic fake)",
            "Deterministic planning",
            "Human decisions",
            "Delivery and feedback",
            "Local mock export",
            "Audit and evaluation",
        )


def compose_foundation() -> Foundation:
    """Wire only safe, local contracts; business workflows are intentionally deferred."""
    return Foundation(
        intake=ProvenanceIntake(),
        casework=DeferredCaseworkService(),
        ai_gateway=DeterministicFakeAiGateway(),
        planning=DeterministicPlanner(),
        decisions=AdviserDecisionGate(),
        delivery_feedback=DeferredFeedbackRecorder(),
        export=LocalMockOutbox(),
        audit=DeferredAuditProjection(),
    )
