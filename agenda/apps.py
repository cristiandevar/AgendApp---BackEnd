from django.apps import AppConfig


class AgendaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "agenda"
    # El nombre interno ("agenda") se mantiene: define las tablas y migraciones.
    verbose_name = "AgendApp"
