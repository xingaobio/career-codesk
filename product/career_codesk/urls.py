from django.urls import path

from career_codesk.web import views

urlpatterns = [
    path("", views.home, name="home"),
    path("workbench/", views.queue, name="workbench-queue"),
    path("workbench/<str:allocation_id>/", views.review, name="workbench-review"),
    path("workbench/<str:allocation_id>/confirm/", views.confirm, name="workbench-confirm"),
    path("workbench/<str:allocation_id>/decide/", views.decide, name="workbench-decide"),
    path("health/", views.health, name="health"),
]
