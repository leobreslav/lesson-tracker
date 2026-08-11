from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from dj_rest_auth.registration.serializers import SocialLoginSerializer
from rest_framework import serializers

from .adapter import EmailNotVerifiedError
from .models import User


class GoogleLoginSerializer(SocialLoginSerializer):
    """
    Штатный SocialLoginSerializer требует access_token или code.

    Google Identity Services во frontend-flow отдаёт только id_token,
    поэтому подставляем его в access_token: дальше по коду для google
    сериализатор всё равно передаёт adapter'у response={"id_token": ...},
    а тот проверяет подпись по ключам Google (did_fetch_access_token=False).
    """

    def validate(self, attrs):
        id_token = attrs.get("id_token")

        if not (id_token or attrs.get("access_token") or attrs.get("code")):
            raise serializers.ValidationError("Требуется id_token или access_token.")

        if id_token and not attrs.get("access_token") and not attrs.get("code"):
            attrs["access_token"] = id_token

        try:
            return super().validate(attrs)
        except OAuth2Error as exc:
            # битый или просроченный id_token — это ошибка клиента, а не 500
            raise serializers.ValidationError(str(exc)) from exc
        except EmailNotVerifiedError as exc:
            raise serializers.ValidationError(
                "Google не подтвердил этот адрес электронной почты."
            ) from exc


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name")
        read_only_fields = fields
