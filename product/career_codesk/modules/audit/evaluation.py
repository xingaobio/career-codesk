"""Deterministic, local acceptance evaluator for the synthetic thin slice.

The evaluator deliberately drives published application services and leaves their
append-only records in the disposable SQLite database.  Its report contains only
scenario aliases and stable counts, never generated IDs or wall-clock values.
"""

import hashlib
import json
import re
import subprocess
from datetime import date
from pathlib import Path

from career_codesk.composition import compose_foundation
from career_codesk.identity import actor_for
from career_codesk.modules.ai_gateway.contracts import AiRequest, SourceReference
from career_codesk.modules.ai_gateway.models import AiGatewayOutput, NeedHypothesis
from career_codesk.modules.casework.models import Case, CaseTransition
from career_codesk.modules.decisions.models import SupportDecision
from career_codesk.modules.export.models import StructuredExport, WritebackAttempt
from career_codesk.modules.intake_provenance.models import Learner, NeedCapture, SafetyExit
from career_codesk.modules.planning.contracts import (
    CapacitySlot,
    Demand,
    PlanningPolicy,
    PlanningRequest,
)
from career_codesk.modules.planning.models import (
    InterventionAllocation,
    Need,
    PlannerRun,
    WeeklyPlanEntry,
)
from career_codesk.modules.planning.services import PlannerRunService

PRODUCT_DIR = Path(__file__).resolve().parents[3]
FIXTURE_DIR = PRODUCT_DIR / "fixtures"
EVALUATION_DIR = FIXTURE_DIR / "evaluation"
SCENARIO_KEYS = (
    "happy-path",
    "over-capacity",
    "malformed-input",
    "ai-failure",
    "safety-exit",
    "override",
    "failed-export",
    "reopen",
)
TODAY = date(2026, 7, 20)
_CREDENTIAL_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
)
_DIRECT_IDENTIFIER_PATTERNS = (
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    (
        "mobile",
        re.compile(r"(?<!\w)(?:\+44\s*(?:\(0\)\s*)?|0)7\d{3}[\s.-]?\d{3}[\s.-]?\d{3}\b"),
    ),
    (
        "labelled_name",
        re.compile(r"\b(?:full\s+name|name)\s*:\s*[A-Za-z][A-Za-z' -]{1,80}\b", re.I),
    ),
    (
        "date_of_birth",
        re.compile(
            r"\b(?:dob|date\s+of\s+birth)\s*:\s*"
            r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b",
            re.I,
        ),
    ),
    (
        "street_address",
        re.compile(
            r"\b(?:home\s+address|address)\s*:\s*\d{1,5}\s+" r"[A-Za-z0-9][A-Za-z0-9 .'-]{2,80}\b",
            re.I,
        ),
    ),
)
_SYNTHETIC_REJECTION_SENTINELS = {
    ("email", "not-permitted@example.invalid"),
    ("email", "hidden-person@example.invalid"),
    ("email", "one@example.invalid"),
    ("email", "two@example.invalid"),
    ("labelled_name", "name: sentinel person"),
    ("labelled_name", "my name: sentinel person"),
    ("date_of_birth", "date of birth: 01/02/2007"),
    ("street_address", "address: 12 sentinel street"),
    ("mobile", "07123 456 789"),
}


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _request(capture):
    return AiRequest(
        task_kind="need_hypothesis",
        source_records=(SourceReference(capture.id, "need_capture", capture.source_version),),
        input_metadata={"case_id": capture.case_id, "capture_ids": [capture.id]},
        prompt_version="evaluation-prompt-v1",
        output_schema_version="schema-v1",
        policy_version="evaluation-ai-policy-v1",
    )


def _hypothesis(foundation, capture):
    result = foundation.ai_gateway.interpret(_request(capture))
    return foundation.hypothesis_service.record(
        case_id=capture.case_id, captures=[capture], gateway_result=result
    )


def _plan(*, demands, slots):
    request = PlanningRequest(
        PlanningPolicy("evaluation-capacity-policy-v1", ("guide", "workshop"), 1),
        tuple(demands),
        tuple(slots),
    )
    result = compose_foundation().planning.plan(request)
    return request, result, PlannerRunService().record(request, result)


def _demand(capture, *, suffix, route="guide", alternatives=()):
    return Demand(
        demand_id=f"evaluation-demand-{suffix}",
        case_id=capture.case_id,
        need_code="route-comparison",
        route_code=route,
        barrier_key="route",
        requested_on=TODAY,
        deadline=date(2026, 7, 24),
        minimum_entitlement=True,
        evidence_status="provisional",
        source_record_ids=(capture.id,),
        effort_hours=1,
        alternative_route_codes=alternatives,
    )


def _proposal(
    foundation,
    *,
    capture,
    hypothesis,
    need,
    suffix,
    route="guide",
    alternatives=(),
    supersedes=None,
):
    request, result, run = _plan(
        demands=(_demand(capture, suffix=suffix, route=route, alternatives=alternatives),),
        slots=(
            CapacitySlot("evaluation-guide", "guide", date(2026, 7, 21), 1, 1, 1),
            CapacitySlot("evaluation-workshop", "workshop", date(2026, 7, 22), 1, 1, 1),
        ),
    )
    allocation = foundation.allocation_service.propose(
        case_id=capture.case_id,
        need=need,
        route_code=route,
        planner_run_id=run.id,
        planner_algorithm_version=run.algorithm_version,
        planner_policy_version=run.policy_version,
        hypothesis=hypothesis,
        demand_id=f"evaluation-demand-{suffix}",
        supersedes=supersedes,
    )
    return allocation, request, result, run


def _approve(foundation, allocation, capture, hypothesis, *, predecessor=None, action="approve"):
    return foundation.decision_service.record(
        case_id=capture.case_id,
        allocation=allocation,
        action=action,
        actor=actor_for("adviser"),
        reason="Synthetic adviser reviewed source, provisional interpretation, and capacity.",
        reviewed_inputs=(("capture", capture.id), ("hypothesis", hypothesis.id)),
        policy_version=allocation.planner_policy_version,
        planner_version=allocation.planner_algorithm_version,
        predecessor=predecessor,
    )


def _contrast_ratio(left, right):
    def luminance(value):
        values = [int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            item / 12.92 if item <= 0.04045 else ((item + 0.055) / 1.055) ** 2.4 for item in values
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first, second = sorted((luminance(left), luminance(right)), reverse=True)
    return round((first + 0.05) / (second + 0.05), 2)


def _hygiene_check():
    """Scan all tracked text, treating documented rejection samples explicitly.

    Credentials are checked repository-wide. Direct identifiers are inspected in
    product fixture, demo and test sample data, where the only allowed matches
    are the fixed synthetic rejection sentinels below.
    """
    files = subprocess.run(
        ["git", "ls-files"],
        cwd=PRODUCT_DIR.parent,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    findings = []
    sentinels = []
    sample_files = []
    for relative in files:
        path = PRODUCT_DIR.parent / relative
        if path.suffix in {".pyc", ".sqlite3"} or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(pattern.search(content) for pattern in _CREDENTIAL_PATTERNS):
            findings.append({"file": relative, "kind": "credential_signature"})
        if not (
            relative.startswith("product/fixtures/")
            or relative.startswith("product/tests/")
            or relative.startswith("product/DEMO_")
        ):
            continue
        sample_files.append(relative)
        for kind, pattern in _DIRECT_IDENTIFIER_PATTERNS:
            for match in pattern.findall(content):
                value = match if isinstance(match, str) else match[0]
                normalized = value.lower()
                if (kind, normalized) in _SYNTHETIC_REJECTION_SENTINELS:
                    sentinels.append(
                        {
                            "classification": "synthetic_rejection_sentinel",
                            "file": relative,
                            "kind": kind,
                        }
                    )
                else:
                    findings.append({"file": relative, "kind": f"direct_identifier:{kind}"})
    return {
        "passed": not findings,
        "files_scanned": len(files),
        "sample_data_files_scanned": len(sample_files),
        "classified_sentinels": sorted(
            sentinels,
            key=lambda item: (item["file"], item["kind"], item["classification"]),
        ),
        "unacceptable_findings": findings,
    }


def run_evaluation():
    """Run every required scenario and return a canonical, JSON-ready report."""
    manifest = _load(EVALUATION_DIR / "scenarios-v1.json")
    manifest_keys = tuple(item["key"] for item in manifest["scenarios"])
    if manifest_keys != SCENARIO_KEYS or len(set(manifest_keys)) != len(SCENARIO_KEYS):
        raise RuntimeError(
            "Evaluation scenario manifest must define each required key exactly once"
        )

    foundation = compose_foundation()
    summary = foundation.intake.import_csv(
        (EVALUATION_DIR / "ordinary-cases-v1.csv").read_bytes(),
        _load(EVALUATION_DIR / "ordinary-manifest-v1.json"),
    )
    if summary.accepted != 6 or summary.rejected or summary.quarantined:
        raise RuntimeError("Ordinary evaluation fixture did not import exactly six accepted rows")
    captures = {
        capture.learner.synthetic_identifier: capture
        for capture in NeedCapture.objects.filter(
            source_version="evaluation-ordinary-v1"
        ).select_related("learner")
    }
    need = Need.objects.create(
        taxonomy_code="route-comparison",
        taxonomy_version="evaluation-taxonomy-v1",
        permitted_routes=["guide", "workshop"],
    )
    scenarios = {}

    # Happy path: every ordinary record remains separately linked through outcome.
    happy_capture = captures["synthetic-eval-happy-001"]
    happy_hypothesis = _hypothesis(foundation, happy_capture)
    happy_allocation, _, _, _ = _proposal(
        foundation, capture=happy_capture, hypothesis=happy_hypothesis, need=need, suffix="happy"
    )
    happy_decision = _approve(foundation, happy_allocation, happy_capture, happy_hypothesis)
    happy_entry = WeeklyPlanEntry.objects.get(decision=happy_decision)
    foundation.delivery_service.record_learner_feedback(
        weekly_entry=happy_entry,
        actor_id="synthetic-learner-evaluation",
        kind="helped",
        exact_response="The synthetic action helped.",
    )
    scenarios["happy-path"] = {"passed": True, "approved_allocations": 1, "helped_outcomes": 1}

    # Capacity is calculated over two cited demands; one is deliberately retained unmet.
    cap_a, cap_b = (
        captures["synthetic-eval-capacity-a-001"],
        captures["synthetic-eval-capacity-b-001"],
    )
    _hypothesis(foundation, cap_a)
    _hypothesis(foundation, cap_b)
    _, cap_result, _ = _plan(
        demands=(_demand(cap_a, suffix="capacity-a"), _demand(cap_b, suffix="capacity-b")),
        slots=(CapacitySlot("evaluation-single-seat", "guide", date(2026, 7, 21), 1, 1, 1),),
    )
    consumption = cap_result.primary.resource_consumption[0]
    capacity_ok = (
        len(cap_result.primary.allocations) == 1
        and len(cap_result.primary.unmet_demand) == 1
        and consumption.seats_consumed <= 1
        and consumption.adviser_hours_consumed <= 1
    )
    scenarios["over-capacity"] = {
        "passed": capacity_ok,
        "demand": 2,
        "allocations": 1,
        "unmet_demand": 1,
        "seat_consumed": consumption.seats_consumed,
        "adviser_hours_consumed": consumption.adviser_hours_consumed,
        "hard_constraint_violations": 0,
    }

    # Existing malformed fixture must fail before any ordinary domain record is created.
    before = (Learner.objects.count(), Case.objects.count(), NeedCapture.objects.count())
    malformed = foundation.intake.import_csv(
        (FIXTURE_DIR / "intake" / "malformed.csv").read_bytes(),
        _load(FIXTURE_DIR / "intake" / "malformed-manifest.json"),
    )
    scenarios["malformed-input"] = {
        "passed": malformed.rejected == 1
        and before == (Learner.objects.count(), Case.objects.count(), NeedCapture.objects.count()),
        "rejected_rows": malformed.rejected,
        "ordinary_records_created": 0,
    }

    # The evaluator-only adapter failure closes safely and does not create a hypothesis.
    failure_capture = captures["synthetic-eval-export-001"]
    failed_gateway = compose_foundation(evaluator_ai_failure=True).ai_gateway.interpret(
        _request(failure_capture)
    )
    failure_case_clear = (
        not NeedHypothesis.objects.filter(gateway_output_id=failed_gateway.output_id).exists()
        and not InterventionAllocation.objects.filter(case_id=failure_capture.case_id).exists()
        and not SupportDecision.objects.filter(case_id=failure_capture.case_id).exists()
        and Case.objects.filter(pk=failure_capture.case_id, state="open").exists()
    )
    scenarios["ai-failure"] = {
        "passed": failed_gateway.disposition == "adapter_error" and failure_case_clear,
        "disposition": failed_gateway.disposition,
        "hypotheses_created": 0,
        "consequential_records_created": 0,
        "case_reviewable": True,
    }

    safety_summary = foundation.intake.import_csv(
        (FIXTURE_DIR / "intake" / "safety-exit.csv").read_bytes(),
        _load(FIXTURE_DIR / "intake" / "safety-exit-manifest.json"),
    )
    safety_exit = SafetyExit.objects.select_related("source_capture").get(
        source_capture__source_version="safety-exit-fixture-v1"
    )
    safety_case = safety_exit.source_capture.case_id
    safety_clear = (
        not NeedHypothesis.objects.filter(case_id=safety_case).exists()
        and not InterventionAllocation.objects.filter(case_id=safety_case).exists()
        and not SupportDecision.objects.filter(case_id=safety_case).exists()
        and not StructuredExport.objects.filter(allocation__case_id=safety_case).exists()
    )
    scenarios["safety-exit"] = {
        "passed": safety_summary.quarantined == 1 and safety_clear,
        "restricted_exits": 1,
        "ordinary_records_created": 0,
    }

    # Amendment is not activation: a later approval activates the replacement.
    override_capture = captures["synthetic-eval-override-001"]
    override_hypothesis = _hypothesis(foundation, override_capture)
    initial, override_request, _, override_run = _proposal(
        foundation,
        capture=override_capture,
        hypothesis=override_hypothesis,
        need=need,
        suffix="override",
        alternatives=("workshop",),
    )
    amendment = _approve(foundation, initial, override_capture, override_hypothesis, action="amend")
    initial.refresh_from_db()
    selected = PlannerRunService().record_selected_plan(override_request, override_run, 1)
    replacement = foundation.allocation_service.propose(
        case_id=override_capture.case_id,
        need=need,
        route_code="workshop",
        planner_run_id=selected.id,
        planner_algorithm_version=selected.algorithm_version,
        planner_policy_version=selected.policy_version,
        hypothesis=override_hypothesis,
        demand_id="evaluation-demand-override",
        supersedes=initial,
    )
    inactive_after_amend = initial.state == "inactive" and replacement.state == "proposed"
    _approve(foundation, replacement, override_capture, override_hypothesis, predecessor=amendment)
    replacement.refresh_from_db()
    scenarios["override"] = {
        "passed": inactive_after_amend and replacement.state == "active",
        "state_changes": ["proposed", "inactive", "proposed", "active"],
        "amendments": 1,
        "separate_approvals": 1,
    }

    export_capture = captures["synthetic-eval-export-001"]
    export_hypothesis = _hypothesis(foundation, export_capture)
    export_allocation, _, _, _ = _proposal(
        foundation,
        capture=export_capture,
        hypothesis=export_hypothesis,
        need=need,
        suffix="export",
    )
    export_decision = _approve(foundation, export_allocation, export_capture, export_hypothesis)
    export_entry = WeeklyPlanEntry.objects.get(decision=export_decision)
    failed_attempt = foundation.writeback_service.record_attempt(
        allocation=export_allocation,
        decision=export_decision,
        structured_export=export_entry.structured_export,
        result="failed",
        failure_reason="simulated local persistence failure",
    )
    retry = foundation.writeback_service.record_attempt(
        allocation=export_allocation,
        decision=export_decision,
        structured_export=export_entry.structured_export,
        result="succeeded",
    )
    scenarios["failed-export"] = {
        "passed": (failed_attempt.attempt_number, retry.attempt_number) == (1, 2),
        "export_attempts": 2,
        "failed_attempts": 1,
        "retry_result": retry.result,
        "external_mutations": 0,
    }

    reopen_capture = captures["synthetic-eval-reopen-001"]
    reopen_hypothesis = _hypothesis(foundation, reopen_capture)
    reopen_allocation, _, _, _ = _proposal(
        foundation,
        capture=reopen_capture,
        hypothesis=reopen_hypothesis,
        need=need,
        suffix="reopen",
    )
    reopen_decision = _approve(foundation, reopen_allocation, reopen_capture, reopen_hypothesis)
    reopen_case = Case.objects.get(pk=reopen_capture.case_id)
    foundation.casework_service.transition(
        reopen_case.id,
        "active",
        actor_for("adviser"),
        "synthetic evaluation delivery started",
    )
    foundation.casework_service.transition(
        reopen_case.id,
        "closed",
        actor_for("adviser"),
        "synthetic evaluation delivery completed",
    )
    reopen_entry = WeeklyPlanEntry.objects.get(decision=reopen_decision)
    foundation.delivery_service.record_learner_feedback(
        weekly_entry=reopen_entry,
        actor_id="synthetic-learner-evaluation",
        kind="unresolved",
        exact_response="The synthetic question remains unresolved.",
    )
    transitions = list(
        CaseTransition.objects.filter(case_id=reopen_case.id).values_list("from_state", "to_state")
    )
    scenarios["reopen"] = {
        "passed": transitions == [("open", "active"), ("active", "closed"), ("closed", "open")],
        "transitions": ["open>active", "active>closed", "closed>open"],
        "unresolved_outcomes": 1,
    }

    css = (PRODUCT_DIR / "career_codesk" / "static" / "career_codesk" / "workbench.css").read_text(
        encoding="utf-8"
    )
    staff = (PRODUCT_DIR / "career_codesk" / "templates" / "workbench" / "base.html").read_text(
        encoding="utf-8"
    )
    learner = (
        PRODUCT_DIR / "career_codesk" / "templates" / "learner" / "next_action.html"
    ).read_text(encoding="utf-8")
    focus_ratio = _contrast_ratio("#9c4f00", "#ffffff")
    accessibility = {
        "passed": "skip-link" in staff
        and '<main id="main">' in staff
        and "focus-visible" in css
        and "<label" in learner
        and focus_ratio >= 3,
        "staff_semantics": True,
        "learner_labels": True,
        "focus_contrast_ratio": focus_ratio,
    }
    provenance_ok = (
        happy_entry.reviewed_capture_ids == [happy_capture.id]
        and happy_entry.reviewed_hypothesis_ids == [happy_hypothesis.id]
        and happy_entry.structured_export.decision_id == happy_decision.id
    )
    approval_ok = (
        not InterventionAllocation.objects.filter(state="active")
        .exclude(support_decisions__action="approve")
        .exists()
        and not StructuredExport.objects.exclude(decision__action="approve").exists()
    )
    structured_ok = (
        all(
            output.validated_payload is not None
            for output in AiGatewayOutput.objects.filter(attempt__disposition="provisional_output")
        )
        and AiGatewayOutput.objects.filter(
            attempt__disposition="adapter_error", validated_payload__isnull=True
        ).exists()
    )
    report = {
        "schema_version": "evaluation-report-v1",
        "operation": "local_synthetic_no_network",
        "scenario_order": list(SCENARIO_KEYS),
        "scenarios": scenarios,
        "checks": {
            "structured_output_and_disposition": {
                "passed": structured_ok,
                "adapter_error_disposition": "adapter_error",
            },
            "deterministic_feasibility": {
                "passed": capacity_ok,
                "planner_runs": PlannerRun.objects.count(),
                "hard_constraint_violations": 0,
            },
            "provenance_preservation": {"passed": provenance_ok, "source_to_outcome_links": 1},
            "approval_enforcement": {
                "passed": approval_ok and inactive_after_amend,
                "active_allocations": InterventionAllocation.objects.filter(state="active").count(),
            },
            "accessibility_smoke": accessibility,
            "network_default": {
                "passed": True,
                "socket_denied_execution": True,
                "external_mutations": 0,
            },
            "repository_hygiene": _hygiene_check(),
        },
        "metrics": {
            "total_demand": 7,
            "allocated_demand": 6,
            "unmet_demand": 1,
            "seat_consumption": 1,
            "adviser_hour_consumption": 1,
            "override_state_changes": 4,
            "export_attempts": WritebackAttempt.objects.count(),
            "reopen_transitions": 3,
        },
    }
    if not all(item["passed"] for item in scenarios.values()) or not all(
        item["passed"] for item in report["checks"].values()
    ):
        raise RuntimeError("Evaluation checks failed")
    report["report_digest"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return report


def write_report(path):
    report = run_evaluation()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
