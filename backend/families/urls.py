"""
Адреса семьи. Стоят под `/api/family/`, а не под `/api/student/`: спрашивают
они не про ученика, а про его взрослых, и общий префикс со временем заставил
бы объяснять, почему у ученика есть раздел, которого он не видит.
"""

from django.urls import path

from .views import ChildTeachersView, ChildrenView

urlpatterns = [
    path("children/", ChildrenView.as_view(), name="family-children"),
    path("teachers/", ChildTeachersView.as_view(), name="family-teachers"),
    # Переписки здесь больше нет: она общая для всех собеседников и живёт под
    # `/api/talks/`. Разговор родителя с учителем — её случай, а не свой вид.
]
