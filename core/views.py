from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render


def home(request):
    """Slice 0 landing page. Exists chiefly so the quarantine banner has a
    non-admin page to prove itself on."""
    return render(request, "home.html")


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
