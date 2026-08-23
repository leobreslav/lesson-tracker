"""
Адреса семьи. Стоят под `/api/family/`, а не под `/api/student/`: спрашивают
они не про ученика, а про его взрослых, и общий префикс со временем заставил
бы объяснять, почему у ученика есть раздел, которого он не видит.
"""

from django.urls import path

from .views import (
    ChildTeachersView,
    ChildrenView,
    FamilyThreadView,
    FamilyThreadsView,
)

urlpatterns = [
    path("children/", ChildrenView.as_view(), name="family-children"),
    path("teachers/", ChildTeachersView.as_view(), name="family-teachers"),
    path("threads/", FamilyThreadsView.as_view(), name="family-threads"),
    path("threads/<int:pk>/", FamilyThreadView.as_view(), name="family-thread"),
]
