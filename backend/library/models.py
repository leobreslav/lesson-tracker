from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from schedule.models import MIN_GRADE
from django.core.validators import MaxValueValidator, MinValueValidator
from plans.content import CONTENT_FIELDS, LessonContent, content_problems


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
    #: Этот шаблон автор **ведёт**; остальные его шаблоны — снимки.
    #:
    #: Пометки не было, а кнопка «Обновить шаблон» была: клиент искал «мой
    #: шаблон с тем же предметом и той же параллелью» и обновлял первый
    #: попавшийся. Список отсортирован по названию, значит «первый» означало
    #: «раньше по алфавиту», и у человека с черновиком и опубликованным по
    #: одному предмету обновление молча уходило не туда.
    #:
    #: Та же болезнь, что была у раскладки: позиция вместо записи. И лечится
    #: тем же — записью; запись сильнее догадки.
    #:
    #: Ключ поиска при этом остался прежним — автор, предмет, параллель, — и
    #: это не лень. Ссылка на курс тут не годится вовсе: курс привязан к
    #: учебному году, в сентябре «9Б Алгебра» — уже другая запись, а шаблон к
    #: году намеренно не привязан. Связь с курсом протухала бы каждый
    #: сентябрь, и полка обрастала бы дублями по одному в год.
    #:
    #: Снято — значит **снимок**: его не перезапишет ничто, потому что
    #: «Обновить» бьёт только по живому. Отдельного поля «снимок» поэтому
    #: нет, оно получается само.
    is_live = models.BooleanField("kept up to date by its author", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "plan template"
        verbose_name_plural = "plan library"
        ordering = ("subject__name", "grade", "title")
        constraints = [
            # Двусмысленность «какой из них обновлять» ловится **схемой**, а
            # не проверкой во вьюхе: проверку обходит любой второй путь к
            # записи, а на неё здесь опирается кнопка, которая переписывает
            # чужую работу.
            #
            # Частичный индекс, а не обычный: снимков по одному предмету и
            # параллели может лежать сколько угодно, ограничен только живой.
            # Автор без учётки (`SET_NULL`) под ограничение не попадает —
            # вести шаблон некому, и NULL'ы в индексе не сравниваются.
            models.UniqueConstraint(
                fields=("school", "author", "subject", "grade"),
                condition=models.Q(is_live=True),
                name="one_live_template_per_subject_and_grade",
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.subject}, {self.grade})"

    @property
    def lesson_count(self) -> int:
        return self.rows.filter(is_header=False).count()


class PlanTemplateRow(LessonContent):
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

    def clean(self):
        super().clean()

        problems = content_problems(
            is_section=self.is_header,
            values={field: getattr(self, field) for field in CONTENT_FIELDS},
        )
        if problems:
            raise ValidationError(problems)
