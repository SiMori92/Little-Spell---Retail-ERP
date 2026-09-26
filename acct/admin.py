"""Accounting records are read-only; all writes pass through catalogue posting."""

from django.contrib import admin

from acct.models import (Account, AcctManualEntry, ClearingCause, CloseAudit, CloseRun,
                         FxRate, JournalEntry, JournalLine, Period, WacPosition)
from ops.admin import ReadOnlyAdmin


@admin.register(Account)
class AccountAdmin(ReadOnlyAdmin):
    list_display = ("code", "name_en", "type", "statement", "is_reserved")
    list_filter = ("type", "statement", "is_reserved")
    search_fields = ("code", "name_en", "name_zh")


@admin.register(FxRate)
class FxRateAdmin(ReadOnlyAdmin):
    list_display = ("rate_date", "currency", "kind", "rate", "rate_source")
    list_filter = ("currency", "kind", "rate_source")
    search_fields = ("currency", "source_event_key")


@admin.register(Period)
class PeriodAdmin(ReadOnlyAdmin):
    list_display = ("period", "status")
    list_filter = ("status",)
    search_fields = ("period",)


@admin.register(WacPosition)
class WacPositionAdmin(ReadOnlyAdmin):
    list_display = ("sku", "qty_packs", "value_twd")
    search_fields = ("sku",)


@admin.register(JournalEntry)
class JournalEntryAdmin(ReadOnlyAdmin):
    list_display = ("source_ref", "period", "source_kind", "dataset_kind", "memo_only")
    list_filter = ("period", "source_kind", "dataset_kind", "memo_only")
    search_fields = ("source_ref", "period")


@admin.register(JournalLine)
class JournalLineAdmin(ReadOnlyAdmin):
    list_display = ("entry_id", "account_id", "sku", "debit", "credit", "qty_delta_packs")
    list_filter = ("account", "entry__period")
    search_fields = ("entry__source_ref", "account__code", "sku")


@admin.register(AcctManualEntry)
class AcctManualEntryAdmin(ReadOnlyAdmin):
    list_display = ("event_type", "period", "idempotency_key", "posted_entry_id")
    list_filter = ("event_type", "period")
    search_fields = ("event_type", "period", "idempotency_key")


@admin.register(ClearingCause)
class ClearingCauseAdmin(ReadOnlyAdmin):
    list_display = ("line_id", "recorded_by", "recorded_at")
    search_fields = ("line__entry__source_ref", "line__account__code")


@admin.register(CloseRun)
class CloseRunAdmin(ReadOnlyAdmin):
    list_display = ("period", "dataset_kind", "status", "runner", "elapsed_seconds")
    list_filter = ("dataset_kind", "status", "period")
    search_fields = ("period", "runner")


@admin.register(CloseAudit)
class CloseAuditAdmin(ReadOnlyAdmin):
    list_display = ("period", "action", "actor", "recorded_at")
    list_filter = ("action", "period")
    search_fields = ("period", "actor")
