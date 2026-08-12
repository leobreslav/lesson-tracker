from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from . import services

# уроков в дне: больше десятого номера в школьном расписании не бывает
MAX_LESSON_NUMBER = 10


class Course(models.Model):
    """
    What somebody teaches: a group and a subject together, «9B Algebra».

    The course belongs to the school and is created by its administrators —
    a teacher picks from the list rather than inventing their own entry, or
    two colleagues teaching the same group would end up with two courses
    nobody can compare.

    The link to a year is deliberate: next year 9B becomes 10B, and that is a
    different course with its own load.
    """

    school = models.ForeignKey(
        "schools.School",
        related_name="courses",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    # deleting a year takes its courses with it; lesson slots and plan rows
    # hang off the course under PROTECT, so a course in use cannot vanish
    year = models.ForeignKey(
        "calendars.SchoolYear",
        related_name="courses",
        on_delete=models.CASCADE,
        verbose_name="school year",
    )
    name = models.CharField("name", max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "course"
        verbose_name_plural = "courses"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("school", "year", "name"), name="unique_course_name_per_year"
            ),
        ]

    def __str__(self):
        return self.name


class MasterSlot(models.Model):
    """
    A lesson in the school-wide timetable: who teaches what, and when.

    Kept by administrators and read by everybody in the school. A teacher may
    copy their own rows into their personal schedule **once** — after that the
    copies are ordinary lessons of theirs and know nothing about this table.
    Changing the timetable later does not reach them, and that is deliberate:
    a schedule somebody has already annotated must not be rewritten under
    them by an edit elsewhere.

    `teacher` is nullable because the grid is usually built before the load
    is shared out. A row without a teacher is a plan, not an assignment, and
    it is copied to nobody.
    """

    school = models.ForeignKey(
        "schools.School",
        related_name="master_slots",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    year = models.ForeignKey(
        "calendars.SchoolYear",
        related_name="master_slots",
        on_delete=models.CASCADE,
        verbose_name="school year",
    )
    course = models.ForeignKey(
        Course,
        related_name="master_slots",
        on_delete=models.CASCADE,
        verbose_name="course",
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="master_slots",
        null=True,
        blank=True,
        # the row survives the person: losing a teacher must not silently
        # delete the school's timetable
        on_delete=models.SET_NULL,
        verbose_name="teacher",
    )
    date = models.DateField("date")
    lesson_number = models.PositiveSmallIntegerField(
        "lesson number",
        validators=[MinValueValidator(1), MaxValueValidator(MAX_LESSON_NUMBER)],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "school timetable lesson"
        verbose_name_plural = "school timetable"
        ordering = ("date", "lesson_number")
        indexes = [
            models.Index(
                fields=("school", "year", "teacher", "date"),
                name="master_teacher_date_idx",
            ),
        ]
        constraints = [
            # a course is a group and a subject together, so it cannot sit in
            # two rooms at once — whoever ends up teaching it
            models.UniqueConstraint(
                fields=("course", "date", "lesson_number"),
                name="unique_master_slot_per_course_day",
            ),
            models.CheckConstraint(
                condition=models.Q(lesson_number__gte=1)
                & models.Q(lesson_number__lte=MAX_LESSON_NUMBER),
                name="master_lesson_number_in_range",
            ),
        ]

    def __str__(self):
        return f"{self.course} {self.date} №{self.lesson_number}"

    @classmethod
    def find_conflict(cls, *, teacher_id, date, lesson_number, exclude_pk=None):
        """
        The same teacher already standing somewhere at that hour.

        Not covered by unique_together, whose key is the course: two
        different courses on one number is exactly the mistake to catch.
        A row with no teacher conflicts with nothing — nobody is there yet.
        """
        if teacher_id is None:
            return None

        queryset = cls.objects.filter(
            teacher_id=teacher_id, date=date, lesson_number=lesson_number
        ).select_related("course")

        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)

        return queryset.first()

    def clean(self):
        super().clean()

        if self.course_id and self.school_id and self.course.school_id != self.school_id:
            raise ValidationError({"course": "The course belongs to another school."})

        if self.teacher_id and self.school_id:
            if self.teacher.school_id != self.school_id:
                raise ValidationError(
                    {"teacher": "The teacher belongs to another school."}
                )

        if not (self.date and self.lesson_number):
            return

        busy = self.find_conflict(
            teacher_id=self.teacher_id,
            date=self.date,
            lesson_number=self.lesson_number,
            exclude_pk=self.pk,
        )
        if busy is not None:
            raise ValidationError(
                {
                    "lesson_number": services.occupied_message(
                        self.date, self.lesson_number, busy.course.name
                    )
                }
            )


class LessonSlot(models.Model):
    """
    One lesson of one teacher in one course on one day.

    There is no separate "timetable" entity: a teacher's schedule for the year
    is every slot of theirs inside the year's boundaries. There is no lesson
    kind either, only two flags: a regular lesson has both False, a cancelled
    one has is_cancelled, an unplanned one (a substitution, a club) has
    is_extra. The combination is allowed — an extra lesson can be cancelled.

    The slot is personal. Two teachers may share a course and still keep
    completely separate schedules inside it.
    """

    year = models.ForeignKey(
        "calendars.SchoolYear",
        related_name="slots",
        on_delete=models.CASCADE,
        verbose_name="school year",
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="slots",
        on_delete=models.CASCADE,
        verbose_name="teacher",
    )
    course = models.ForeignKey(
        Course,
        related_name="slots",
        # PROTECT: an administrator must not wipe somebody's schedule by
        # deleting a course — the answer explains what is in the way
        on_delete=models.PROTECT,
        verbose_name="course",
    )
    date = models.DateField("date")
    lesson_number = models.PositiveSmallIntegerField(
        "lesson number",
        validators=[MinValueValidator(1), MaxValueValidator(MAX_LESSON_NUMBER)],
    )
    is_cancelled = models.BooleanField("cancelled", default=False)
    is_extra = models.BooleanField("extra lesson", default=False)
    reason = models.CharField("reason", max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "lesson slot"
        verbose_name_plural = "lesson slots"
        ordering = ("date", "lesson_number")
        indexes = [
            models.Index(fields=("teacher", "date"), name="slot_teacher_date_idx"),
            models.Index(fields=("course", "date"), name="slot_course_date_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("teacher", "course", "date", "lesson_number"),
                name="unique_slot_per_teacher_course_day",
            ),
            models.CheckConstraint(
                condition=models.Q(lesson_number__gte=1)
                & models.Q(lesson_number__lte=MAX_LESSON_NUMBER),
                name="lesson_number_in_range",
            ),
        ]

    def __str__(self):
        return f"{self.course} {self.date} №{self.lesson_number}"

    @property
    def is_regular(self) -> bool:
        """Обычный урок расписания — только такие копируются и чистятся оптом."""
        return not self.is_extra and not self.is_cancelled

    @classmethod
    def find_conflict(cls, *, teacher_id, year, date, lesson_number, exclude_pk=None):
        """
        The teacher's own lesson already holding that number that day.

        Physically nobody teaches two courses at once, and unique_together
        does not catch it: its key includes the course. A cancelled lesson
        frees the slot — another course can take it.
        """
        queryset = cls.objects.filter(
            teacher_id=teacher_id,
            year=year,
            date=date,
            lesson_number=lesson_number,
            is_cancelled=False,
        ).select_related("course")

        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)

        return queryset.first()

    def conflict(self):
        if self.is_cancelled or not (self.year_id and self.course_id and self.teacher_id):
            return None
        if self.date is None or self.lesson_number is None:
            return None

        return self.find_conflict(
            teacher_id=self.teacher_id,
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
                        self.date, self.lesson_number, busy.course.name
                    )
                }
            )
