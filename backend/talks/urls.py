"""Мессенджер: список собеседников и разговор с человеком."""

from django.urls import path

from .views import TalkView, TalksView

urlpatterns = [
    path("", TalksView.as_view(), name="talks"),
    path("<int:person>/", TalkView.as_view(), name="talk"),
]
