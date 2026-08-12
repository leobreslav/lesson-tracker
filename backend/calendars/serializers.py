from config.errors import Codes, api_error
from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from . import services
from .models import DayException, SchoolYear, Term


def own_years(serializer):
    """Only the requester's own years: someone else's cannot be referenced."""
    user = getattr(serializer.context.get("request"), "user", None)
    if user is None or not user.is_authenticated:
        return SchoolYear.objects.none()
    return SchoolYear.objects.filter(owner=user)


class DayExceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DayException
        fields = ("id", "year", "start_date", "end_date", "kind", "title")

    def get_fields(self):
        fields = super().get_fields()
        fields["year"].queryset = own_years(self)
        return fields

    def validate(self, attrs):
        def value(name):
            # a PATCH may send only some fields — take the rest from the object
            return attrs.get(name, getattr(self.instance, name, None))

        year = value("year")
        start_date = value("start_date")
        end_date = value("end_date")

        if end_date < start_date:
            api_error(
                Codes.EXCEPTION_DATES_REVERSED,
                "The end date is earlier than the start date.",
                field="end_date",
            )

        period = services.Period(
            start_date=start_date,
            end_date=end_date,
            kind=value("kind"),
            id=self.instance.pk if self.instance else None,
        )

        if not services.is_within(period, year.start_date, year.end_date):
            api_error(
                Codes.EXCEPTION_OUTSIDE_YEAR,
                "The period must fit inside the school year "
                f"({year.start_date} — {year.end_date}).",
                start=str(year.start_date),
                end=str(year.end_date),
            )

        # duplicate titles are fine: two «Holidays» on different dates are
        # normal, only overlapping dates count as a conflict
        conflicts = services.find_conflicts(period, year.periods())
        if conflicts:
            first = conflicts[0]
            api_error(
                Codes.EXCEPTION_OVERLAP,
                f"These dates are already taken by «{first.title or 'untitled'}» "
                f"({first.start_date} — {first.end_date}).",
                title=first.title,
                kind=first.kind,
                start=str(first.start_date),
                end=str(first.end_date),
            )

        return attrs


class TermSerializer(serializers.ModelSerializer):
    class Meta:
        model = Term
        fields = ("id", "year", "name", "start_date", "end_date", "position")

    def get_fields(self):
        fields = super().get_fields()
        fields["year"].queryset = own_years(self)
        return fields

    def validate(self, attrs):
        def value(name):
            return attrs.get(name, getattr(self.instance, name, None))

        year = value("year")
        start_date, end_date = value("start_date"), value("end_date")

        if end_date < start_date:
            api_error(
                Codes.TERM_DATES_REVERSED,
                "The end date is earlier than the start date.",
                field="end_date",
            )

        if not (year.start_date <= start_date and end_date <= year.end_date):
            api_error(
                Codes.TERM_OUTSIDE_YEAR,
                "The term must fit inside the school year "
                f"({year.start_date} — {year.end_date}).",
                start=str(year.start_date),
                end=str(year.end_date),
            )

        # the overlap check lives on the model so the admin gets it too
        probe = Term(
            pk=self.instance.pk if self.instance else None,
            year=year,
            start_date=start_date,
            end_date=end_date,
        )
        busy = probe.overlapping()
        if busy is not None:
            api_error(
                Codes.TERM_OVERLAP,
                f"Overlaps with the term «{busy.name}» "
                f"({busy.start_date} — {busy.end_date}).",
                name=busy.name,
                start=str(busy.start_date),
                end=str(busy.end_date),
            )

        return attrs


class SchoolYearSerializer(serializers.ModelSerializer):
    # the owner comes from the request, never from the body
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
            # unique_together with owner: DRF cannot check a field that is not
            # in the request body, and a duplicate name would blow up with 500
            UniqueTogetherValidator(
                queryset=SchoolYear.objects.all(),
                fields=("owner", "name"),
                message="A school year with this name already exists.",
            ),
        ]

    def validate_weekend_days(self, value):
        for weekday in value:
            if weekday not in range(7):
                api_error(
                    Codes.YEAR_WEEKEND_INVALID,
                    "Weekday numbers run from 0 (Monday) to 6 (Sunday).",
                    field="weekend_days",
                )
        if len(set(value)) == 7:
            api_error(
                Codes.YEAR_WEEKEND_FULL,
                "Every weekday cannot be a day off.",
                field="weekend_days",
            )
        return sorted(set(value))

    def validate(self, attrs):
        def value(name):
            return attrs.get(name, getattr(self.instance, name, None))

        start_date = value("start_date")
        end_date = value("end_date")

        if end_date < start_date:
            api_error(
                Codes.YEAR_DATES_REVERSED,
                "The end date is earlier than the start date.",
                field="end_date",
            )

        if self.instance is not None:
            # narrowing the year could cut off markup that already exists
            outside = [
                period
                for period in self.instance.periods()
                if not services.is_within(period, start_date, end_date)
            ]
            if outside:
                api_error(
                    Codes.YEAR_SHRINK_CUTS_EXCEPTIONS,
                    "The new boundaries cut off existing markup, for example "
                    f"{outside[0].start_date} — {outside[0].end_date}. "
                    "Remove it first.",
                    start=str(outside[0].start_date),
                    end=str(outside[0].end_date),
                )

        return attrs
