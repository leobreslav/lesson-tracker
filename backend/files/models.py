"""
Files and the links to them — two models on purpose, not one.

A file does not belong to a lesson; a lesson points at it. That distinction is
the whole reason this app exists: when a colleague takes a plan off the shelf,
the copy must reference **the same object in R2**, not a duplicate of it. One
model holding both the bytes and the lesson could not express that.

So `StoredFile` is the object in the bucket and `Attachment` is one lesson's
reference to it. Uploading the same file twice reuses the row (see
`services.store_upload`); removing the last reference removes the object
(see `signals`). In between, a file quietly serves however many lessons need
it, in however many teachers' plans.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

KIND_FILE = "file"
KIND_LINK = "link"
# A resource that is only named: «Мордкович, §14», «принести линейку».
# Nothing is stored and nothing is fetched — the title *is* the resource.
KIND_TEXT = "text"
KINDS = ((KIND_FILE, "file"), (KIND_LINK, "link"), (KIND_TEXT, "text"))


class StoredFile(models.Model):
    """
    One object in the bucket.

    Belongs to a school, never to a person: files do not leave the school, and
    an account going away must not take the school's materials with it — hence
    `SET_NULL` on the uploader.
    """

    school = models.ForeignKey(
        "schools.School",
        related_name="files",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="uploaded_files",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="uploaded by",
    )
    # the address in R2: files/<school>/<uuid>/<name>
    key = models.CharField("object key", max_length=400, unique=True)
    original_name = models.CharField("original name", max_length=255)
    size = models.PositiveIntegerField("size, bytes")
    content_type = models.CharField("content type", max_length=120)
    # sha256, for deduplication; blank means «not computed», never «empty file»
    checksum = models.CharField("sha256", max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "stored file"
        verbose_name_plural = "stored files"
        ordering = ("-created_at", "id")
        indexes = [
            # the deduplication lookup: same school, same bytes, same length
            models.Index(
                fields=("school", "checksum", "size"), name="stored_file_dedup_idx"
            ),
        ]

    def __str__(self):
        return self.original_name

    @property
    def reference_count(self) -> int:
        return self.attachments.count()


class Attachment(models.Model):
    """
    Материал урока: файл, адрес в сети или просто запись.

    Третий вид не хранит и не открывает ничего — «Мордкович, §14», «принести
    линейку». Своего поля ему не нужно: название и есть весь материал, а
    заводить ради него отдельную таблицу значило бы делить надвое один
    список, который человек видит и правит как один.

    Мест три, и ровно одно у каждой ссылки: строка учебного плана, строка
    шаблона на полке и **работа конкретного ученика**. Все три `CASCADE`:
    уходит владелец — уходят его ссылки, а сигнал потом решает, нужен ли ещё
    файл за ними.

    Третий владелец отличается от первых двух правом на чтение: план и
    шаблон читают учителя, а работу ученика — учитель, **сам ученик** и его
    родитель, и никто больше. Ошибка здесь это не «показали лишнее», а чужая
    контрольная с отметками у одноклассника.

    У третьего же владельца две стороны, и они лежат вперемешку намеренно.
    Скан — запись **учителя** о работе, фотография тетради — слова
    **ученика** о ней, а различает их `added_by`, а не отдельная таблица:
    изображение работы ученика это одна и та же вещь, просмотрщик листает
    их одной лентой, и разделять их значило бы дважды спрашивать одно.
    Различие нужно ровно в одном месте — кто вправе это убрать.

    Внутри работы у ссылки есть ещё и адрес: `task` называет вопрос, к
    которому приложено, или пуст — «это про работу целиком».

    `stored_file` is `PROTECT` so that a file can never be deleted out from
    under a reference. Removal happens the other way round, from the last
    reference outwards.
    """

    plan_row = models.ForeignKey(
        "plans.PlanNode",
        related_name="attachments",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name="plan lesson",
    )
    template_row = models.ForeignKey(
        "library.PlanTemplateRow",
        related_name="attachments",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name="template row",
    )
    student_work = models.ForeignKey(
        "works.StudentWork",
        related_name="attachments",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name="student's work",
    )
    # Куда **внутри** работы ученика это приложено: к вопросу или ко всей
    # работе разом.
    #
    # Не четвёртый владелец, а уточнение адреса у третьего, и разница
    # принципиальна. Фотография решения — это всегда работа **этого** ученика
    # по **этой** работе; вопрос лишь в том, названа ли внутри неё задача.
    # Заведи мы владельца «задача и ученик», и у одного и того же ученика
    # появилось бы два не связанных между собой места с его фотографиями —
    # а оценка, комментарий и скан лежат на `StudentWork`, и просмотрщику
    # пришлось бы собирать их из двух источников.
    #
    # Пусто — фотография всей работы: «задач слишком много, снимаю тетрадь
    # целиком». Это законное состояние, а не пропуск, и оно же у скана,
    # приложенного учителем.
    task = models.ForeignKey(
        "works.Task",
        related_name="attachments",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name="question inside the work",
    )
    # Кто положил эту ссылку сюда. Не «кто загрузил байты»: то отвечает
    # `StoredFile.uploaded_by`, и после дедупликации это может быть вовсе
    # посторонний человек, приложивший тот же файл первым.
    #
    # Отвечает поле на два вопроса, и оба живые. Первый — **чьё это слово**:
    # скан от учителя и фотография от ученика лежат на одной строке, и
    # различить их больше нечем. Второй — **кто именно из семьи**: за
    # маленького ученика фотографию присылает родитель, и «прислала мама»
    # видно должно быть.
    #
    # Пусто у всего, что легло сюда до появления поля, и это честно:
    # единственным видом вложения работы был тогда учительский скан.
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="attachments_added",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="added by",
    )
    # На сколько повернуть картинку при показе. Свойство **ссылки**, а не
    # файла: байты в бакете общие (дедупликация), и повернуть их значило бы
    # повернуть их у всех, кто на них смотрит.
    #
    # Хранится потому, что снятая боком тетрадь снята боком навсегда:
    # поворот, живущий в состоянии вкладки, каждый учитель делал бы заново
    # при каждом открытии, а ученик не увидел бы его вовсе.
    rotation = models.PositiveSmallIntegerField(
        "rotation, degrees clockwise",
        default=0,
        choices=((0, "0°"), (90, "90°"), (180, "180°"), (270, "270°")),
    )
    kind = models.CharField("kind", max_length=8, choices=KINDS, default=KIND_FILE)
    stored_file = models.ForeignKey(
        StoredFile,
        related_name="attachments",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name="file",
    )
    url = models.URLField("address", max_length=500, blank=True)
    # Картинка, вставленная **в текст** урока, а не приложенная к нему.
    #
    # Разница не косметическая: материал — это то, чем на уроке пользуются
    # («карточки.pdf», «принести линейку»), и человек правит его списком. А
    # картинка в содержании — часть самого содержания: её ставят, двигают и
    # убирают в тексте, и в списке материалов она была бы строкой, которую
    # нельзя понять, не открыв текст. Отсюда отдельный признак, а не
    # четвёртый `kind`: вид отвечает на «на что ссылка», а этот — на «кто ею
    # распоряжается».
    inline = models.BooleanField("inline in the text", default=False)
    title = models.CharField("title", max_length=200)
    position = models.PositiveIntegerField("position", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "attachment"
        verbose_name_plural = "attachments"
        ordering = ("position", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        plan_row__isnull=False,
                        template_row__isnull=True,
                        student_work__isnull=True,
                    )
                    | Q(
                        plan_row__isnull=True,
                        template_row__isnull=False,
                        student_work__isnull=True,
                    )
                    | Q(
                        plan_row__isnull=True,
                        template_row__isnull=True,
                        student_work__isnull=False,
                    )
                ),
                name="attachment_has_exactly_one_owner",
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind=KIND_FILE, stored_file__isnull=False)
                    | Q(kind=KIND_LINK, stored_file__isnull=True)
                    | Q(kind=KIND_TEXT, stored_file__isnull=True, url="")
                ),
                name="attachment_kind_matches_target",
            ),
            # в текст ставится картинка, то есть файл. Ссылка и запись
            # показать нечего, и «инлайновая ссылка» была бы ссылкой,
            # которую человек не видит ни в списке, ни в тексте
            models.CheckConstraint(
                condition=Q(inline=False) | Q(kind=KIND_FILE),
                name="inline_attachment_is_a_file",
            ),
            # задача — адрес **внутри** работы ученика, и у вложения плана
            # или шаблона такого адреса нет: там нет ни работы, ни ученика,
            # чью задачу можно было бы назвать
            models.CheckConstraint(
                condition=Q(task__isnull=True) | Q(student_work__isnull=False),
                name="attachment_task_lives_inside_a_students_work",
            ),
        ]
        indexes = [
            models.Index(fields=("plan_row", "position"), name="attachment_plan_idx"),
            models.Index(
                fields=("template_row", "position"), name="attachment_template_idx"
            ),
            models.Index(
                fields=("student_work", "position"), name="attachment_student_idx"
            ),
            # просмотрщик спрашивает «что приложено к этому вопросу этого
            # ученика», и спрашивает по разу на клетку таблицы
            models.Index(fields=("task", "position"), name="attachment_task_idx"),
        ]

    def __str__(self):
        return self.title or self.url

    @property
    def is_shared(self) -> bool:
        """Whether somebody else's lesson points at the same file."""
        if self.stored_file_id is None:
            return False
        return self.stored_file.attachments.exclude(pk=self.pk).exists()

    def clean(self):
        super().clean()
        problems = {}

        owners = [self.plan_row_id, self.template_row_id, self.student_work_id]
        if sum(1 for owner in owners if owner is not None) != 1:
            problems["plan_row"] = (
                "An attachment belongs to a plan lesson, a template row or a "
                "student's work — to exactly one of them."
            )

        if self.task_id is not None and self.student_work_id is None:
            problems["task"] = (
                "A question can only be named inside a student's work."
            )

        if self.kind == KIND_FILE and self.stored_file_id is None:
            problems["stored_file"] = "A file attachment must name a file."
        if self.inline and self.kind != KIND_FILE:
            problems["inline"] = "Only a file can stand inside the text."
        if self.kind == KIND_LINK:
            if self.stored_file_id is not None:
                problems["stored_file"] = "A link attachment must not name a file."
            if not self.url:
                problems["url"] = "A link attachment must carry an address."
        if self.kind == KIND_TEXT:
            # у записи нет цели вовсе: её название и есть весь материал
            if self.stored_file_id is not None:
                problems["stored_file"] = "A text resource must not name a file."
            if self.url:
                problems["url"] = "A text resource carries no address."
            if not self.title.strip():
                problems["title"] = "A text resource is its title."

        if problems:
            raise ValidationError(problems)
