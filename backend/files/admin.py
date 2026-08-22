from django.contrib import admin

from .models import Attachment, StoredFile


@admin.register(StoredFile)
class StoredFileAdmin(admin.ModelAdmin):
    list_display = ("original_name", "school", "size", "content_type", "references")
    list_filter = ("school", "content_type")
    search_fields = ("original_name", "key", "checksum")
    readonly_fields = ("key", "checksum", "size", "created_at")

    @admin.display(description="references")
    def references(self, obj):
        return obj.reference_count


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "plan_row", "template_row", "stored_file")
    list_filter = ("kind",)
    search_fields = ("title", "url")
