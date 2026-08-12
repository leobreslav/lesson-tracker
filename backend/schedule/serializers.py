from calendars import services as calendar_services
from calendars.models import SchoolYear
from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from . import services
from .models import LessonSlot, SchoolClass


def own_classes(serializer):
    """Классы владельца запроса — чужой в поле не подставить."""
    user = getattr(serializer.context.get("request"), "user", None)
    if user is None or not user.is_authenticated:
        return SchoolClass.objects.none()
    return SchoolClass.objects.filter(owner=user)


class SchoolClassSerializer(serializers.ModelSerializer):
    # владелец берётся из токена: из тела запроса его не подставить
    owner = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = SchoolClass
        fields = ("id", "owner", "year", "name", "created_at")
        read_only_fields = ("created_at",)
        validators = [
            # owner в теле запроса нет, поэтому unique_together DRF сам не
            # проверит — без валидатора дубль падал бы с 500
            UniqueTogetherValidator(
                queryset=SchoolClass.objects.all(),
                fields=("owner", "year", "name"),
                message="Класс с таким названием в этом году уже есть.",
            ),
        ]

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        # класс можно завести только в своём учебном году
        user = getattr(request, "user", None)
        fields["year"].queryset = (
            SchoolYear.objects.filter(owner=user)
            if user is not None and user.is_authenticated
            else SchoolYear.objects.none()
        )
        return fields


class LessonSlotSerializer(serializers.ModelSerializer):
    # год выводится из класса, в теле запроса его можно не присылать
    year = serializers.PrimaryKeyRelatedField(
        queryset=SchoolYear.objects.none(), required=False
    )
    warning = serializers.SerializerMethodField()

    class Meta:
        model = LessonSlot
        fields = (
            "id",
            "year",
            "school_class",
            "date",
            "lesson_number",
            "is_cancelled",
            "is_extra",
            "reason",
            "created_at",
            "warning",
        )
        read_only_fields = ("created_at",)
        validators = [
            UniqueTogetherValidator(
                queryset=LessonSlot.objects.all(),
                fields=("school_class", "date", "lesson_number"),
                message="В этот день у класса уже есть урок с таким номером.",
            ),
        ]

    def get_fields(self):
        fields = super().get_fields()
        classes = own_classes(self)
        fields["school_class"].queryset = classes
        fields["year"].queryset = SchoolYear.objects.filter(
            pk__in=classes.values("year_id")
        )
        return fields

    def get_warning(self, obj):
        """
        Урок в неучебный день не запрещаем — бывают отработки и субботники, —
        но говорим об этом в ответе.
        """
        day = calendar_services.resolve_day(
            obj.date, obj.year.weekend_days, obj.year.periods()
        )
        if day.is_study:
            return None

        label = calendar_services.STATUS_LABELS[day.status]
        note = f" «{day.title}»" if day.title else ""
        return f"{obj.date:%d.%m.%Y} — {label}{note}. Урок стоит вне учебных дней."

    def validate(self, attrs):
        def value(name):
            return attrs.get(name, getattr(self.instance, name, None))

        school_class = value("school_class")
        year = attrs.get("year") or school_class.year
        slot_date = value("date")

        if year != school_class.year:
            raise serializers.ValidationError(
                {"year": "Год урока должен совпадать с годом класса."}
            )

        if not year.start_date <= slot_date <= year.end_date:
            raise serializers.ValidationError(
                {
                    "date": (
                        "Дата вне границ учебного года "
                        f"({year.start_date} — {year.end_date})."
                    )
                }
            )

        if not value("is_cancelled"):
            # два класса на одном номере в один день учитель не потянет
            busy = LessonSlot.find_conflict(
                year=year,
                date=slot_date,
                lesson_number=value("lesson_number"),
                exclude_pk=self.instance.pk if self.instance else None,
            )
            if busy is not None:
                raise serializers.ValidationError(
                    {
                        "lesson_number": services.occupied_message(
                            slot_date, value("lesson_number"), busy.school_class.name
                        )
                    }
                )

        attrs["year"] = year
        return attrs


class CopySerializer(serializers.Serializer):
    """
    Вход для /api/slots/copy/.

    Без `class_id` копируется расписание целиком — все классы владельца,
    чей учебный год задевает целевой период.
    """

    # имя class_id — из тела запроса; class в Python зарезервировано
    class_id = serializers.PrimaryKeyRelatedField(
        queryset=SchoolClass.objects.none(),
        source="school_class",
        required=False,
        allow_null=True,
    )
    source_start = serializers.DateField()
    source_end = serializers.DateField()
    target_start = serializers.DateField()
    target_end = serializers.DateField()
    mode = serializers.ChoiceField(choices=("replace", "merge"), default="merge")

    def get_fields(self):
        fields = super().get_fields()
        fields["class_id"].queryset = own_classes(self)
        return fields

    def validate(self, attrs):
        for start, end in (("source_start", "source_end"), ("target_start", "target_end")):
            if attrs[end] < attrs[start]:
                raise serializers.ValidationError(
                    {end: "Дата окончания раньше даты начала."}
                )
        return attrs


class PeriodSerializer(serializers.Serializer):
    """Границы периода для /api/slots/agenda/."""

    start = serializers.DateField()
    end = serializers.DateField()

    def validate(self, attrs):
        if attrs["end"] < attrs["start"]:
            raise serializers.ValidationError(
                {"end": "Дата окончания раньше даты начала."}
            )
        return attrs


class BulkDeleteSerializer(serializers.Serializer):
    """Вход для DELETE /api/slots/bulk/ — приходит параметрами запроса."""

    school_class = serializers.PrimaryKeyRelatedField(
        queryset=SchoolClass.objects.none()
    )
    start = serializers.DateField()
    end = serializers.DateField()
    only_regular = serializers.BooleanField(default=False)

    def get_fields(self):
        fields = super().get_fields()
        fields["school_class"].queryset = own_classes(self)
        return fields

    def validate(self, attrs):
        if attrs["end"] < attrs["start"]:
            raise serializers.ValidationError(
                {"end": "Дата окончания раньше даты начала."}
            )
        return attrs
