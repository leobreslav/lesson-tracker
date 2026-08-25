"""
Половина ученика: список работ, одна работа и отправка ответа.

Своими адресами, а не общими с учительскими: спрашивают они другое и
отвечают другим, и ветка «если ученик» внутри одного вьюсета была бы
длиннее двух отдельных вьюх.
"""

from django.urls import path

from .photo_views import StudentPhotosView, StudentPhotoView
from .views import (
    StudentAnswerView,
    StudentJournalView,
    StudentWorkView,
    StudentWorksView,
)

urlpatterns = [
    path("works/", StudentWorksView.as_view(), name="student-works"),
    # журнал курса глазами семьи: та же таблица, но строка одна — своя
    path("journal/", StudentJournalView.as_view(), name="student-journal"),
    path("works/<int:pk>/", StudentWorkView.as_view(), name="student-work"),
    path("tasks/<int:pk>/answer/", StudentAnswerView.as_view(), name="student-answer"),
    # фотография работы: кладёт её ученик — или родитель за него
    path(
        "works/<int:pk>/photos/",
        StudentPhotosView.as_view(),
        name="student-photos",
    ),
    path("photos/<int:pk>/", StudentPhotoView.as_view(), name="student-photo"),
]
