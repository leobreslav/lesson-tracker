from config.errors import Codes, api_error
from django.db.models import Count
from rest_framework import serializers

from .models import (
    Attachment,
    KIND_FILE,
    KIND_LINK,
    KIND_TEXT,
    KINDS,
    OWNER_FIELDS,
    StoredFile,
)
from .services import INLINE_EXTENSIONS, shows_in_text


def with_sharing(queryset):
    """
    Attachments plus how many references their file has.

    Counted in the query rather than per row: «this file is used elsewhere»
    is drawn next to every attachment, and a lesson with six of them would
    otherwise ask the database six extra times to say so.
    """
    return queryset.select_related("stored_file").annotate(
        reference_count=Count("stored_file__attachments")
    )


class AttachmentSerializer(serializers.ModelSerializer):
    """One reference, as the panel shows it."""

    file_name = serializers.CharField(source="stored_file.original_name", default=None)
    size = serializers.IntegerField(source="stored_file.size", default=None)
    content_type = serializers.CharField(
        source="stored_file.content_type", default=None
    )
    is_shared = serializers.SerializerMethodField()
    # объект в бакете, а не ссылка на него: разметка содержания называет
    # именно его, потому что переживает копирование плана и откат
    file = serializers.IntegerField(source="stored_file_id", read_only=True)

    class Meta:
        model = Attachment
        fields = (
            "id",
            "kind",
            "title",
            "url",
            "position",
            "inline",
            "file",
            "file_name",
            "size",
            "content_type",
            "is_shared",
        )
        read_only_fields = ("id", "kind", "url", "position", "inline")

    def get_is_shared(self, obj) -> bool:
        # the annotation when it is there, the model's own answer otherwise
        count = getattr(obj, "reference_count", None)
        if count is None:
            return obj.is_shared
        return count > 1


class AttachmentCreateSerializer(serializers.Serializer):
    """
    Adding a reference: either an uploaded file or an address on the web.

    The row it hangs off is validated against what this person may write, so
    a plan node id belonging to a colleague is simply not a valid choice.
    """

    plan_row = serializers.PrimaryKeyRelatedField(
        queryset=Attachment.objects.none(), required=False, allow_null=True
    )
    template_row = serializers.PrimaryKeyRelatedField(
        queryset=Attachment.objects.none(), required=False, allow_null=True
    )
    student_work = serializers.PrimaryKeyRelatedField(
        queryset=Attachment.objects.none(), required=False, allow_null=True
    )
    work = serializers.PrimaryKeyRelatedField(
        queryset=Attachment.objects.none(), required=False, allow_null=True
    )
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    file = serializers.FileField(required=False)
    # вид называется только у записи: у файла и ссылки он и так виден по
    # тому, что прислали, а у записи присылать нечего
    kind = serializers.ChoiceField(choices=KINDS, required=False)
    # «эта картинка встала в текст» — про распоряжение ею, а не про вид
    inline = serializers.BooleanField(required=False, default=False)

    def get_fields(self):
        from .access import (
            writable_plan_rows,
            writable_student_works,
            writable_template_rows,
            writable_works,
        )

        fields = super().get_fields()
        user = self.context["request"].user
        fields["plan_row"].queryset = writable_plan_rows(user)
        fields["template_row"].queryset = writable_template_rows(user)
        fields["student_work"].queryset = writable_student_works(user)
        fields["work"].queryset = writable_works(user)
        return fields

    def validate(self, attrs):
        owners = {name: attrs.get(name) for name in OWNER_FIELDS}
        named = [name for name, value in owners.items() if value is not None]

        if len(named) != 1:
            api_error(
                Codes.ATTACHMENT_OWNER_REQUIRED,
                "Name exactly one owner: «plan_row», «template_row», «work» "
                "or «student_work».",
                field="plan_row",
            )

        plan_row, template_row = owners["plan_row"], owners["template_row"]
        row = owners[named[0]]
        if getattr(row, "is_section", False) or getattr(row, "is_header", False):
            api_error(
                Codes.CONTENT_ON_SECTION,
                "A section header holds no lesson content.",
                field="plan_row" if plan_row else "template_row",
            )

        upload = attrs.get("file")
        url = attrs.get("url")

        if attrs.get("inline"):
            # в текст встаёт картинка, и только она: показать ссылку или
            # запись нечем, а из файлов показывается не всякий
            if upload is None or not shows_in_text(upload.name):
                api_error(
                    Codes.ATTACHMENT_NOT_AN_IMAGE,
                    "Only an image can stand inside the lesson text.",
                    field="file",
                    allowed=sorted(INLINE_EXTENSIONS),
                )
            if owners["student_work"] is not None:
                # у работы ученика текста нет — есть его тетрадь. Ставить
                # картинку «в текст» тут некуда, и `inline` означал бы
                # фотографию, которую не видно ни в списке, ни в содержании.
                # У самой работы (`work`) текст есть — пояснения к заданию, —
                # и картинка в них законна
                api_error(
                    Codes.ATTACHMENT_KIND_MISMATCH,
                    "A student's work has no text to stand in.",
                    field="student_work",
                )

        if attrs.get("kind") == KIND_TEXT:
            if upload or url:
                api_error(
                    Codes.ATTACHMENT_KIND_MISMATCH,
                    "A text resource carries neither a file nor an address.",
                    field="file",
                )
            if not (attrs.get("title") or "").strip():
                api_error(
                    Codes.ATTACHMENT_TITLE_REQUIRED,
                    "A text resource is its title — it cannot be empty.",
                    field="title",
                )
            return attrs

        if bool(upload) == bool(url):
            api_error(
                Codes.ATTACHMENT_KIND_MISMATCH,
                "Send either a file or an address, not both and not neither.",
                field="file",
            )

        attrs["kind"] = KIND_FILE if upload else KIND_LINK
        return attrs


class StoredFileSerializer(serializers.ModelSerializer):
    """Only the admin and the cleanup report need this."""

    class Meta:
        model = StoredFile
        fields = ("id", "key", "original_name", "size", "content_type", "created_at")
