"""Create auditable local mock export attempts only after human approval."""

import hashlib
import json

from django.db import transaction
from django.db.models import Max

from career_codesk.domain import DomainInvariantError
from career_codesk.modules.decisions.models import SupportDecision
from career_codesk.modules.intake_provenance.services import case_has_safety_exit
from career_codesk.modules.planning.models import InterventionAllocation

from .models import WritebackAttempt


class WritebackService:
    @transaction.atomic
    def record_attempt(
        self,
        *,
        allocation,
        decision,
        payload,
        payload_version="1.0",
        result="not_sent",
        failure_reason="",
    ):
        if result not in {"pending", "succeeded", "failed", "not_sent"}:
            raise DomainInvariantError("Writeback result is invalid")
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
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        previous = WritebackAttempt.objects.filter(
            allocation=allocation, payload_version=payload_version
        ).aggregate(maximum=Max("attempt_number"))["maximum"]
        return WritebackAttempt.objects.create(
            allocation=allocation,
            decision=decision,
            idempotency_key=f"{decision.id}:{allocation.id}:{payload_version}",
            payload_version=payload_version,
            payload_digest=digest,
            attempt_number=(previous or 0) + 1,
            result=result,
            failure_reason=failure_reason,
        )
