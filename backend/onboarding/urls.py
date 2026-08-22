from django.urls import path

from .views import DemoView, StatusView

urlpatterns = [
    path("status/", StatusView.as_view(), name="onboarding-status"),
    path("demo/", DemoView.as_view(), name="onboarding-demo"),
]
