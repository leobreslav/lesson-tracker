from django.contrib import admin

from .models import LessonSlot, SchoolClass


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "owner")
    list_filter = ("year",)
    search_fields = ("name", "owner__email")


@admin.register(LessonSlot)
class LessonSlotAdmin(admin.ModelAdmin):
    list_display = ("date", "lesson_number", "school_class", "is_cancelled", "is_extra")
    list_filter = ("school_class", "is_cancelled", "is_extra")
    date_hierarchy = "date"
