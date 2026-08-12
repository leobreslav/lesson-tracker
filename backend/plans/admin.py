from django.contrib import admin

from .models import PlanNode


@admin.register(PlanNode)
class PlanNodeAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "teacher", "parent", "position", "is_section")
    list_filter = ("course", "teacher", "is_section")
    search_fields = ("title",)
