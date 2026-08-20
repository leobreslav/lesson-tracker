"""Учительская половина работ: сами работы и задачи внутри них."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .grading_views import GradingSystemsView, GradingSystemView
from .views import SubmissionViewSet, TaskThreadView, TaskViewSet, WorkViewSet

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="task")
router.register("submissions", SubmissionViewSet, basename="submission")
router.register("", WorkViewSet, basename="work")

urlpatterns = [
    path("thread/", TaskThreadView.as_view(), name="task-thread"),
    path("grading/", GradingSystemsView.as_view(), name="grading-systems"),
    # справочник до роутера: иначе «grading» уедет в работу с таким id
    path("grading/<int:pk>/", GradingSystemView.as_view(), name="grading-system"),
    path("", include(router.urls)),
]
