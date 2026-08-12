from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from . import services

# уроков в дне: больше десятого номера в школьном расписании не бывает
MAX_LESSON_NUMBER = 10


class SchoolClass(models.Model):
    """
    Класс учителя в конкретном учебном году.

    Привязка к году намеренная: в следующем году 9Б становится 10Б, и это
    другой объект со своей нагрузкой. Модель минимальная, но полноценная —
    к ней будут цепляться слоты расписания и, возможно, список учеников.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="classes",
        on_delete=models.CASCADE,
        verbose_name="владелец",
    )
    # снос учебного года уносит и его классы; будущие слоты расписания
    # точно так же вешаются на класс через on_delete=CASCADE
    year = models.ForeignKey(
        "calendars.SchoolYear",
        related_name="classes",
        on_delete=models.CASCADE,
        verbose_name="учебный год",
    )
    name = models.CharField("название", max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "класс"
        verbose_name_plural = "классы"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "year", "name"), name="unique_class_name_per_year"
            ),
        ]

    def __str__(self):
        return self.name


class LessonSlot(models.Model):
    """
    Один урок класса в конкретный день.

    Отдельной сущности «расписание» нет: расписание класса на год — это все
    его слоты внутри границ года. Вида урока тоже нет, только два флага:
    обычный урок — оба False, отменённый — is_cancelled, внезапный (замена,
    дополнительное занятие) — is_extra. Комбинация допустима: отменить можно
    и дополнительный урок.
    """

    year = models.ForeignKey(
        "calendars.SchoolYear",
        related_name="slots",
        on_delete=models.CASCADE,
        verbose_name="учебный год",
    )
    school_class = models.ForeignKey(
        SchoolClass,
        related_name="slots",
        on_delete=models.CASCADE,
        verbose_name="класс",
    )
    date = models.DateField("дата")
    lesson_number = models.PositiveSmallIntegerField(
        "номер урока",
        validators=[MinValueValidator(1), MaxValueValidator(MAX_LESSON_NUMBER)],
    )
    is_cancelled = models.BooleanField("отменён", default=False)
    is_extra = models.BooleanField("сверх расписания", default=False)
    reason = models.CharField("причина", max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "урок"
        verbose_name_plural = "уроки"
        ordering = ("date", "lesson_number")
        indexes = [
            models.Index(fields=("school_class", "date"), name="slot_class_date_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("school_class", "date", "lesson_number"),
                name="unique_slot_per_class_day",
            ),
            models.CheckConstraint(
                condition=models.Q(lesson_number__gte=1)
                & models.Q(lesson_number__lte=MAX_LESSON_NUMBER),
                name="lesson_number_in_range",
            ),
        ]

    def __str__(self):
        return f"{self.school_class} {self.date} №{self.lesson_number}"

    @property
    def is_regular(self) -> bool:
        """Обычный урок расписания — только такие копируются и чистятся оптом."""
        return not self.is_extra and not self.is_cancelled

    @classmethod
    def find_conflict(cls, *, year, date, lesson_number, exclude_pk=None):
        """
        Урок владельца, уже занимающий этот номер в этот день.

        Физически учитель не ведёт два класса одновременно, а
        unique_together этого не ловит: там ключ включает класс. Отменённые
        уроки место не занимают — их можно перекрыть другим классом.
        """
        queryset = cls.objects.filter(
            school_class__owner_id=year.owner_id,
            year=year,
            date=date,
            lesson_number=lesson_number,
            is_cancelled=False,
        ).select_related("school_class")

        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)

        return queryset.first()

    def conflict(self):
        if self.is_cancelled or not (self.year_id and self.school_class_id):
            return None
        if self.date is None or self.lesson_number is None:
            return None

        return self.find_conflict(
            year=self.year,
            date=self.date,
            lesson_number=self.lesson_number,
            exclude_pk=self.pk,
        )

    def clean(self):
        super().clean()

        busy = self.conflict()
        if busy is not None:
            raise ValidationError(
                {
                    "lesson_number": services.occupied_message(
                        self.date, self.lesson_number, busy.school_class.name
                    )
                }
            )
