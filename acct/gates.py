"""Slice B completeness gate G-1. Both frozen event streams are in scope."""
from acct.models import AcctManualEntry
from ops.models import LedgerEvent
from django.db.models import Q


def g1_unposted_counts(period_end):
    failing = Q(posted_entry_id__isnull=True) | Q(posting_error__isnull=False)
    return {
        "ops": LedgerEvent.objects.filter(occurred_at__lt=period_end).filter(failing).count(),
        "manual": AcctManualEntry.objects.filter(occurred_at__lt=period_end).filter(failing).count(),
    }


def assert_g1(period_end):
    counts = g1_unposted_counts(period_end)
    if counts["ops"] or counts["manual"]:
        raise ValueError(f"G-1 failed: ops={counts['ops']}, manual={counts['manual']}")
    return counts
