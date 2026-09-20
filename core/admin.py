from django.contrib import admin

from core.models import AuditLogEntry, DatasetSettings


@admin.register(DatasetSettings)
class DatasetSettingsAdmin(admin.ModelAdmin):
    """Read-only in the admin, deliberately.

    `dataset_kind` is flipped by `manage.py flip_dataset_to_actual`, which refuses
    while no real opening entry exists. An editable dropdown here would be a way to
    clear the quarantine banner without reversing the seed, which is precisely what
    DATA_REVIEW addendum §A1.4 forbids.
    """

    list_display = ("dataset_kind", "seed_journal_entry_ref", "flipped_to_actual_at", "updated_at")
    readonly_fields = tuple(f.name for f in DatasetSettings._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditLogEntry)
class AuditLogEntryAdmin(admin.ModelAdmin):
    """Append-only, so: view and filter, never add, change or delete."""

    list_display = ("at", "actor_username", "action", "app_label", "model_name", "object_pk")
    list_filter = ("action", "app_label", "model_name")
    search_fields = ("actor_username", "object_pk")
    date_hierarchy = "at"
    readonly_fields = tuple(f.name for f in AuditLogEntry._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
