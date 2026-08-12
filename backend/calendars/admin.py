from django.contrib import admin

from .models import DayException, SchoolYear, Term


class DayExceptionInline(admin.TabularInline):
    model = DayException
    extra = 0


@admin.register(SchoolYear)
class SchoolYearAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "start_date", "end_date")
    list_filter = ("school",)
    search_fields = ("name", "school__name")
    inlines = [DayExceptionInline]


@admin.register(DayException)
class DayExceptionAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "start_date", "end_date", "year")
    list_filter = ("kind", "year")


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "start_date", "end_date", "position")
    list_filter = ("year",)
