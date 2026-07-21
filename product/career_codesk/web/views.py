"""Server-rendered, synthetic-only adviser workbench views."""

from django.db import OperationalError
from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, render

from career_codesk.composition import compose_foundation
from career_codesk.domain import DomainInvariantError
from career_codesk.identity import UnsupportedRoleError, actor_for
from career_codesk.modules.decisions.workbench import (
    DecisionWorkbenchService,
    StaleWorkbenchInput,
    WorkbenchQueryService,
)
from career_codesk.modules.delivery_feedback.services import DeliveryFeedbackService
from career_codesk.modules.export.services import WritebackService
from career_codesk.modules.planning.models import WeeklyPlanEntry


def home(request):
    """The workbench is the primary local prototype surface."""
    return queue(request)


def health(request):
    return HttpResponse("ok", content_type="text/plain")


def queue(request):
    sort = request.GET.get("sort", "age")
    projection = WorkbenchQueryService()
    try:
        items = projection.queue(sort=sort)
    except OperationalError as error:
        # A fresh local checkout can render the documented foundation page before
        # its synthetic SQLite schema is migrated.  Do not conceal other DB errors.
        if "no such table" not in str(error):
            raise
        items = ()
    return render(
        request,
        "workbench/queue.html",
        {
            "foundation": compose_foundation(),
            "items": items,
            "sort": sort if sort in {"age", "wait", "case", "route"} else "age",
        },
    )


def review(request, allocation_id):
    item = WorkbenchQueryService().get(allocation_id)
    if item is None:
        # Restricted safety evidence is intentionally indistinguishable from an
        # absent ordinary record on this route.
        raise Http404("Ordinary proposal not found")
    return render(request, "workbench/review.html", item)


def confirm(request, allocation_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    item = WorkbenchQueryService().get(allocation_id)
    if item is None:
        raise Http404("Ordinary proposal not found")
    action = request.POST.get("action")
    if action not in {"approve", "amend", "reject"}:
        return render(
            request, "workbench/review.html", {**item, "error": "Choose a decision."}, status=400
        )
    context = {
        **item,
        "action": action,
        "reason": request.POST.get("reason", ""),
        "actor": request.POST.get("actor", "adviser"),
        "alternative_index": request.POST.get("alternative_index", ""),
    }
    if not context["reason"].strip():
        return render(
            request,
            "workbench/review.html",
            {**item, "error": "Enter a reason before continuing."},
            status=400,
        )
    if action == "amend" and not context["alternative_index"]:
        return render(
            request,
            "workbench/review.html",
            {**item, "error": "Choose a feasible alternative before continuing."},
            status=400,
        )
    if action == "amend":
        selected = next(
            (
                alternative
                for alternative in item["alternatives"]
                if str(alternative["index"]) == context["alternative_index"]
            ),
            None,
        )
        if selected is None:
            return render(
                request,
                "workbench/review.html",
                {**item, "error": "Choose a feasible alternative before continuing."},
                status=400,
            )
        context["selected_alternative"] = selected
    return render(request, "workbench/confirm.html", context)


def decide(request, allocation_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    item = WorkbenchQueryService().get(allocation_id)
    if item is None:
        raise Http404("Ordinary proposal not found")
    reviewed_inputs = [("capture", capture.id) for capture in item["captures"]] + [
        ("hypothesis", hypothesis.id) for hypothesis in item["hypotheses"]
    ]
    try:
        actor = actor_for(request.POST.get("actor", ""))
        outcome = DecisionWorkbenchService().decide(
            allocation_id=allocation_id,
            action=request.POST.get("action", ""),
            actor=actor,
            reason=request.POST.get("reason", ""),
            reviewed_inputs=reviewed_inputs,
            expected_planner_digest=request.POST.get("planner_digest", ""),
            expected_decision_token=request.POST.get("decision_token", ""),
            alternative_index=request.POST.get("alternative_index"),
        )
    except StaleWorkbenchInput as error:
        return render(
            request,
            "workbench/review.html",
            {**item, "error": str(error), "stale": True},
            status=409,
        )
    except (DomainInvariantError, UnsupportedRoleError) as error:
        return render(request, "workbench/review.html", {**item, "error": str(error)}, status=400)
    return render(request, "workbench/result.html", {"outcome": outcome})


def weekly_plans(request):
    """Small staff inspection surface for immutable execution packages."""
    entries = WeeklyPlanEntry.objects.select_related(
        "need", "decision", "allocation", "planner_run", "adviser_brief", "structured_export"
    ).order_by("scheduled_on", "id")
    return render(request, "plans/list.html", {"entries": entries})


def weekly_plan_detail(request, entry_id):
    entry = get_object_or_404(
        WeeklyPlanEntry.objects.select_related(
            "need", "decision", "allocation", "planner_run", "adviser_brief", "structured_export"
        ),
        pk=entry_id,
    )
    export_state = WritebackService().reconcile_local_state(
        structured_export=entry.structured_export
    )
    return render(request, "plans/detail.html", {"entry": entry, "export_state": export_state})


def learner_next_action(request, case_id):
    """One local, adviser-approved action, never a learner-facing AI response."""
    entry = (
        WeeklyPlanEntry.objects.select_related("allocation", "adviser_brief", "structured_export")
        .filter(case_id=case_id, allocation__state="active")
        .order_by("scheduled_on", "created_at", "id")
        .first()
    )
    if entry is None:
        raise Http404("No approved local action is available")
    export_state = WritebackService().reconcile_local_state(
        structured_export=entry.structured_export
    )
    return render(
        request,
        "learner/next_action.html",
        {"entry": entry, "export_state": export_state},
    )


def learner_feedback(request, entry_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    entry = get_object_or_404(WeeklyPlanEntry, pk=entry_id)
    kind = request.POST.get("kind", "")
    try:
        feedback = DeliveryFeedbackService().record_learner_feedback(
            weekly_entry=entry,
            actor_id="synthetic-learner-local-view",
            kind=kind,
            exact_response=request.POST.get("response", ""),
            correction_statement=request.POST.get("correction_statement"),
        )
    except DomainInvariantError as error:
        return render(
            request,
            "learner/next_action.html",
            {"entry": entry, "error": str(error), "export_state": "not_sent"},
            status=400,
        )
    return render(request, "learner/feedback_recorded.html", {"feedback": feedback, "entry": entry})
