from django.conf import settings
from django.contrib.postgres.fields import ArrayField
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
            self.start_date, self.end_date, self.weekend_days, self.periods()
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
