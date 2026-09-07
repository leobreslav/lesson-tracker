from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from dj_rest_auth.registration.views import SocialLoginView
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import codes
from .serializers import GoogleLoginSerializer, UserSerializer


class GoogleLoginView(SocialLoginView):
    """POST {"id_token": ...} либо {"access_token": ...} -> {"key": "<токен DRF>"}."""

    adapter_class = GoogleOAuth2Adapter
    serializer_class = GoogleLoginSerializer


class LoginCodeView(APIView):
    """
    Вход по коду из письма: две ступени под одним классом.

    Без аутентификации по построению — токена у входящего ещё нет, — и с
    ограничением частоты по адресу запроса: дверь, которой можно заваливать
    чужую почту, это не дверь. Правила самой двери — в `accounts/codes.py`.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login_code"


class LoginCodeRequestView(LoginCodeView):
    """POST {"email": ...} -> {"sent": true} — одинаково для любого адреса."""

    def post(self, request):
        codes.request_code(request.data.get("email") or "")
        # ответ не различает адреса намеренно: незнакомый, чужой для контура
        # и слишком частый выглядят так же, как ушедшее письмо
        return Response({"sent": True})


class LoginCodeVerifyView(LoginCodeView):
    """POST {"email": ..., "code": ...} -> {"key": "<токен DRF>"}, как у Google."""

    def post(self, request):
        token = codes.verify_code(
            request.data.get("email") or "", request.data.get("code") or ""
        )
        return Response({"key": token.key})


class MeView(RetrieveUpdateAPIView):
    """GET — профиль текущего пользователя, PATCH — правка имени и фамилии."""

    serializer_class = UserSerializer
    # PUT не нужен: обновление только частичное
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        # редактировать можно только себя: объект берётся из запроса, а не из URL
        return self.request.user
