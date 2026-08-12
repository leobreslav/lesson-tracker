from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from dj_rest_auth.registration.serializers import SocialLoginSerializer
from config.errors import Codes, api_error
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
            api_error(Codes.TOKEN_REQUIRED, "An id_token or access_token is required.")

        if id_token and not attrs.get("access_token") and not attrs.get("code"):
            attrs["access_token"] = id_token

        try:
            return super().validate(attrs)
        except OAuth2Error as exc:
            # a broken or expired id_token is a client error, not a 500
            api_error(Codes.TOKEN_INVALID, "The Google token is invalid or expired.")
        except EmailNotVerifiedError as exc:
            api_error(
                Codes.EMAIL_NOT_VERIFIED,
                "Google has not verified this email address.",
            )


class UserSerializer(serializers.ModelSerializer):
    """
    The profile, plus everything the interface needs to decide what to show.

    `school` is null for somebody nobody has invited yet — the frontend shows
    them the "ask your administrator" screen instead of the sections.
    """

    school = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "language",
            "school",
            "is_school_admin",
            "is_superuser",
        )
        # the email comes from Google and identifies the login — not editable;
        # the role is granted by an administrator, not claimed in a profile
        read_only_fields = (
            "id",
            "email",
            "school",
            "is_school_admin",
            "is_superuser",
        )

    def get_school(self, obj):
        if obj.school_id is None:
            return None
        return {"id": obj.school_id, "name": obj.school.name}
