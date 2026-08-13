from django.apps import AppConfig


class PlansConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plans"
    verbose_name = "Lesson plan"

    def ready(self):
        # правка плана отзывает поданный запрос на утверждение
        from . import signals  # noqa: F401
