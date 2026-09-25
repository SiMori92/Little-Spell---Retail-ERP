from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from acct.models import CloseRun, JournalEntry
from core.models import DatasetSettings
from ops.models import InventoryMove, LedgerEvent, Order


def home(request):
    """A useful overview for signed-in staff and a safe entry point for visitors."""
    context = {"period": timezone.localdate().strftime("%Y-%m")}
    if request.user.is_authenticated:
        kind = DatasetSettings.load().dataset_kind
        context.update({
            "recorded_orders": Order.objects.filter(dataset_kind=kind).count(),
            "operational_events": LedgerEvent.objects.filter(dataset_kind=kind).count(),
            "inventory_moves": InventoryMove.objects.filter(dataset_kind=kind).count(),
            "journal_entries": JournalEntry.objects.filter(dataset_kind=kind).count(),
            "latest_close": CloseRun.objects.filter(dataset_kind=kind).order_by("-id").first(),
        })
    return render(request, "home.html", context)


def health(request):
    """Healthcheck for Railway: a bad deploy should fail, not serve errors."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    return JsonResponse({"status": "ok" if db_ok else "degraded", "database": db_ok},
                        status=200 if db_ok else 503)
