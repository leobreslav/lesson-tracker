from dj_rest_auth.views import LogoutView
from django.conf import settings
from django.urls import path

from .dev_door import DevLoginView, DevPeopleView
from .views import GoogleLoginView, LoginCodeRequestView, LoginCodeVerifyView, MeView

urlpatterns = [
    path("auth/google/", GoogleLoginView.as_view(), name="google_login"),
    # вторая дверь — код из письма, для тех, у кого нет Google-аккаунта
    path("auth/code/request/", LoginCodeRequestView.as_view(), name="login_code_request"),
    path("auth/code/verify/", LoginCodeVerifyView.as_view(), name="login_code_verify"),
    path("auth/logout/", LogoutView.as_view(), name="rest_logout"),
    path("me/", MeView.as_view(), name="me"),
]

if settings.DEV_LOGIN:
    # not merely permission-checked — absent from the routing table, so the
    # path answers 404 like any other misspelling
    urlpatterns += [
        path("dev/login/", DevLoginView.as_view(), name="dev-login"),
        path("dev/people/", DevPeopleView.as_view(), name="dev-people"),
    ]
