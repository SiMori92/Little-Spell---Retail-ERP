"""Platform infrastructure models.

Two things live here, and no business data:

* `DatasetSettings` — the SAMPLE/ACTUAL quarantine flag (DATA_REVIEW addendum §A1.2).
* `AuditLogEntry` — an append-only record of who changed what and when, carrying
  NO customer PII.

Business models (orders, inventory, lots, shipments, POs, journals, accounts,
customers) belong to Slices A and B and must not be added here.
"""

from django.conf import settings
from django.db import models


class DatasetKind(models.TextChoices):
    SAMPLE = "SAMPLE", "Sample data — not actuals"
    ACTUAL = "ACTUAL", "Actual data"


class DatasetSettings(models.Model):
    """Singleton. One row, pk=1, enforced by a CHECK constraint.

    `dataset_kind` defaults to SAMPLE. It is flipped to ACTUAL only by the
    `flip_dataset_to_actual` management command, which refuses while no real
    opening entry exists (DATA_REVIEW addendum §A1.4).
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    dataset_kind = models.CharField(
        max_length=6,
        choices=DatasetKind.choices,
        default=DatasetKind.SAMPLE,
        help_text="While SAMPLE, every page renders the SAMPLE DATA — NOT ACTUALS banner.",
    )
    seed_journal_entry_ref = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=(
            "source_ref of the single balanced seed JE, e.g. SAMPLE_SEED_2026-09-20. "
            "Set by Slice B when the seed is loaded; cleared when it is reversed."
        ),
    )
    flipped_to_actual_at = models.DateTimeField(null=True, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "dataset settings"
        verbose_name_plural = "dataset settings"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1), name="core_datasetsettings_singleton"
            )
        ]

    def __str__(self) -> str:
        return f"dataset_kind={self.dataset_kind}"

    def save(self, *args, **kwargs):
        self.id = 1
        return super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "DatasetSettings":
        """Return the singleton, creating it as SAMPLE if it is missing.

        Defaulting to SAMPLE on creation is deliberate: a missing row must never
        be read as "these are actuals".
        """
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def is_sample(self) -> bool:
        return self.dataset_kind == DatasetKind.SAMPLE


class AuditAction(models.TextChoices):
    CREATE = "CREATE", "Create"
    UPDATE = "UPDATE", "Update"
    DELETE = "DELETE", "Delete"


class AuditLogEntry(models.Model):
    """Append-only: who changed what, and when.

    NO CUSTOMER PII. This table records field NAMES, never field VALUES. That is
    the mechanism by which the guarantee holds rather than being a promise — there
    is no column for a value to land in, so a future model carrying a buyer name
    or a street address cannot leak it here.

    Append-only is enforced by a database trigger (see migration 0002), not by
    this class alone. Application-level validation gets bypassed by the next
    script written at midnight (BUILD_TASK §3.4).
    """

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    actor_username = models.CharField(max_length=150, blank=True, default="")
    action = models.CharField(max_length=6, choices=AuditAction.choices)
    app_label = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100)
    object_pk = models.CharField(max_length=64, blank=True, default="")
    changed_fields = models.JSONField(
        default=list,
        blank=True,
        help_text="Field NAMES only. Never values — that is what keeps PII out of this table.",
    )
    request_method = models.CharField(max_length=8, blank=True, default="")
    request_path = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "audit log entry"
        verbose_name_plural = "audit log"
        ordering = ("-at", "-id")
        indexes = [models.Index(fields=["app_label", "model_name", "object_pk"])]

    def __str__(self) -> str:
        who = self.actor_username or "system"
        return f"{self.at:%Y-%m-%d %H:%M} {who} {self.action} {self.app_label}.{self.model_name}"

    def delete(self, *args, **kwargs):
        raise RuntimeError("The audit log is append-only; entries cannot be deleted.")

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("The audit log is append-only; entries cannot be modified.")
        return super().save(*args, **kwargs)
