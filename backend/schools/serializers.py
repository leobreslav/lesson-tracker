from accounts.models import Kind
from config.errors import Codes, api_error
from django.contrib.auth import get_user_model
from rest_framework import serializers
from schedule.models import Course

from . import services

from .models import Invitation, School

User = get_user_model()


class SchoolSerializer(serializers.ModelSerializer):
    """
    The school itself. Only the name is editable — that is all it holds.

    Who may edit depends on the door: an administrator renames their own
    school through /api/school/, a superuser manages every school through
    /api/schools/.
    """

    # все привязанные к школе, ученики в том числе: число отвечает на вопрос
    # «кто мешает её удалить», а мешают все — `User.school` стоит на PROTECT.
    # Внутри школы «учителей» считает обзор, и там сужение по виду есть
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
            for member in obj.members.filter(
                is_school_admin=True, kind=User.Kind.TEACHER
            ).order_by("email")
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

    class Meta:
        model = User
        fields = (
            "id", "email", "first_name", "last_name", "is_school_admin", "courses",
        )
        read_only_fields = ("id", "email", "first_name", "last_name")

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
    """
    Приглашение в школу — учителю или ученику.

    Вид назван здесь, а не выведен из чего-то: адрес становится учительским
    или ученическим в момент приглашения, и одна почта не бывает и тем и
    другим. Проверка адреса общая на все входы — `services.check_address`.
    """

    accepted = serializers.BooleanField(source="is_accepted", read_only=True)

    class Meta:
        model = Invitation
        fields = (
            "id",
            "email",
            "kind",
            "is_school_admin",
            "courses",
            "created_at",
            "accepted_at",
            "accepted",
        )
        read_only_fields = ("id", "created_at", "accepted_at")

    def validate_email(self, value):
        # Google hands back a lowercase address; storing it the same way keeps
        # the lookup on sign-in an exact match
        return value.strip().lower()

    def validate(self, attrs):
        school = self.context["request"].user.school
        email = attrs["email"]
        kind = attrs.get("kind", Kind.TEACHER)

        if Invitation.objects.filter(school=school, email=email).exists():
            api_error(
                Codes.INVITATION_EXISTS,
                f"«{email}» has already been invited to this school.",
                field="email",
                email=email,
            )

        # адрес занят кем-то другого вида или из другой школы — отказ здесь,
        # а не молчание при входе: приглашение, которое никогда не сработает,
        # хуже отказа, потому что администратор считает, что пригласил
        services.check_address(email, kind)

        member = User.objects.filter(email__iexact=email).first()
        if member is not None and member.school_id is not None:
            api_error(
                Codes.ALREADY_MEMBER,
                f"«{email}» already belongs to a school.",
                field="email",
                email=email,
            )

        if kind == Kind.STUDENT and attrs.get("is_school_admin"):
            api_error(
                Codes.NOT_A_STUDENT,
                "A student invitation cannot grant the administrator role.",
                field="is_school_admin",
            )

        return attrs

    def get_fields(self):
        fields = super().get_fields()
        # контекста может не быть вовсе: суперпользователь приглашает первого
        # администратора и сериализует ответ без запроса
        user = getattr(self.context.get("request"), "user", None)
        fields["courses"].child_relation.queryset = Course.objects.filter(
            school_id=getattr(user, "school_id", None)
        )
        return fields
