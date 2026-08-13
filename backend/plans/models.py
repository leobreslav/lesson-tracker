from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from . import services
from .content import CONTENT_FIELDS, LessonContent, content_problems


class PlanNode(LessonContent):
    """
    A node of a lesson plan: a top-level section or a lesson.

    The tree is exactly two levels deep — a section inside a section is
    refused, see `clean`. A lesson carries no stored number:
    `services.number_lessons` counts it by walking the tree.

    The plan is personal, like the schedule: two teachers sharing a course
    keep their own plans inside it. Its content (see `LessonContent`) is
    personal for the same reason: a colleague teaching the same course writes
    their own lesson, even under the same title.
    """

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="plan_nodes",
        on_delete=models.CASCADE,
        verbose_name="teacher",
    )
    course = models.ForeignKey(
        "schedule.Course",
        related_name="plan_nodes",
        # PROTECT, like the slots: deleting a course must not take somebody's
        # plan down with it
        on_delete=models.PROTECT,
        verbose_name="course",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE,
        verbose_name="section",
    )
    position = models.PositiveIntegerField("position", default=0)
    is_section = models.BooleanField("is a section", default=False)
    title = models.CharField("title", max_length=200)
    note = models.TextField("note", blank=True)

    class Meta:
        verbose_name = "plan node"
        verbose_name_plural = "lesson plan"
        ordering = ("position", "id")
        indexes = [
            models.Index(
                fields=("teacher", "course", "parent", "position"),
                name="plan_level_idx",
            ),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()

        problems = services.structure_problems(
            course_id=self.course_id,
            parent=self.parent,
            is_section=self.is_section,
        )
        messages = {field: message for field, (_, message) in problems.items()}
        messages.update(
            content_problems(
                is_section=self.is_section,
                values={field: getattr(self, field) for field in CONTENT_FIELDS},
            )
        )

        if self._position_taken():
            messages["position"] = "Another node already occupies this position."

        if messages:
            raise ValidationError(messages)

    def _position_taken(self) -> bool:
        if self.position is None or self.course_id is None:
            return False

        return (
            PlanNode.objects.filter(
                teacher_id=self.teacher_id,
                course_id=self.course_id,
                parent_id=self.parent_id,
                position=self.position,
            )
            .exclude(pk=self.pk)
            .exists()
        )


class PlanBaseline(models.Model):
    """
    Снимок плана на момент фиксации — то, с чем сравнивают потом.

    Нужен ровно для одного вопроса: план разросся или его пришлось
    сократить? Без эталона на этот вопрос ответить нечем — план меняется
    каждый день, и «стало 47 уроков» само по себе ничего не значит.

    Содержание уроков и вложения сюда не копируются: эталон про
    **структуру** — сколько уроков, в каких темах и в каком порядке. Копия
    содержания удвоила бы хранение ради вопроса, которого никто не задаёт.

    На пару (учитель, курс) снимок один: перефиксация заменяет прежний.
    История версий тут была бы отдельной функцией со своим экраном, а нужен
    ответ «относительно чего считаем» — и он один.
    """

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="plan_baselines",
        on_delete=models.CASCADE,
        verbose_name="teacher",
    )
    course = models.ForeignKey(
        "schedule.Course",
        related_name="plan_baselines",
        on_delete=models.CASCADE,
        verbose_name="course",
    )
    created_at = models.DateTimeField("fixed at", auto_now_add=True)

    class Meta:
        verbose_name = "plan baseline"
        verbose_name_plural = "plan baselines"
        constraints = [
            models.UniqueConstraint(
                fields=("teacher", "course"), name="one_baseline_per_plan"
            ),
        ]

    def __str__(self):
        return f"{self.course} — {self.created_at:%Y-%m-%d}"


class PlanBaselineRow(models.Model):
    """
    Строка снимка: плоский список, как у шаблона библиотеки.

    `node_id` — тот узел плана, с которого строку сняли, обычным числом, а
    не связью: узел могут удалить, и именно это удаление снимок и должен
    пережить, чтобы о нём рассказать.
    """

    baseline = models.ForeignKey(
        PlanBaseline,
        related_name="rows",
        on_delete=models.CASCADE,
        verbose_name="baseline",
    )
    position = models.PositiveIntegerField("position")
    is_section = models.BooleanField("section", default=False)
    title = models.CharField("title", max_length=200)
    node_id = models.PositiveIntegerField("plan node id", null=True, blank=True)

    class Meta:
        verbose_name = "plan baseline row"
        verbose_name_plural = "plan baseline rows"
        ordering = ("position", "id")

    def __str__(self):
        return self.title
