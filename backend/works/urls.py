"""Учительская половина работ: сами работы и задачи внутри них."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .grading_views import GradingSystemsView, GradingSystemView
from .photo_views import (
    PhotoMarkupView,
    PhotoNoteView,
    PhotoNotesView,
    PhotoStrokesView,
)
from .views import (
    StudentTrackView,
    SubmissionViewSet,
    TaskThreadView,
    TaskViewSet,
    WorkViewSet,
)

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="task")
router.register("submissions", SubmissionViewSet, basename="submission")
router.register("", WorkViewSet, basename="work")

urlpatterns = [
    path("thread/", TaskThreadView.as_view(), name="task-thread"),
    path(
        "track/<int:student>/",
        StudentTrackView.as_view(),
        name="student-track",
    ),
    path("grading/", GradingSystemsView.as_view(), name="grading-systems"),
    # справочник до роутера: иначе «grading» уедет в работу с таким id
    path("grading/<int:pk>/", GradingSystemView.as_view(), name="grading-system"),
    # просмотрщик — до роутера по той же причине, что и справочник
    path(
        "photos/<int:pk>/",
        PhotoMarkupView.as_view(),
        name="photo-markup",
    ),
    path(
        "photos/<int:pk>/strokes/",
        PhotoStrokesView.as_view(),
        name="photo-strokes",
    ),
    path(
        "photos/<int:pk>/notes/",
        PhotoNotesView.as_view(),
        name="photo-notes",
    ),
    path("notes/<int:pk>/", PhotoNoteView.as_view(), name="photo-note"),
    path("", include(router.urls)),
]
