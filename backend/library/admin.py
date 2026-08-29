from django.contrib import admin

from .models import PlanTemplate


@admin.register(PlanTemplate)
class PlanTemplateAdmin(admin.ModelAdmin):
    """
    Полка школы. Строк плана здесь нет намеренно.

    Строки шаблона — это обычные строки плана (`plans.PlanNode`), и правятся
    они тем же экраном, что и план курса. Вкладка со строками прямо здесь
    была бы вторым местом, где их правят, — и вторым набором правил про
    вложенность и порядок, расходящимся с первым молча.
    """

    list_display = ("title", "subject", "grade", "author", "is_published")
    list_filter = ("school", "subject", "grade", "is_published")
    search_fields = ("title", "description")
