"""
Половина ученика: список работ, одна работа и отправка ответа.

Своими адресами, а не общими с учительскими: спрашивают они другое и
отвечают другим, и ветка «если ученик» внутри одного вьюсета была бы
длиннее двух отдельных вьюх.
"""

from django.urls import path

from .views import StudentAnswerView, StudentWorkView, StudentWorksView

urlpatterns = [
    path("works/", StudentWorksView.as_view(), name="student-works"),
    path("works/<int:pk>/", StudentWorkView.as_view(), name="student-work"),
    path("tasks/<int:pk>/answer/", StudentAnswerView.as_view(), name="student-answer"),
]
