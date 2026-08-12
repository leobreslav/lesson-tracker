from config.errors import Codes, api_error
from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Invitation, School

User = get_user_model()


class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = School
        fields = ("id", "name")
        read_only_fields = ("id", "name")


class MemberSerializer(serializers.ModelSerializer):
    """
    A member of the school as the school sees them.

    Only the role is writable: names and addresses belong to the person, an
    administrator manages membership, not identity.
    """

    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "is_school_admin")
        read_only_fields = ("id", "email", "first_name", "last_name")

    def validate_is_school_admin(self, value):
        if value:
            return value

        user = self.instance
        # a school without an administrator can never be repaired from the
        # interface again, so the last one cannot step down alone
        others = User.objects.filter(
            school_id=user.school_id, is_school_admin=True
        ).exclude(pk=user.pk)
        if not others.exists():
            api_error(
                Codes.LAST_ADMIN,
                "This is the only administrator of the school. Give the role "
                "to somebody else first.",
                field="is_school_admin",
            )
        return value


class InvitationSerializer(serializers.ModelSerializer):
    accepted = serializers.BooleanField(source="is_accepted", read_only=True)

    class Meta:
        model = Invitation
        fields = (
            "id",
            "email",
            "is_school_admin",
            "created_at",
            "accepted_at",
            "accepted",
        )
        read_only_fields = ("id", "created_at", "accepted_at")

    def validate_email(self, value):
        # Google hands back a lowercase address; storing it the same way keeps
        # the lookup on sign-in an exact match
        value = value.strip().lower()
        school = self.context["request"].user.school

        if Invitation.objects.filter(school=school, email=value).exists():
            api_error(
                Codes.INVITATION_EXISTS,
                f"«{value}» has already been invited to this school.",
                field="email",
                email=value,
            )

        member = User.objects.filter(email__iexact=value).first()
        if member is not None and member.school_id is not None:
            api_error(
                Codes.ALREADY_MEMBER,
                f"«{value}» already belongs to a school.",
                field="email",
                email=value,
            )

        return value
