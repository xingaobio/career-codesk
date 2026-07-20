from django.urls import path

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
]
