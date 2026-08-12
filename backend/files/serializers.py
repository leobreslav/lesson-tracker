from config.errors import Codes, api_error
from django.db.models import Count
from rest_framework import serializers

from .models import Attachment, KIND_FILE, KIND_LINK, StoredFile


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

    class Meta:
        model = Attachment
        fields = (
            "id",
            "kind",
            "title",
            "url",
            "position",
            "file_name",
            "size",
            "content_type",
            "is_shared",
        )
        read_only_fields = ("id", "kind", "url", "position")

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
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    file = serializers.FileField(required=False)

    def get_fields(self):
        from .access import writable_plan_rows, writable_template_rows

        fields = super().get_fields()
        user = self.context["request"].user
        fields["plan_row"].queryset = writable_plan_rows(user)
        fields["template_row"].queryset = writable_template_rows(user)
        return fields

    def validate(self, attrs):
        plan_row = attrs.get("plan_row")
        template_row = attrs.get("template_row")

        if (plan_row is None) == (template_row is None):
            api_error(
                Codes.ATTACHMENT_OWNER_REQUIRED,
                "Name exactly one of «plan_row» and «template_row».",
                field="plan_row",
            )

        row = plan_row or template_row
        if getattr(row, "is_section", False) or getattr(row, "is_header", False):
            api_error(
                Codes.CONTENT_ON_SECTION,
                "A section header holds no lesson content.",
                field="plan_row" if plan_row else "template_row",
            )

        upload = attrs.get("file")
        url = attrs.get("url")

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
