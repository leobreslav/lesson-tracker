from accounts.models import Kind
from config.errors import Codes, api_error
from django.contrib.auth import get_user_model
from rest_framework import serializers

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
    # число приходит аннотацией вьюсета: `source="members.count"` — запрос
    # на школу, а список школ у суперпользователя как раз список
    members = serializers.SerializerMethodField()
    admins = serializers.SerializerMethodField()

    def get_members(self, school) -> int:
        return getattr(school, "member_count", school.members.count())

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
    kind = serializers.CharField(read_only=True)
    # «ещё не входил»: приглашение заводит учётку сразу, и в списках такие
    # люди стоят наравне со всеми — отличает их только эта пометка. Своего
    # поля не нужно, `last_login` пуст ровно до первого входа
    arrived = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "email", "first_name", "last_name", "kind",
            "is_school_admin", "courses", "arrived",
        )
        read_only_fields = ("id", "email", "first_name", "last_name", "kind")

    def get_arrived(self, person) -> bool:
        return person.last_login is not None

    def get_courses(self, person) -> list:
        """
        Чем человек связан с курсами: учитель назначением, ученик
        зачислением.

        Ответ у обоих одной формы — «курс и строка связи», — потому что
        экраны с ним делают одно и то же: показывают список и снимают
        связь. Различие в одном поле: у ученика зачисление бывает снятым, и
        он всё равно остаётся в списке.
        """
        if person.is_student:
            return [
                {
                    "id": row.course_id,
                    "name": row.course.name,
                    "row": row.pk,
                    "active": row.is_active,
                }
                for row in person.enrolments.all()
            ]

        return [
            {
                "id": item.course_id,
                "name": item.course.name,
                "assignment": item.pk,
            }
            # `.all()`, а не `select_related`: второй игнорирует предвыборку
            # вьюсета и снова идёт в базу — запрос на человека
            for item in person.course_assignments.all()
        ]

    def validate_is_school_admin(self, value):
        # роль администратора — про общие объекты школы, а ученик в них не
        # заходит вовсе; запрет тот же, что у приглашения
        if self.instance is not None and self.instance.is_student:
            api_error(
                Codes.NOT_A_STUDENT,
                "A student cannot be an administrator of the school.",
                field="is_school_admin",
            )

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

    **Создание заводит учётку** (`services.provision`), а не только строку
    приглашения: с этой минуты человека видно в списках, ему можно поручить
    курс и записать его на курс обычными таблицами. Курсов в самом
    приглашении больше нет — носить их было незачем, как только появился
    тот, кому их назначают.
    """

    accepted = serializers.BooleanField(source="is_accepted", read_only=True)

    class Meta:
        model = Invitation
        fields = (
            "id",
            "email",
            "name",
            "kind",
            "is_school_admin",
            "created_at",
            "accepted_at",
            "accepted",
        )
        read_only_fields = ("id", "created_at", "accepted_at")

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
    kind = serializers.CharField(read_only=True)
    # «ещё не входил»: приглашение заводит учётку сразу, и в списках такие
    # люди стоят наравне со всеми — отличает их только эта пометка. Своего
    # поля не нужно, `last_login` пуст ровно до первого входа
    arrived = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "email", "first_name", "last_name", "kind",
            "is_school_admin", "courses", "arrived",
        )
        read_only_fields = ("id", "email", "first_name", "last_name", "kind")

    def get_arrived(self, person) -> bool:
        return person.last_login is not None

    def get_courses(self, person) -> list:
        """
        Чем человек связан с курсами: учитель назначением, ученик
        зачислением.

        Ответ у обоих одной формы — «курс и строка связи», — потому что
        экраны с ним делают одно и то же: показывают список и снимают
        связь. Различие в одном поле: у ученика зачисление бывает снятым, и
        он всё равно остаётся в списке.
        """
        if person.is_student:
            return [
                {
                    "id": row.course_id,
                    "name": row.course.name,
                    "row": row.pk,
                    "active": row.is_active,
                }
                for row in person.enrolments.all()
            ]

        return [
            {
                "id": item.course_id,
                "name": item.course.name,
                "assignment": item.pk,
            }
            # `.all()`, а не `select_related`: второй игнорирует предвыборку
            # вьюсета и снова идёт в базу — запрос на человека
            for item in person.course_assignments.all()
        ]

    def validate_is_school_admin(self, value):
        # роль администратора — про общие объекты школы, а ученик в них не
        # заходит вовсе; запрет тот же, что у приглашения
        if self.instance is not None and self.instance.is_student:
            api_error(
                Codes.NOT_A_STUDENT,
                "A student cannot be an administrator of the school.",
                field="is_school_admin",
            )

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

    **Создание заводит учётку** (`services.provision`), а не только строку
    приглашения: с этой минуты человека видно в списках, ему можно поручить
    курс и записать его на курс обычными таблицами. Курсов в самом
    приглашении больше нет — носить их было незачем, как только появился
    тот, кому их назначают.
    """

    accepted = serializers.BooleanField(source="is_accepted", read_only=True)

    class Meta:
        model = Invitation
        fields = (
            "id",
            "email",
            "name",
            "kind",
            "is_school_admin",
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

        # адрес занят кем-то другого вида или уже состоит в школе — отказ
        # здесь, а не молчание при входе: приглашение, которое никогда не
        # сработает, хуже отказа, потому что администратор считает, что
        # пригласил
        services.check_address(email, kind)

        if kind == Kind.STUDENT and attrs.get("is_school_admin"):
            api_error(
                Codes.NOT_A_STUDENT,
                "A student invitation cannot grant the administrator role.",
                field="is_school_admin",
            )

        return attrs

