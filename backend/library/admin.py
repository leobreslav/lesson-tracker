from django.contrib import admin

from .models import PlanTemplate, PlanTemplateRow


class RowInline(admin.TabularInline):
    model = PlanTemplateRow
    extra = 0


@admin.register(PlanTemplate)
class PlanTemplateAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "grade", "author", "is_published")
    list_filter = ("school", "subject", "grade", "is_published")
    search_fields = ("title", "description")
    inlines = [RowInline]
