from django.core.exceptions import ValidationError
from django.db import models

from . import services


class PlanNode(models.Model):
    """
    Узел учебного плана: папка верхнего уровня или урок.

    Дерево ровно двухуровневое — папка внутри папки запрещена, см. `clean`.
    Сквозного номера у урока нет: его считает `services.number_lessons`.
    """

    class Kind(models.TextChoices):
        LESSON = services.KIND_LESSON, "урок"
        CONTROL = services.KIND_CONTROL, "контрольная"
        RESERVE = services.KIND_RESERVE, "резерв"

    school_class = models.ForeignKey(
        "schedule.SchoolClass",
        related_name="plan_nodes",
        on_delete=models.CASCADE,
        verbose_name="класс",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE,
        verbose_name="папка",
    )
    position = models.PositiveIntegerField("порядок", default=0)
    is_section = models.BooleanField("папка", default=False)
    title = models.CharField("название", max_length=200)
    # у папки вид не используется
    kind = models.CharField(
        "вид", max_length=16, choices=Kind, default=Kind.LESSON
    )
    note = models.TextField("заметка", blank=True)

    class Meta:
        verbose_name = "узел плана"
        verbose_name_plural = "учебный план"
        ordering = ("position", "id")
        indexes = [
            models.Index(
                fields=("school_class", "parent", "position"), name="plan_level_idx"
            ),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()

        problems = services.structure_problems(
            school_class_id=self.school_class_id,
            parent=self.parent,
            is_section=self.is_section,
        )

        if self._position_taken():
            problems["position"] = "На этом месте уровня уже стоит другой узел."

        if problems:
            raise ValidationError(problems)

    def _position_taken(self) -> bool:
        if self.position is None or self.school_class_id is None:
            return False

        return (
            PlanNode.objects.filter(
                school_class_id=self.school_class_id,
                parent_id=self.parent_id,
                position=self.position,
            )
            .exclude(pk=self.pk)
            .exists()
        )
