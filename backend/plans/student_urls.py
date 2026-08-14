"""Адреса ученика в разделе плана: курс с его учебным планом."""

from django.urls import path

from .views import StudentCourseView

urlpatterns = [
    path("courses/<int:pk>/", StudentCourseView.as_view(), name="student-course"),
]
