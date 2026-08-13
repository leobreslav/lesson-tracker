from config.errors import Codes, api_error
from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Invitation, School

User = get_user_model()


class SchoolSerializer(serializers.ModelSerializer):
    """
    The school itself. Only the name is editable — that is all it holds.

    Who may edit depends on the door: an administrator renames their own
    school through /api/school/, a superuser manages every school through
    /api/schools/.
    """

    members = serializers.IntegerField(source="members.count", read_only=True)
    admins = serializers.SerializerMethodField()

    class Meta:
        model = School
        fields = ("id", "name", "created_at", "members", "admins")
        read_only_fields = ("id", "created_at")

    def get_admins(self, obj):
        """Who runs this school — the list a superuser needs to see."""
        return [
            member.email
            for member in obj.members.filter(is_school_admin=True).order_by("email")
        ]


class SchoolInviteSerializer(serializers.Serializer):
    """Handing a brand new school its first administrator."""

    email = serializers.EmailField()

    def validate_email(self, value):
        value = value.strip().lower()
        member = User.objects.filter(email__iexact=value).first()
        if member is not None and member.school_id is not None:
            api_error(
                Codes.ALREADY_MEMBER,
                f"«{value}» already belongs to a school.",
                field="email",
                email=value,
            )
        return value


class MemberSerializer(serializers.ModelSerializer):
    """
    A member of the school as the school sees them.

    Only the role is writable: names and addresses belong to the person, an
    administrator manages membership, not identity.
    """

    courses = serializers.SerializerMethodField()
    methodist_subjects = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "email", "first_name", "last_name", "is_school_admin", "courses",
            "methodist_subjects",
        )
        read_only_fields = ("id", "email", "first_name", "last_name")

    def get_methodist_subjects(self, person) -> list:
        """
        По каким предметам человек утверждает планы.

        Роль висит на паре «человек и предмет», а не на человеке: методистов
        по алгебре бывает двое, и один человек может отвечать за два
        предмета.
        """
        return [
            {"id": row.subject_id, "name": row.subject.name}
            for row in person.methodist_of.all()
        ]

    def get_courses(self, person) -> list:
        """
        What this person teaches — the other half of the assignment table.

        The course card shows its teachers, the teacher card shows their
        courses, and both are read from the same rows: one link, two ways of
        looking for it.
        """
        return [
            {
                "id": item.course_id,
                "name": item.course.name,
                "assignment": item.pk,
            }
            for item in person.course_assignments.select_related("course")
        ]

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
