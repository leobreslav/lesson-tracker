from calendars import services as calendar_services
from config.errors import Codes, api_error, error_payload
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
                message="A class with this name already exists in this year.",
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
                message="This class already has a lesson with this number on that day.",
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
        A lesson on a non-study day is allowed — catch-up days happen — but
        the answer says so, coded like an error so the UI can localise it.
        """
        day = calendar_services.resolve_day(
            obj.date, obj.year.weekend_days, obj.year.periods()
        )
        if day.is_study:
            return None

        label = calendar_services.STATUS_LABELS[day.status]
        note = f" «{day.title}»" if day.title else ""
        return error_payload(
            Codes.SLOT_NOT_STUDY_DAY,
            f"{obj.date.isoformat()} is a {label}{note}: the lesson falls outside study days.",
            date=obj.date.isoformat(),
            status=day.status,
            title=day.title,
        )

    def validate(self, attrs):
        def value(name):
            return attrs.get(name, getattr(self.instance, name, None))

        school_class = value("school_class")
        year = attrs.get("year") or school_class.year
        slot_date = value("date")

        if year != school_class.year:
            api_error(
                Codes.SLOT_YEAR_MISMATCH,
                "The lesson year must match the year of its class.",
                field="year",
            )

        if not year.start_date <= slot_date <= year.end_date:
            api_error(
                Codes.SLOT_OUTSIDE_YEAR,
                "The date is outside the school year "
                f"({year.start_date} — {year.end_date}).",
                field="date",
                start=str(year.start_date),
                end=str(year.end_date),
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
                api_error(
                    Codes.SLOT_NUMBER_TAKEN,
                    services.occupied_message(
                        slot_date, value("lesson_number"), busy.school_class.name
                    ),
                    field="lesson_number",
                    date=str(slot_date),
                    number=value("lesson_number"),
                    class_name=busy.school_class.name,
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
                api_error(
                    Codes.PERIOD_REVERSED,
                    "The end date is earlier than the start date.",
                    field=end,
                )
        return attrs


class PeriodSerializer(serializers.Serializer):
    """Границы периода для /api/slots/agenda/."""

    start = serializers.DateField()
    end = serializers.DateField()

    def validate(self, attrs):
        if attrs["end"] < attrs["start"]:
            api_error(
                Codes.PERIOD_REVERSED,
                "The end date is earlier than the start date.",
                field="end",
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
            api_error(
                Codes.PERIOD_REVERSED,
                "The end date is earlier than the start date.",
                field="end",
            )
        return attrs
