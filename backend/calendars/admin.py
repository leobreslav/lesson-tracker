from django.contrib import admin

from .models import DayException, SchoolYear


class DayExceptionInline(admin.TabularInline):
    model = DayException
    extra = 0


@admin.register(SchoolYear)
class SchoolYearAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "start_date", "end_date")
    list_filter = ("owner",)
    search_fields = ("name", "owner__email")
    inlines = [DayExceptionInline]


@admin.register(DayException)
class DayExceptionAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "start_date", "end_date", "year")
    list_filter = ("kind", "year")
