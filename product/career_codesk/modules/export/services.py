"""Persist canonical local mock exports and their append-only attempt history."""

import hashlib
import json

from django.db import transaction
from django.db.models import Max

from career_codesk.domain import DomainInvariantError
from career_codesk.modules.decisions.models import SupportDecision
from career_codesk.modules.intake_provenance.services import case_has_safety_exit
from career_codesk.modules.planning.models import InterventionAllocation, WeeklyPlanEntry

from .models import StructuredExport, WritebackAttempt


def canonical_payload_digest(payload):
    """Return the stable digest used by both export and attempt records."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class WritebackService:
    payload_version = "weekly-plan-export-v1"
    destination = "local-mock-outbox"

    @transaction.atomic
    def create_or_replay_export(self, *, weekly_entry, decision, allocation):
        """Create exactly one immutable export object; this never sends anything."""
        weekly_entry = WeeklyPlanEntry.objects.select_for_update().get(pk=weekly_entry.pk)
        allocation, decision = self._approved_pair(allocation, decision)
        if (
            weekly_entry.decision_id != decision.id
            or weekly_entry.allocation_id != allocation.id
            or weekly_entry.case_id != allocation.case_id
        ):
            raise DomainInvariantError(
                "Structured export must use its exact weekly execution package"
            )
        existing = StructuredExport.objects.filter(
            decision=decision, allocation=allocation, payload_version=self.payload_version
        ).first()
        if existing:
            return existing
        payload = {
            "allocation_id": allocation.id,
            "case_id": allocation.case_id,
            "deadline": weekly_entry.deadline.isoformat(),
            "decision_id": decision.id,
            "destination": self.destination,
            "effort_hours": weekly_entry.effort_hours,
            "need_id": weekly_entry.need_id,
            "resource_owner_id": weekly_entry.resource_owner_id,
            "route_code": weekly_entry.route_code,
            "scheduled_on": weekly_entry.scheduled_on.isoformat(),
            "weekly_entry_id": weekly_entry.id,
        }
        return StructuredExport.objects.create(
            weekly_entry=weekly_entry,
            allocation=allocation,
            decision=decision,
            destination=self.destination,
            payload_version=self.payload_version,
            canonical_payload=payload,
            payload_digest=canonical_payload_digest(payload),
            idempotency_key=f"{decision.id}:{allocation.id}:{self.payload_version}",
        )

    @transaction.atomic
    def record_attempt(
        self,
        *,
        allocation,
        decision,
        payload=None,
        payload_version=None,
        result="not_sent",
        failure_reason="",
        structured_export=None,
    ):
        """Record a local attempt or replay a terminal local success.

        No connector is called here.  ``succeeded`` means only that a local mock
        outbox record was persisted; failed and not-sent records remain retryable.
        """
        if result not in {"pending", "succeeded", "failed", "not_sent"}:
            raise DomainInvariantError("Writeback result is invalid")
        allocation, decision = self._approved_pair(allocation, decision)
        export = (
            StructuredExport.objects.select_for_update()
            .filter(decision=decision, allocation=allocation)
            .first()
        )
        if export is None:
            raise DomainInvariantError("Writeback requires a persisted structured local export")
        if structured_export is not None and structured_export.pk != export.pk:
            raise DomainInvariantError("Attempt export must match its approved allocation")
        if payload is not None and payload != export.canonical_payload:
            raise DomainInvariantError(
                "Writeback payload must match the canonical structured export"
            )
        if payload_version is not None and payload_version != export.payload_version:
            raise DomainInvariantError("Writeback payload version must match the structured export")
        structured_export = export
        payload = export.canonical_payload
        payload_version = export.payload_version
        terminal = (
            WritebackAttempt.objects.filter(structured_export=export, result="succeeded")
            .order_by("attempt_number")
            .first()
        )
        if terminal is not None:
            return terminal
        previous = WritebackAttempt.objects.filter(
            allocation=allocation, payload_version=payload_version
        ).aggregate(maximum=Max("attempt_number"))["maximum"]
        return WritebackAttempt.objects.create(
            allocation=allocation,
            decision=decision,
            structured_export=structured_export,
            idempotency_key=export.idempotency_key,
            payload_version=payload_version,
            payload_digest=export.payload_digest,
            attempt_number=(previous or 0) + 1,
            result=result,
            failure_reason=failure_reason,
        )

    @transaction.atomic
    def reconcile_local_state(self, *, structured_export):
        """Return the linked canonical local state without any network reconciliation.

        Nullable export links are retained only for pre-migration audit rows.  They
        do not alter a structured export's state because they cannot establish its
        canonical payload or idempotency identity.
        """
        structured_export = StructuredExport.objects.select_for_update().get(
            pk=structured_export.pk
        )
        latest = structured_export.attempts.order_by("attempt_number").last()
        return latest.result if latest else "not_sent"

    @staticmethod
    def _approved_pair(allocation, decision):
        allocation = InterventionAllocation.objects.select_for_update().get(pk=allocation.pk)
        decision = SupportDecision.objects.select_for_update().get(pk=decision.pk)
        if (
            decision.action != "approve"
            or decision.allocation_id != allocation.id
            or decision.case_id != allocation.case_id
        ):
            raise DomainInvariantError("Mock writeback requires the matching approved decision")
        if allocation.state != "active" or case_has_safety_exit(allocation.case_id):
            raise DomainInvariantError(
                "Only an active ordinary-workflow allocation may be exported"
            )
        return allocation, decision
