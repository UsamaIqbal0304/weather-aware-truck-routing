from django.urls import path

from trucking.api import views

urlpatterns = [
    path("api/health", views.health, name="health"),
    path("api/geocode", views.geocode_view, name="geocode"),
    path("api/plan", views.plan_view, name="plan"),
]
