from django.contrib import admin

from .models import Course, Slot


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "school")
    list_filter = ("school", "year")
    search_fields = ("name",)


@admin.register(Slot)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("date", "lesson_number", "course", "is_cancelled")
    list_filter = ("course", "is_cancelled", "is_extra")
    date_hierarchy = "date"
