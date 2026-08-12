from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models

from . import services


def default_weekend_days():
    return list(services.DEFAULT_WEEKEND_DAYS)


class SchoolYear(models.Model):
    """Учебный год одного учителя: границы периода и разметка календаря."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="school_years",
        on_delete=models.CASCADE,
        verbose_name="владелец",
    )
    name = models.CharField("название", max_length=64)
    start_date = models.DateField("начало")
    end_date = models.DateField("конец")
    # номера как в date.weekday(): понедельник — 0, воскресенье — 6
    weekend_days = ArrayField(
        models.PositiveSmallIntegerField(choices=services.WEEKDAY_CHOICES),
        default=default_weekend_days,
        blank=True,
        verbose_name="выходные дни недели",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "учебный год"
        verbose_name_plural = "учебные годы"
        ordering = ("-start_date", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "name"), name="unique_school_year_name_per_owner"
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="school_year_dates_ordered",
            ),
        ]

    def __str__(self):
        return self.name

    def periods(self) -> list[services.Period]:
        """Исключения года в виде структур для calendars.services."""
        return [exception.as_period() for exception in self.exceptions.all()]

    def build_days(self) -> list[services.Day]:
        return services.build_days(
            self.start_date,
            self.end_date,
            self.weekend_days,
            self.periods(),
            self.terms.all(),
        )

    def term_for_date(self, day):
        """Терм, накрывающий дату, или None — мост к services.find_term."""
        return services.find_term(day, self.terms.all())


class Term(models.Model):
    """
    Четверть или семестр.

    Термы не обязаны покрывать год целиком: дни между ними (каникулы)
    не входят ни в один терм, и это нормальное состояние.
    """

    year = models.ForeignKey(
        SchoolYear,
        related_name="terms",
        on_delete=models.CASCADE,
        verbose_name="учебный год",
    )
    name = models.CharField("название", max_length=100)
    start_date = models.DateField("начало")
    end_date = models.DateField("конец")
    position = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        verbose_name = "терм"
        verbose_name_plural = "термы"
        ordering = ("start_date", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="term_dates_ordered",
            ),
        ]

    def __str__(self):
        return self.name

    def overlapping(self):
        """Терм того же года, пересекающийся с этим по датам."""
        return (
            Term.objects.filter(
                year_id=self.year_id,
                start_date__lte=self.end_date,
                end_date__gte=self.start_date,
            )
            .exclude(pk=self.pk)
            .first()
        )

    def clean(self):
        super().clean()

        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Дата окончания раньше даты начала."})

        if not (self.year_id and self.start_date and self.end_date):
            return

        if not (
            self.year.start_date <= self.start_date
            and self.end_date <= self.year.end_date
        ):
            raise ValidationError(
                "Терм должен помещаться в границы учебного года "
                f"({self.year.start_date} — {self.year.end_date})."
            )

        busy = self.overlapping()
        if busy is not None:
            raise ValidationError(
                f"Пересекается с термом «{busy.name}» "
                f"({busy.start_date} — {busy.end_date})."
            )


class DayException(models.Model):
    """Отрезок дат, размеченный не так, как обычная неделя."""

    class Kind(models.TextChoices):
        HOLIDAY = services.KIND_HOLIDAY, "праздник"
        VACATION = services.KIND_VACATION, "каникулы"
        WORKDAY = services.KIND_WORKDAY, "рабочий день"

    year = models.ForeignKey(
        SchoolYear,
        related_name="exceptions",
        on_delete=models.CASCADE,
        verbose_name="учебный год",
    )
    start_date = models.DateField("начало")
    end_date = models.DateField("конец")
    kind = models.CharField("вид", max_length=16, choices=Kind)
    title = models.CharField("название", max_length=120, blank=True)

    class Meta:
        verbose_name = "исключение"
        verbose_name_plural = "исключения"
        ordering = ("start_date", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="day_exception_dates_ordered",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.start_date}–{self.end_date}"

    def as_period(self) -> services.Period:
        return services.Period(
            start_date=self.start_date,
            end_date=self.end_date,
            kind=self.kind,
            title=self.title,
            id=self.pk,
        )
