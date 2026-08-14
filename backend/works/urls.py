"""Учительская половина работ: сами работы и задачи внутри них."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import TaskViewSet, WorkViewSet

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="task")
router.register("", WorkViewSet, basename="work")

urlpatterns = [path("", include(router.urls))]
