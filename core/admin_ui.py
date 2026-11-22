"""Shared admin presentation: labelled status and dataset badges for the read-only ops console.

Colour reinforces the text label; it never replaces it. Tones are conservative: a file-reported
pipeline stage (an Instagram "paid", an Etsy "shipped") is not proof, so it is never shown as success.
"""

from django.contrib import admin
from django.utils.html import format_html

PERIOD_TONES = {"OPEN": "active", "CLOSED": "good", "BLOCKED": "danger"}
PO_TONES = {"draft": "neutral", "sent": "active", "acknowledged": "active", "received": "good",
            "closed": "good", "short_closed": "warn", "cancelled": "warn"}
ORDER_TONES = {"placed": "neutral", "shipped": "active", "cancelled": "warn", "refunded": "warn"}
SHIPMENT_TONES = {"pending": "neutral", "dispatched": "good"}
DATASET_TONES = {"SAMPLE": "warn", "ACTUAL": "neutral"}


def badge(value, tones):
    if value in (None, ""):
        return None  # admin shows its empty-value marker; a blank is not a status
    return format_html('<span class="status-badge status-{}">{}</span>',
                       tones.get(value, "neutral"), str(value).replace("_", " "))


class BadgeColumnsMixin:
    """Render `status` and `dataset_kind` list columns as badges without touching each list_display."""

    status_tones = PERIOD_TONES

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return badge(obj.status, self.status_tones)

    @admin.display(description="Dataset", ordering="dataset_kind")
    def dataset_badge(self, obj):
        return badge(obj.dataset_kind, DATASET_TONES)

    def get_list_display(self, request):
        swap = {"status": "status_badge", "dataset_kind": "dataset_badge"}
        columns = list(super().get_list_display(request))
        # The first column stays plain: Django makes it the link to the record.
        return columns[:1] + [swap.get(column, column) if isinstance(column, str) else column
                              for column in columns[1:]]
