"""Read-only settlement and carrier reconciliation views over posted evidence."""

from collections import defaultdict
from decimal import Decimal

from acct.gates import g2, settlement_aging
from acct.models import JournalLine
from acct.reporting import Column, Report, absent, combine, dataset_kind, known, period_bounds, _lines, _net
from ops.models import LedgerEvent, Order


def settlement_aging_report(period):
    kind = dataset_kind()
    data = settlement_aging(period)
    columns = (Column("account", "Rail", False), Column("line", "Journal line", False),
               Column("date", "Source date", False), Column("age", "Business days"),
               Column("open", "Open TWD"), Column("cause", "Named cause", False))
    rows = [{"account": item["account"], "line": item["line_id"], "date": item["occurred_at"],
             "age": known(item["business_days"], period, kind, unit="business days"),
             "open": known(Decimal(item["open_twd"]), period, kind),
             "cause": item["cause"] or "ABSENT — no named cause"} for item in data["items"]]
    if rows:
        rows.append({"account": "TOTAL", "line": "", "date": "",
                     "age": absent(period, kind, "not applicable to total", unit="business days"),
                     "open": known(Decimal(data["total_twd"]), period, kind), "cause": ""})
    else:
        rows.append({"account": "ABSENT", "line": "ABSENT", "date": "ABSENT",
                     "age": absent(period, kind, "no open rail item", unit="business days"),
                     "open": absent(period, kind, "no open rail item"), "cause": "ABSENT"})
    status = g2(period)
    return Report("settlement-aging", "Settlement and clearing aging", period, kind, columns, rows,
                  [f"G-2: {status.status} — {status.reason}.",
                   f"Signed open rail total: NT${data['total_twd']}.", data["calendar_basis"]])


def carrier_reconciliation(period):
    start, end = period_bounds(period)
    kind = dataset_kind()
    events = LedgerEvent.objects.filter(dataset_kind=kind, occurred_at__gte=start,
        occurred_at__lt=end, entity_table="ops.order",
        event_type__in=("order.ship_cost_accrued", "order.ship_cost_invoiced")).order_by("entity_id", "id")
    grouped = defaultdict(list)
    for event in events:
        grouped[event.entity_id].append(event)
    columns = (Column("order", "Order", False), Column("accrued", "6131 accrual"),
               Column("invoiced", "2172 carrier invoice"), Column("variance", "Invoice less accrual"),
               Column("open", "2191 still open"), Column("status", "Reconciliation", False))
    rows = []
    for order_id, order_events in grouped.items():
        order = Order.objects.filter(pk=order_id, dataset_kind=kind).first()
        accrual_events = [event for event in order_events if event.event_type == "order.ship_cost_accrued"]
        invoice_events = [event for event in order_events if event.event_type == "order.ship_cost_invoiced"]
        accrual_lines = [line for event in accrual_events for line in (_lines(event) or [])]
        invoice_lines = [line for event in invoice_events for line in (_lines(event) or [])]
        good_accrual = bool(accrual_events) and all(_lines(event) is not None for event in accrual_events)
        good_invoice = bool(invoice_events) and all(_lines(event) is not None for event in invoice_events)
        basis_notes = [event.payload.get("basis_note", "").strip() for event in accrual_events]
        basis = "; ".join(note for note in basis_notes if note)
        accrued = (known(_net(accrual_lines, ["6131"]), period, kind,
                         basis="provisional" if not good_invoice else "actual",
                         reason=f"[ESTIMATE] freight accrual basis: {basis or 'ABSENT'}" if not good_invoice else "",
                         estimate=not good_invoice)
                   if good_accrual else absent(period, kind, "posted carrier accrual missing"))
        invoiced = (known(_net(invoice_lines, ["2172"], direction="credit"), period, kind)
                    if good_invoice else absent(period, kind, "posted carrier invoice missing"))
        variance = (combine([invoiced, accrued], period, kind, signs=[1, -1])
                    if invoiced.amount is not None and accrued.amount is not None
                    else absent(period, kind, "invoice or accrual missing"))
        open_amount = (known(_net(accrual_lines + invoice_lines, ["2191"], direction="credit"), period, kind)
                       if good_accrual and (good_invoice or not invoice_events)
                       else absent(period, kind, "posted 2191 evidence missing"))
        if not good_accrual:
            status = "UNPROVABLE — accrual missing or unposted"
        elif not good_invoice:
            status = f"[ESTIMATE] open accrual; basis: {basis or 'ABSENT — G-5 failure'}"
        elif open_amount.amount != 0:
            status = "MISMATCH — 2191 not cleared"
        elif variance.amount is not None and variance.amount > 0:
            status = "VARIANCE — carrier invoice exceeds accrual"
        elif variance.amount is not None and variance.amount < 0:
            status = "VARIANCE — carrier invoice below accrual"
        else:
            status = "TIES — invoice equals accrual"
        rows.append({"order": order.channel_order_id if order else f"ops.order:{order_id}",
                     "accrued": accrued, "invoiced": invoiced, "variance": variance,
                     "open": open_amount, "status": status})
    if not rows:
        rows.append({"order": "ABSENT", "accrued": absent(period, kind, "no carrier accruals"),
                     "invoiced": absent(period, kind, "no carrier invoices"),
                     "variance": absent(period, kind, "no carrier evidence"),
                     "open": absent(period, kind, "no carrier evidence"), "status": "UNPROVABLE"})
    else:
        rows.append({"order": "TOTAL",
                     **{key: combine([row[key] for row in rows], period, kind)
                        for key in ("accrued", "invoiced", "variance", "open")},
                     "status": "Period totals; ABSENT if any order lacks evidence"})
    return Report("carrier-reconciliation", "Carrier invoice vs freight accrual", period, kind, columns, rows,
                  ["Rows show period activity; 6131 accrual, 2172 invoice, and remaining 2191 are named separately.",
                   "An uninvoiced accrual is [ESTIMATE] and requires a stated basis."])


RECONCILIATION_BUILDERS = {
    "settlement-aging": settlement_aging_report,
    "carrier-reconciliation": carrier_reconciliation,
}
