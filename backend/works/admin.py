from django.contrib import admin

from .models import Submission, Task, Work


class TaskInline(admin.TabularInline):
    model = Task
    extra = 0


@admin.register(Work)
class WorkAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "teacher", "opens_at", "closes_at")
    list_filter = ("course",)
    search_fields = ("title",)
    inlines = [TaskInline]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    """
    Отправки только на чтение: журнал правят через приложение или никак.

    Здесь легче всего забыть, что строка — это не «текущий ответ ученика», а
    запись о том, что он отправил в такую-то минуту.
    """

    list_display = ("student", "task", "created_at", "is_correct")
    list_filter = ("is_correct",)
    readonly_fields = ("task", "student", "answer", "created_at")
