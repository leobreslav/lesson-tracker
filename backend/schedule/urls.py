from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    CourseViewSet,
    ImportFromSchoolView,
    ImportPreviewView,
    LessonSlotViewSet,
)

router = DefaultRouter()
router.register("courses", CourseViewSet, basename="course")
router.register("slots", LessonSlotViewSet, basename="lessonslot")

urlpatterns = router.urls + [
    # the teacher's side of the school timetable: one-off copying into their
    # own schedule. The timetable itself lives under /api/school/
    path(
        "schedule/import-from-school/",
        ImportFromSchoolView.as_view(),
        name="import-from-school",
    ),
    path(
        "schedule/import-preview/",
        ImportPreviewView.as_view(),
        name="import-preview",
    ),
]
