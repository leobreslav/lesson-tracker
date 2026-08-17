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

    **План принадлежит курсу, а не учителю** — в отличие от расписания.
    Расписание отвечает на вопрос «когда я веду», и у двух человек оно
    законно разное; план отвечает на вопрос «что это за курс», и ответ у
    курса один: его утверждает методист, он же уезжает в библиотеку.

    Личным он был раньше, по аналогии с расписанием, и аналогия подвела
    дважды. Двое ведущих писали две программы под одним именем, и никто не
    видел расхождения. А главное — при смене ведущего строки оставались
    висеть на ушедшем, и новый учитель открывал пустой план, пока рядом в
    базе лежала вся прошлогодняя работа. Теперь ведущий у курса один
    (`CourseAssignment`), а план переживает его смену.

    Содержание урока (см. `LessonContent`) переехало вместе с планом и тоже
    принадлежит курсу.
    """

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
                fields=("course", "parent", "position"), name="plan_level_idx"
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
                course_id=self.course_id,
                parent_id=self.parent_id,
                position=self.position,
            )
            .exclude(pk=self.pk)
            .exists()
        )


class PlanBaseline(models.Model):
    """
    Запрос на утверждение, а после утверждения — снимок принятого плана.

    Снимок снимается **при утверждении**, а не при отправке: эталоном
    становится ровно то, что приняли. Методист открывает текущую версию
    плана, а не ту, что была отправлена, — правки после отправки запрос не
    отзывают, и утверждает он то, что видит сейчас.

    Содержание уроков и вложения сюда не копируются: эталон про
    **структуру** — сколько уроков, в каких темах и в каком порядке. Копия
    содержания удвоила бы хранение ради вопроса, которого никто не задаёт.

    Снимков у плана несколько: утверждённый продолжает действовать, пока
    новый лежит на утверждении, — иначе отправка новой версии стирала бы
    точку отсчёта, относительно которой считается расхождение.

    У самого плана состояния нет: учитель правит его свободно, состояние
    есть только у запроса. Правки после отправки ничего не отзывают —
    методист открывает текущую версию плана и утверждает то, что видит.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "waiting for approval"
        APPROVED = "approved", "approved"
        RETURNED = "returned", "returned with a comment"

    course = models.ForeignKey(
        "schedule.Course",
        related_name="plan_baselines",
        on_delete=models.CASCADE,
        verbose_name="course",
    )
    # кто отправил — история, а не владение: эталон принадлежит курсу, и
    # смена ведущего учителя его не отменяет
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="plan_baselines",
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="submitted by",
    )
    created_at = models.DateTimeField("snapshot taken at", auto_now_add=True)
    status = models.CharField(
        "status", max_length=16, choices=Status, default=Status.PENDING
    )
    submitted_at = models.DateTimeField("submitted at", null=True, blank=True)
    approved_at = models.DateTimeField("approved at", null=True, blank=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="plans_to_review",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="reviewer",
    )
    comment = models.TextField("comment", blank=True)
    # сколько часов было у курса в момент утверждения. Без этого числа
    # «почему резерв упал на четыре» не ответить: резерв это `слоты минус
    # уроки`, и подвинуть его могут обе стороны, а какая именно — видно
    # только в сравнении с точкой отсчёта
    slots_total = models.PositiveIntegerField(
        "hours at approval", null=True, blank=True
    )

    class Meta:
        verbose_name = "plan baseline"
        verbose_name_plural = "plan baselines"
        ordering = ("-created_at",)
        indexes = [
            # ровно по этой паре ходят обе выборки — утверждённый эталон и
            # висящий запрос, — и ходят пачками: главная и экран методиста
            # спрашивают их сразу по всем курсам
            models.Index(
                fields=("course", "status"), name="baseline_owner_status_idx"
            )
        ]

    def __str__(self):
        return f"{self.course} — {self.created_at:%Y-%m-%d} ({self.status})"

    @property
    def self_approved(self) -> bool:
        """Методист утвердил собственный план — это законно, но помечается."""
        return (
            self.status == self.Status.APPROVED
            and self.reviewer_id is not None
            and self.reviewer_id == self.submitted_by_id
        )


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
    # отпечаток содержания на момент снимка: само содержание в эталон не
    # кладётся, а факт правки показать надо. Пусто у тем и у снимков,
    # снятых до того, как отпечаток завели, — тогда про содержание молчим
    content_hash = models.CharField("content hash", max_length=32, blank=True)

    class Meta:
        verbose_name = "plan baseline row"
        verbose_name_plural = "plan baseline rows"
        ordering = ("position", "id")

    def __str__(self):
        return self.title
