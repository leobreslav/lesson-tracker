from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from dj_rest_auth.registration.views import SocialLoginView
from rest_framework.generics import RetrieveAPIView

from .serializers import GoogleLoginSerializer, UserSerializer


class GoogleLoginView(SocialLoginView):
    """POST {"id_token": ...} либо {"access_token": ...} -> {"key": "<токен DRF>"}."""

    adapter_class = GoogleOAuth2Adapter
    serializer_class = GoogleLoginSerializer


class MeView(RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user
