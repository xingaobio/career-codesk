"""The sole composition root for published module interfaces."""

from dataclasses import dataclass

from career_codesk.modules.ai_gateway.contracts import AiGateway, DeterministicFakeAdapter
from career_codesk.modules.ai_gateway.services import AiGatewayService, HypothesisService
from career_codesk.modules.audit.contracts import AuditProjection, DeferredAuditProjection
from career_codesk.modules.casework.contracts import CaseworkService
from career_codesk.modules.casework.services import CaseWorkflowService
from career_codesk.modules.decisions.contracts import AdviserDecisionGate, DecisionGate
from career_codesk.modules.decisions.services import SupportDecisionService
from career_codesk.modules.delivery_feedback.contracts import FeedbackRecorder
from career_codesk.modules.delivery_feedback.services import DeliveryFeedbackService
from career_codesk.modules.export.contracts import ExportGateway, LocalMockOutbox
from career_codesk.modules.export.services import WritebackService
from career_codesk.modules.intake_provenance.contracts import ProvenanceIntake
from career_codesk.modules.intake_provenance.services import CaptureService
from career_codesk.modules.planning.contracts import DeterministicPlanner, Planner
from career_codesk.modules.planning.services import AllocationService


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
    capture_service: CaptureService
    hypothesis_service: HypothesisService
    casework_service: CaseWorkflowService
    allocation_service: AllocationService
    decision_service: SupportDecisionService
    delivery_service: DeliveryFeedbackService
    writeback_service: WritebackService

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
    """Wire safe, local contracts and their transactional domain services."""
    return Foundation(
        intake=ProvenanceIntake(),
        casework=CaseWorkflowService(),
        ai_gateway=AiGatewayService(DeterministicFakeAdapter()),
        planning=DeterministicPlanner(),
        decisions=AdviserDecisionGate(),
        delivery_feedback=DeliveryFeedbackService(),
        export=LocalMockOutbox(),
        audit=DeferredAuditProjection(),
        capture_service=CaptureService(),
        hypothesis_service=HypothesisService(),
        casework_service=CaseWorkflowService(),
        allocation_service=AllocationService(),
        decision_service=SupportDecisionService(),
        delivery_service=DeliveryFeedbackService(),
        writeback_service=WritebackService(),
    )
