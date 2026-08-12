from django.contrib import admin

from .models import PlanNode


@admin.register(PlanNode)
class PlanNodeAdmin(admin.ModelAdmin):
    list_display = ("title", "school_class", "parent", "position", "is_section", "kind")
    list_filter = ("school_class", "is_section", "kind")
    search_fields = ("title",)
