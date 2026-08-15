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
KINDS = ((KIND_FILE, "file"), (KIND_LINK, "link"))


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
    Ссылка на файл или на адрес в сети — из одного места, где она нужна.

    Мест три, и ровно одно у каждой ссылки: строка учебного плана, строка
    шаблона на полке и **работа конкретного ученика** (скан того, что он
    написал на бумаге). Все три `CASCADE`: уходит владелец — уходят его
    ссылки, а сигнал потом решает, нужен ли ещё файл за ними.

    Третий владелец отличается от первых двух правом на чтение: план и
    шаблон читают учителя, а скан — учитель **и сам ученик**, и никто
    больше. Ошибка здесь это не «показали лишнее», а чужая контрольная с
    отметками у одноклассника.

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
                ),
                name="attachment_kind_matches_target",
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

        if self.kind == KIND_FILE and self.stored_file_id is None:
            problems["stored_file"] = "A file attachment must name a file."
        if self.kind == KIND_LINK:
            if self.stored_file_id is not None:
                problems["stored_file"] = "A link attachment must not name a file."
            if not self.url:
                problems["url"] = "A link attachment must carry an address."

        if problems:
            raise ValidationError(problems)
