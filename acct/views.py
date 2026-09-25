"""Authenticated read-only reporting views and provenance-preserving CSV exports."""

import csv
from zoneinfo import ZoneInfo

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone

from acct.reporting import Figure, REPORT_BUILDERS, period_bounds


def _period(request):
    period = request.GET.get("period") or timezone.localtime(timezone.now(), ZoneInfo("Asia/Taipei")).strftime("%Y-%m")
    period_bounds(period)
    return period


def _csv_text(value):
    """Prevent spreadsheet formula execution from any source-derived label."""
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def export_csv(report):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    prefix = "SAMPLE_" if report.dataset_kind == "SAMPLE" else ""
    filename = f"{prefix}{report.slug}_{report.period}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(["dataset_kind", report.dataset_kind, "cost_basis", report.cost_basis,
                     "generated_at", timezone.now().isoformat()])
    header = []
    for column in report.columns:
        header.append(column.label)
        if column.figure:
            header += [f"{column.key}_dataset_kind", f"{column.key}_cost_basis",
                       f"{column.key}_source_period", f"{column.key}_unit", f"{column.key}_reason"]
    writer.writerow(header)
    for row in report.rows:
        output = []
        for column in report.columns:
            value = row[column.key]
            if column.figure:
                if not isinstance(value, Figure):
                    raise ValueError(f"figure column {column.key} lacks provenance")
                output += ["ABSENT" if value.amount is None else str(value.amount),
                           value.dataset_kind, value.cost_basis, value.source_period,
                           value.unit, _csv_text(value.reason)]
            else:
                output.append(_csv_text(value))
        writer.writerow(output)
    return response


@login_required
def report_index(request):
    try:
        period = _period(request)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    return render(request, "reports/index.html", {"period": period, "reports": REPORT_BUILDERS})


@login_required
def report_detail(request, slug):
    builder = REPORT_BUILDERS.get(slug)
    if builder is None:
        raise Http404("unknown report")
    try:
        period = _period(request)
        report = builder(period)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if request.GET.get("format") == "csv":
        return export_csv(report)
    display_rows = []
    for row in report.rows:
        cells = []
        for column in report.columns:
            value = row[column.key]
            if column.figure:
                if not isinstance(value, Figure):
                    raise ValueError(f"figure column {column.key} lacks provenance")
                cells.append({"text": value.display(), "kind": value.dataset_kind,
                              "basis": value.cost_basis, "period": value.source_period,
                              "unit": value.unit})
            else:
                cells.append({"text": str(value), "kind": "", "basis": "", "period": "", "unit": ""})
        display_rows.append(cells)
    return render(request, "reports/report.html", {"report": report, "display_rows": display_rows})
