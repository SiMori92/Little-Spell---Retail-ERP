"""Audit-log signal receivers.

Every model save and delete is recorded, except the exclusions below. The record
holds field NAMES only, never values, so no customer PII can reach this table.
"""

from django.db import connection, router
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from core.middleware import get_actor
from core.models import AuditAction, AuditLogEntry

# Excluded from auditing:
#   core.auditlogentry — auditing the audit log recurses forever.
#   sessions.session   — session keys are credentials; they do not belong in a log.
#   admin.logentry     — Django's own admin log already covers it; duplicating it
#                        doubles the rows and adds nothing.
#   contenttypes.contenttype / auth.permission — framework bookkeeping. Both are
#                        written by `migrate`, not by a person. Note that GRANTING a
#                        permission is recorded on the user or group row, which IS
#                        audited; only the permission catalogue itself is skipped.
EXCLUDED = {
    ("core", "auditlogentry"),
    ("sessions", "session"),
    ("admin", "logentry"),
    ("contenttypes", "contenttype"),
    ("auth", "permission"),
}


def _audit_table_exists() -> bool:
    """True once core_auditlogentry exists.

    `migrate` writes rows before this table is created, and the migration test rolls
    `core` back to zero and forward again, so the answer genuinely changes during a
    process's lifetime. It is therefore checked rather than cached — `to_regclass`
    is an index-free catalogue lookup, and this application's write volume is a
    one-person business, not a firehose.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.core_auditlogentry') IS NOT NULL")
        return bool(cursor.fetchone()[0])


def _excluded(instance) -> bool:
    meta = instance._meta
    if (meta.app_label, meta.model_name) in EXCLUDED:
        return True
    if router.db_for_write(type(instance)) not in (None, "default"):
        return True
    return not _audit_table_exists()


def _write(instance, action, changed_fields):
    actor_id, username, method, path = get_actor()
    AuditLogEntry.objects.create(
        actor_id=actor_id,
        actor_username=username,
        action=action,
        app_label=instance._meta.app_label,
        model_name=instance._meta.model_name,
        object_pk=str(instance.pk)[:64] if instance.pk is not None else "",
        changed_fields=sorted(changed_fields),
        request_method=method,
        request_path=path,
    )


@receiver(pre_save)
def stash_dirty_fields(sender, instance, **kwargs):
    """Work out which fields changed, before the row is overwritten.

    Only field names are compared and kept; the values are read and discarded.
    """
    if _excluded(instance) or instance.pk is None:
        return
    try:
        previous = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return
    changed = [
        f.name
        for f in sender._meta.concrete_fields
        if getattr(previous, f.attname, None) != getattr(instance, f.attname, None)
    ]
    instance._audit_changed_fields = changed


@receiver(post_save)
def audit_save(sender, instance, created, **kwargs):
    if _excluded(instance):
        return
    if created:
        fields = [f.name for f in sender._meta.concrete_fields]
        _write(instance, AuditAction.CREATE, fields)
        return
    changed = getattr(instance, "_audit_changed_fields", None)
    if changed is None:
        changed = [f.name for f in sender._meta.concrete_fields]
    if changed:
        _write(instance, AuditAction.UPDATE, changed)
    instance._audit_changed_fields = None


@receiver(post_delete)
def audit_delete(sender, instance, **kwargs):
    if _excluded(instance):
        return
    _write(instance, AuditAction.DELETE, [])
