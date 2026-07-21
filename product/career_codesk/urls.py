from django.conf import settings
from django.urls import path, re_path
from django.views.static import serve

from career_codesk.web import views

urlpatterns = [
    path("", views.home, name="home"),
    path("workbench/", views.queue, name="workbench-queue"),
    path("workbench/<str:allocation_id>/", views.review, name="workbench-review"),
    path("workbench/<str:allocation_id>/confirm/", views.confirm, name="workbench-confirm"),
    path("workbench/<str:allocation_id>/decide/", views.decide, name="workbench-decide"),
    path("plans/", views.weekly_plans, name="weekly-plan-list"),
    path("plans/<str:entry_id>/", views.weekly_plan_detail, name="weekly-plan-detail"),
    path("learner/<str:case_id>/", views.learner_next_action, name="learner-next-action"),
    path(
        "learner/actions/<str:entry_id>/feedback/",
        views.learner_feedback,
        name="learner-feedback",
    ),
    path("health/", views.health, name="health"),
    # This product is an explicitly loopback-only synthetic demonstrator. Keep
    # DEBUG disabled while still making its checked-in stylesheet available to
    # the documented local runserver command.
    re_path(
        r"^static/(?P<path>.*)$",
        serve,
        {"document_root": settings.STATICFILES_DIRS[0], "show_indexes": False},
        name="local-static",
    ),
]
