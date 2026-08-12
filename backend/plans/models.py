from django.core.exceptions import ValidationError
from django.db import models

from . import services


class PlanNode(models.Model):
    """
    Узел учебного плана: папка верхнего уровня или урок.

    Дерево ровно двухуровневое — папка внутри папки запрещена, см. `clean`.
    Сквозного номера у урока нет: его считает `services.number_lessons`.
    """

    school_class = models.ForeignKey(
        "schedule.SchoolClass",
        related_name="plan_nodes",
        on_delete=models.CASCADE,
        verbose_name="class",
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
        messages = {field: message for field, (_, message) in problems.items()}

        if self._position_taken():
            messages["position"] = "Another node already occupies this position."

        if messages:
            raise ValidationError(messages)

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
