from django.contrib import admin

from .models import AiSpend


@admin.register(AiSpend)
class AiSpendAdmin(admin.ModelAdmin):
    list_display = ("created_at", "school", "user", "purpose", "model", "cost_micros")
    list_filter = ("school", "purpose", "model")
    # Журнал не правится: строка здесь — событие, а не запись о состоянии.
    readonly_fields = [f.name for f in AiSpend._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
