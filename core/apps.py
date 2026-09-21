from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Platform"

    def ready(self):
        # Registering the audit receivers is what makes the log a code path rather
        # than something a caller has to remember to invoke.
        from core import signals  # noqa: F401
