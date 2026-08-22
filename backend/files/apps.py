from django.apps import AppConfig


class FilesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "files"
    verbose_name = "files and attachments"

    def ready(self):
        from . import signals  # noqa: F401
