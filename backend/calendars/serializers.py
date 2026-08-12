from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from . import services
from .models import DayException, SchoolYear


class DayExceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DayException
        fields = ("id", "year", "start_date", "end_date", "kind", "title")

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        # подставить чужой год нельзя: выбор ограничен годами владельца
        user = getattr(request, "user", None)
        fields["year"].queryset = (
            SchoolYear.objects.filter(owner=user)
            if user is not None and user.is_authenticated
            else SchoolYear.objects.none()
        )
        return fields

    def validate(self, attrs):
        def value(name):
            # PATCH может прислать часть полей — остальные берём у объекта
            return attrs.get(name, getattr(self.instance, name, None))

        year = value("year")
        start_date = value("start_date")
        end_date = value("end_date")

        if end_date < start_date:
            raise serializers.ValidationError(
                {"end_date": "Дата окончания раньше даты начала."}
            )

        period = services.Period(
            start_date=start_date,
            end_date=end_date,
            kind=value("kind"),
            id=self.instance.pk if self.instance else None,
        )

        if not services.is_within(period, year.start_date, year.end_date):
            raise serializers.ValidationError(
                "Исключение должно попадать в границы учебного года "
                f"({year.start_date} — {year.end_date})."
            )

        conflicts = services.find_conflicts(period, year.periods())
        if conflicts:
            first = conflicts[0]
            raise serializers.ValidationError(
                f"Пересекается с исключением того же вида: "
                f"{first.title or 'без названия'} ({first.start_date} — {first.end_date})."
            )

        return attrs


class SchoolYearSerializer(serializers.ModelSerializer):
    # владелец берётся из запроса, а не из тела: чужой год не подсунуть
    owner = serializers.HiddenField(default=serializers.CurrentUserDefault())
    exceptions = DayExceptionSerializer(many=True, read_only=True)

    class Meta:
        model = SchoolYear
        fields = (
            "id",
            "owner",
            "name",
            "start_date",
            "end_date",
            "weekend_days",
            "exceptions",
        )
        validators = [
            # unique_together с owner: без явного валидатора DRF не проверит
            # поле, которого нет в теле запроса, и запрос упадёт с 500
            UniqueTogetherValidator(
                queryset=SchoolYear.objects.all(),
                fields=("owner", "name"),
                message="Учебный год с таким названием уже есть.",
            ),
        ]

    def validate_weekend_days(self, value):
        for weekday in value:
            if weekday not in range(7):
                raise serializers.ValidationError(
                    "Номер дня недели должен быть от 0 (понедельник) до 6 (воскресенье)."
                )
        if len(set(value)) == 7:
            raise serializers.ValidationError("Все дни недели выходными быть не могут.")
        return sorted(set(value))

    def validate(self, attrs):
        def value(name):
            return attrs.get(name, getattr(self.instance, name, None))

        start_date = value("start_date")
        end_date = value("end_date")

        if end_date < start_date:
            raise serializers.ValidationError(
                {"end_date": "Дата окончания раньше даты начала."}
            )

        if self.instance is not None:
            # сузили год — уже размеченные исключения могли остаться снаружи
            outside = [
                period
                for period in self.instance.periods()
                if not services.is_within(period, start_date, end_date)
            ]
            if outside:
                raise serializers.ValidationError(
                    "Новые границы года отрезают уже размеченные исключения "
                    f"(например, {outside[0].start_date} — {outside[0].end_date}). "
                    "Сначала удалите их."
                )

        return attrs
