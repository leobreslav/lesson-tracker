from dj_rest_auth.views import LogoutView
from django.urls import path

from .views import GoogleLoginView, MeView

urlpatterns = [
    path("auth/google/", GoogleLoginView.as_view(), name="google_login"),
    path("auth/logout/", LogoutView.as_view(), name="rest_logout"),
    path("me/", MeView.as_view(), name="me"),
]
