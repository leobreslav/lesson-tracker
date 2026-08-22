from dj_rest_auth.views import LogoutView
from django.conf import settings
from django.urls import path

from .e2e import TestLoginView, TestPeopleView, TestResetView
from .views import GoogleLoginView, MeView

urlpatterns = [
    path("auth/google/", GoogleLoginView.as_view(), name="google_login"),
    path("auth/logout/", LogoutView.as_view(), name="rest_logout"),
    path("me/", MeView.as_view(), name="me"),
]

if settings.E2E_TEST_LOGIN:
    # not merely permission-checked — absent from the routing table, so the
    # path answers 404 like any other misspelling
    urlpatterns += [
        path("test/login/", TestLoginView.as_view(), name="e2e-login"),
        path("test/people/", TestPeopleView.as_view(), name="e2e-people"),
        path("test/reset/", TestResetView.as_view(), name="e2e-reset"),
    ]
