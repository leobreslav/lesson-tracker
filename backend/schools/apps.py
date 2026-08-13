from django.apps import AppConfig


class SchoolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "schools"
    verbose_name = "Schools"

    def ready(self):
        from . import signals  # noqa: F401
