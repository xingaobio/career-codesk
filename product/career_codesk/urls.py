from django.urls import path

from career_codesk.web import views

urlpatterns = [path("", views.home, name="home"), path("health/", views.health, name="health")]
