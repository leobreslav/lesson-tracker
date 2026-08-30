from django.conf import settings
from django.db import models
from schedule.models import MIN_GRADE
from django.core.validators import MinValueValidator


class PlanTemplate(models.Model):
    """
    A lesson plan somebody put on the shelf for colleagues to take.

    Not tied to a school year on purpose: an algebra plan for grade 9 does
    not expire in September. It is tied to a subject and a grade, because
    that is what a colleague searches by.

    Taking a copy is a copy — the same rule as the school timetable. What
    lands in a course is that teacher's own plan; later edits to the
    template do not follow it, and edits to the plan do not climb back.

    A draft is private to its author. Publishing is the moment it becomes
    the school's, and only the author decides when that is.
    """

    school = models.ForeignKey(
        "schools.School",
        related_name="plan_templates",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    subject = models.ForeignKey(
        "schedule.Subject",
        related_name="plan_templates",
        on_delete=models.PROTECT,
        verbose_name="subject",
    )
    grade = models.PositiveSmallIntegerField(
        # the year of study, not a foreign key: a plan for the ninth year is
        # a plan for the ninth year whatever the school writes on the door,
        # and the filter needs one comparable number
        "year of study",
        validators=[MinValueValidator(MIN_GRADE)],
    )
    title = models.CharField("title", max_length=200)
    description = models.TextField("description", blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="plan_templates",
        null=True,
        # the shelf outlives the person: losing an account must not delete
        # the plans colleagues are already using
        on_delete=models.SET_NULL,
        verbose_name="author",
    )
    is_published = models.BooleanField("published", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "plan template"
        verbose_name_plural = "plan library"
        ordering = ("subject__name", "grade", "title")

    def __str__(self):
        return f"{self.title} ({self.subject}, {self.grade})"

    @property
    def lesson_count(self) -> int:
        return self.nodes.filter(is_section=False).count()

