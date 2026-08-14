"""Адреса ученика. Пока один, но ветка своя с самого начала."""

from django.urls import path

from .views import StudentCoursesView

urlpatterns = [
    path("courses/", StudentCoursesView.as_view(), name="student-courses"),
]
