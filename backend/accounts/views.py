from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from dj_rest_auth.registration.views import SocialLoginView
from rest_framework.generics import RetrieveUpdateAPIView

from .serializers import GoogleLoginSerializer, UserSerializer


class GoogleLoginView(SocialLoginView):
    """POST {"id_token": ...} либо {"access_token": ...} -> {"key": "<токен DRF>"}."""

    adapter_class = GoogleOAuth2Adapter
    serializer_class = GoogleLoginSerializer


class MeView(RetrieveUpdateAPIView):
    """GET — профиль текущего пользователя, PATCH — правка имени и фамилии."""

    serializer_class = UserSerializer
    # PUT не нужен: обновление только частичное
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        # редактировать можно только себя: объект берётся из запроса, а не из URL
        return self.request.user
