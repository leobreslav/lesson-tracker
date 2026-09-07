"""
Родство глазами администратора школы.

Форма та же, что у зачисления и назначения: строка на пару, рядом с ней —
кто эти двое. Ввод принимает не родителя по номеру, а **адрес**: у
администратора в руках список школы, а не наши идентификаторы, и родителя,
которого ещё нет, надо суметь завести тем же движением, что и связать.
"""

from accounts.models import Kind
from config.errors import Codes, api_error
from django.contrib.auth import get_user_model
from rest_framework import serializers
from schools import services as school_services
from schools.models import Invitation

from .models import Guardianship, link

User = get_user_model()


def person(user) -> dict:
    return {
        "id": user.pk,
        "name": " ".join(filter(None, (user.first_name, user.last_name))) or user.email,
        "email": user.email,
        # «ещё не входил»: та же пометка, что у учеников и учителей
        "arrived": user.last_login is not None,
    }


class GuardianshipSerializer(serializers.ModelSerializer):
    parent = serializers.SerializerMethodField()
    child_name = serializers.SerializerMethodField()
    # ввод: чей родитель и на каком адресе
    email = serializers.EmailField(write_only=True)
    child = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())

    class Meta:
        model = Guardianship
        fields = ("id", "parent", "child", "child_name", "email", "relation")
        read_only_fields = ("id",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            # ребёнок — ученик своей школы, и только он: чужой неотличим от
            # несуществующего, как всюду
            self.fields["child"].queryset = User.objects.filter(
                school_id=request.user.school_id, kind=Kind.STUDENT
            )

    def get_parent(self, row) -> dict:
        return person(row.parent)

    def get_child_name(self, row) -> str:
        return person(row.child)["name"]

    def validate_email(self, value):
        return value.strip().lower()

    def create(self, validated):
        """
        Связать — заведя родителя, если его ещё нет.

        Тот же путь, что у импорта: приглашение как билет и след, учётка
        сразу. Адрес, занятый учителем или учеником, — отказ: один адрес,
        один вид.
        """
        request = self.context["request"]
        school = request.user.school
        email = validated.pop("email")
        child = validated["child"]

        if email == child.email.lower():
            api_error(
                Codes.ROSTER_PARENT_IS_STUDENT,
                "The parent's address is the student's own.",
                field="email",
                email=email,
            )

        parent = User.objects.filter(email__iexact=email).first()
        trouble = school_services.member_problem(parent, Kind.PARENT, school)
        if trouble is not None:
            code, detail = trouble
            api_error(code, detail, field="email", email=email)

        if parent is None or parent.school_id != school.pk:
            Invitation.objects.get_or_create(
                school=school,
                email=email,
                defaults={"kind": Kind.PARENT, "created_by": request.user},
            )
            parent = school_services.provision(school, email, kind=Kind.PARENT)

        row = link(parent, child, relation=validated.get("relation", ""))
        if validated.get("relation") and row.relation != validated["relation"]:
            row.relation = validated["relation"]
            row.save(update_fields=["relation"])
        return row

    def update(self, row, validated):
        # меняется только «кем приходится»: пара — это сама строка
        row.relation = validated.get("relation", row.relation)
        row.save(update_fields=["relation"])
        return row
