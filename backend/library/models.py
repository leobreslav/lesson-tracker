from django.conf import settings
from django.db import models
from schedule.models import MAX_GRADE, MIN_GRADE
from django.core.validators import MaxValueValidator, MinValueValidator


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
        "grade",
        validators=[MinValueValidator(MIN_GRADE), MaxValueValidator(MAX_GRADE)],
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
        return self.rows.filter(is_header=False).count()


class PlanTemplateRow(models.Model):
    """
    One line of a template: a block header or a lesson.

    Flat, unlike `PlanNode`, and deliberately so. A plan tree is exactly two
    levels deep, which a flat ordered list with header markers expresses
    completely — it is the same shape the CSV import and export already use,
    and reusing it means the conversion between a plan and a template is the
    conversion the project already had.

    It carries the one limitation of that shape: a top-level lesson standing
    **after** a header cannot be told apart from a lesson inside it. The CSV
    format has always had that limit; taking a template from such a plan
    folds those lessons into the preceding block.
    """

    template = models.ForeignKey(
        PlanTemplate,
        related_name="rows",
        on_delete=models.CASCADE,
        verbose_name="template",
    )
    position = models.PositiveIntegerField("position", default=0)
    is_header = models.BooleanField("is a block header", default=False)
    title = models.CharField("title", max_length=300)
    note = models.TextField("note", blank=True)

    class Meta:
        verbose_name = "template row"
        verbose_name_plural = "template rows"
        ordering = ("position", "id")
        indexes = [
            models.Index(fields=("template", "position"), name="template_row_idx"),
        ]

    def __str__(self):
        return self.title
