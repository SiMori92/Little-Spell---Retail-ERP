"""Read-only operational reports: the Instagram pipeline, purchase orders and receiving."""

from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from acct.reporting import Column, Report, ReportSection, absent, known, period_bounds
from core.models import DatasetSettings
from ops.models import GoodsReceipt, IgDeal, LedgerEvent, PurchaseOrderLine, SupplierInvoice

PAID = {"paid", "shipped", "followed_up"}
QUOTED = {"quoted", *PAID}
OPEN = {"enquiry", "quoted"}
LOST_REASONS = ("no_reply", "price", "shipping_cost", "out_of_stock", "other")


def _as_date(raw):
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("as_of must be YYYY-MM-DD") from exc


def _deals(kind):
    rows = IgDeal.objects.filter(dataset_kind=kind).order_by("deal_id", "line_no")
    result = {}
    for row in rows:
        result.setdefault(row.deal_id, row)
    return list(result.values())


def ig_pipeline(as_of_text):
    as_of = _as_date(as_of_text)
    kind = DatasetSettings.load().dataset_kind
    deals = [deal for deal in _deals(kind) if deal.enquiry_at <= as_of]

    follow_columns = (Column("deal_id", "Deal", False), Column("customer_ref", "Customer", False),
                      Column("status", "Status", False), Column("days", "Days overdue"),
                      Column("quote", "Quote TWD"))
    follow_rows = []
    for deal in sorted((d for d in deals if d.status in OPEN and d.follow_up_on <= as_of),
                       key=lambda d: (d.follow_up_on, d.deal_id)):
        quote = (known(deal.quote_twd, as_of_text, kind) if deal.quote_twd is not None else
                 absent(as_of_text, kind, "deal has not reached quoted status"))
        follow_rows.append({"deal_id": deal.deal_id, "customer_ref": deal.customer_ref,
                            "status": deal.status,
                            "days": known((as_of - deal.follow_up_on).days, as_of_text, kind, unit="days"),
                            "quote": quote})

    journey_columns = (Column("deal_id", "Deal", False), Column("customer_ref", "Customer", False),
                       Column("step", "Step due", False), Column("due_on", "Due on", False),
                       Column("days", "Days overdue"))
    journey_rows = []
    next_step = {"none": ("d0", 0), "d0": ("d10", 10), "d10": ("d30", 30)}
    for deal in deals:
        if deal.status not in {"shipped", "followed_up"} or deal.consent_marketing != "yes":
            continue
        due = next_step.get(deal.journey_sent)
        if not due or not deal.ship_date:
            continue
        due_on = deal.ship_date + timedelta(days=due[1])
        if due_on <= as_of:
            journey_rows.append({"deal_id": deal.deal_id, "customer_ref": deal.customer_ref,
                                 "step": due[0], "due_on": due_on.isoformat(),
                                 "days": known((as_of - due_on).days, as_of_text, kind, unit="days")})
    journey_rows.sort(key=lambda row: (row["due_on"], row["deal_id"]))

    conversion_columns = (Column("month", "Enquiry month", False), Column("enquiries", "Enquiries"),
                          Column("quoted", "Quoted"), Column("paid", "Paid"),
                          *(Column(reason, f"Lost: {reason.replace('_', ' ')}") for reason in LOST_REASONS),
                          Column("quote_rate", "Quoted / enquiry"), Column("paid_rate", "Paid / enquiry"))
    months = defaultdict(list)
    for deal in deals:
        months[deal.enquiry_at.strftime("%Y-%m")].append(deal)
    months.setdefault(as_of.strftime("%Y-%m"), [])
    conversion_rows = []
    for month, cohort in sorted(months.items()):
        total = len(cohort)
        lost = Counter(d.lost_reason for d in cohort if d.status == "lost")
        row = {"month": month, "enquiries": known(total, month, kind, unit="deals")}
        # Milestone dates preserve conversion even when the current state later becomes lost.
        row["quoted"] = known(sum(d.quoted_at is not None for d in cohort), month, kind, unit="deals")
        row["paid"] = known(sum(d.paid_at is not None for d in cohort), month, kind, unit="deals")
        for reason in LOST_REASONS:
            row[reason] = known(lost[reason], month, kind, unit="deals")
        if total:
            row["quote_rate"] = known(Decimal(row["quoted"].amount) * 100 / total, month, kind, unit="percent")
            row["paid_rate"] = known(Decimal(row["paid"].amount) * 100 / total, month, kind, unit="percent")
        else:
            row["quote_rate"] = absent(month, kind, "zero enquiries in denominator", unit="percent")
            row["paid_rate"] = absent(month, kind, "zero enquiries in denominator", unit="percent")
        conversion_rows.append(row)
    sections = (ReportSection("Follow-ups due", follow_columns, follow_rows),
                ReportSection("Journey due", journey_columns, journey_rows),
                ReportSection("Conversion by enquiry month", conversion_columns, conversion_rows))
    return Report("ig-pipeline", "Instagram pipeline", as_of_text, kind, (), [],
                  ["Opaque customer references only; this report sends no messages."], sections, "as_of")


def repeat_rate(period):
    period_bounds(period)
    kind = DatasetSettings.load().dataset_kind
    paid_dates = defaultdict(list)
    for deal in _deals(kind):
        if deal.status in PAID and deal.paid_at:
            paid_dates[deal.customer_ref].append((deal.deal_id, deal.paid_at))
    cohort = {customer: rows for customer, rows in paid_dates.items()
              if min(day for _deal, day in rows).strftime("%Y-%m") == period}
    denominator = len(cohort)
    repeats = sum(len({deal for deal, _day in rows}) >= 2 for rows in cohort.values())
    columns = (Column("cohort", "First-paid cohort", False), Column("customers", "Customers paid"),
               Column("repeat_customers", "Customers with 2+ deals"), Column("rate", "Repeat rate"))
    rate = (known(Decimal(repeats) * 100 / denominator, period, kind, unit="percent") if denominator else
            absent(period, kind, "zero customers in denominator", unit="percent"))
    rows = [{"cohort": period, "customers": known(denominator, period, kind, unit="customers"),
             "repeat_customers": known(repeats, period, kind, unit="customers"), "rate": rate}]
    return Report("repeat-rate", "Repeat rate — Instagram only", period, kind, columns, rows,
                  ["Instagram only — Etsy has no customer_ref yet."])


def open_pos(as_of_text):
    """Open commitments by supplier and SKU. A PO is a commitment, not a ledger balance."""
    as_of = _as_date(as_of_text)
    kind = DatasetSettings.load().dataset_kind
    columns = (Column("supplier", "Supplier", False), Column("sku", "SKU", False),
               Column("po", "PO", False), Column("status", "Status", False),
               Column("pieces", "Pieces on order"), Column("committed", "Committed NT$ excl. tax"),
               Column("target", "Target date", False), Column("days", "Days to target"))
    lines = (PurchaseOrderLine.objects.filter(dataset_kind=kind, po__status__in=["draft", "sent", "acknowledged"])
             .select_related("po__supplier").order_by("po__supplier__supplier_ref", "product_id",
                                                      "po__po_number", "line_no"))

    def row(line):
        po = line.po
        return {"supplier": po.supplier.supplier_ref, "sku": line.product_id, "po": po.po_number,
                "status": po.status, "pieces": known(line.qty_pieces, as_of_text, kind, unit="pcs"),
                "committed": known(line.line_total_twd, as_of_text, kind),
                "target": po.target_delivery_date.isoformat(),
                "days": known((po.target_delivery_date - as_of).days, as_of_text, kind, unit="days")}

    def total(rows, label):
        return {"supplier": "TOTAL", "sku": "", "po": "", "status": label,
                "pieces": known(sum((r["pieces"].amount for r in rows), Decimal(0)), as_of_text, kind, unit="pcs"),
                "committed": known(sum((r["committed"].amount for r in rows), Decimal(0)), as_of_text, kind),
                "target": "", "days": absent(as_of_text, kind, "a total has no single target date", unit="days")}

    committed = [row(line) for line in lines if line.po.status in {"sent", "acknowledged"}]
    drafts = [row(line) for line in lines if line.po.status == "draft"]
    sections = (ReportSection("Open commitments (sent or acknowledged)", columns,
                              committed + [total(committed, "committed")]),
                ReportSection("Drafts — not committed", columns, drafts + [total(drafts, "draft, not committed")]))
    return Report("open-pos", "Open purchase orders", as_of_text, kind, (), [],
                  ["Committed = PO lines at sent or acknowledged. Drafts are listed apart and never counted "
                   "as committed. Cancelled POs are excluded.",
                   "NT$ is line_total_twd: qty_pieces x unit_price_twd + setup_charge_twd, excluding business "
                   "tax (open question P-5).",
                   "A PO is a commitment, not a liability. Nothing here is posted; receiving is G-2.",
                   "Days to target is negative when the target date has passed."],
                  sections, "as_of")


def po_exceptions(as_of_text):
    """I-1: every receipt or invoice that has not posted is listed here. Nothing waits silently."""
    from ops.receiving import evaluate_match, event_key

    as_of = _as_date(as_of_text)
    kind = DatasetSettings.load().dataset_kind
    posted = set(LedgerEvent.objects.filter(event_type="po.received", dataset_kind=kind)
                 .values_list("idempotency_key", flat=True))
    receipts = (GoodsReceipt.objects.filter(dataset_kind=kind, received_on__lte=as_of)
                .select_related("po").order_by("po__po_number", "receipt_no"))
    invoices = {(invoice.po_id, invoice.receipt_no): invoice for invoice in SupplierInvoice.objects.filter(
        dataset_kind=kind, invoice_date__lte=as_of).select_related("po")}
    received_columns = (Column("po", "PO", False), Column("receipt", "Receipt", False),
                        Column("received_on", "Received on", False), Column("line", "PO line", False),
                        Column("sku", "SKU", False), Column("good", "Good pieces"),
                        Column("damaged", "Damaged pieces"), Column("days", "Days waiting"))
    invoiced_columns = (Column("po", "PO", False), Column("receipt", "Receipt named", False),
                        Column("invoice", "Invoice", False), Column("invoice_date", "Invoice date", False),
                        Column("total", "Invoice total NT$"), Column("days", "Days waiting"))
    refused_columns = (Column("po", "PO", False), Column("receipt", "Receipt", False),
                       Column("invoice", "Invoice", False), Column("reason", "Why nothing posted", False))
    received_rows, refused_rows, receipt_keys = [], [], set()
    for receipt in receipts:
        receipt_keys.add((receipt.po_id, receipt.receipt_no))
        if event_key(receipt) in posted:
            continue
        invoice = invoices.get((receipt.po_id, receipt.receipt_no))
        if invoice is None:
            for line in receipt.lines.order_by("line_no"):
                received_rows.append({
                    "po": receipt.po.po_number, "receipt": receipt.receipt_no,
                    "received_on": receipt.received_on.isoformat(), "line": str(line.line_no),
                    "sku": line.product_id, "good": known(line.qty_pieces_good, as_of_text, kind, unit="pcs"),
                    "damaged": known(line.qty_pieces_damaged, as_of_text, kind, unit="pcs"),
                    "days": known((as_of - receipt.received_on).days, as_of_text, kind, unit="days")})
            continue
        for reason in evaluate_match(receipt, invoice).problems or [
                "matched but not posted; post the po.received event"]:
            refused_rows.append({"po": receipt.po.po_number, "receipt": receipt.receipt_no,
                                 "invoice": invoice.invoice_no, "reason": reason})
    invoiced_rows = [{"po": invoice.po.po_number, "receipt": invoice.receipt_no, "invoice": invoice.invoice_no,
                      "invoice_date": invoice.invoice_date.isoformat(),
                      "total": known(invoice.invoice_total_twd, as_of_text, kind),
                      "days": known((as_of - invoice.invoice_date).days, as_of_text, kind, unit="days")}
                     for key, invoice in sorted(invoices.items(), key=lambda item: item[1].invoice_no)
                     if key not in receipt_keys]
    sections = (ReportSection("Received, not invoiced", received_columns, received_rows),
                ReportSection("Invoiced, not received", invoiced_columns, invoiced_rows),
                ReportSection("Refused matches", refused_columns, refused_rows))
    return Report("po-exceptions", "Purchase exceptions", as_of_text, kind, (), [],
                  ["po.received posts only on a three-way match: a sent or acknowledged PO, a goods receipt, "
                   "and a supplier invoice for that receipt that agree (catalogue G.3.3).",
                   "Every row here has posted nothing. A refused match names its reason; nothing is absorbed.",
                   "Documents dated after the as-of date are not shown."],
                  sections, "as_of")


def landed_cost(as_of_text):
    """Per PO line received: pieces, landed value and how it was built (catalogue G.3, G.5)."""
    from ops.receiving import event_key, invoice_for, value_pair

    as_of = _as_date(as_of_text)
    kind = DatasetSettings.load().dataset_kind
    posted = set(LedgerEvent.objects.filter(event_type="po.received", dataset_kind=kind,
                                            posted_entry_id__isnull=False)
                 .values_list("idempotency_key", flat=True))
    columns = (Column("po", "PO", False), Column("receipt", "Receipt", False), Column("line", "PO line", False),
               Column("sku", "SKU", False), Column("account", "Account", False),
               Column("good", "Good pieces"), Column("damaged", "Damaged, not credited"),
               Column("line_amount", "Line amount NT$"), Column("setup", "of which setup NT$"),
               Column("freight", "Supplier freight share NT$"), Column("tax", "Non-creditable tax share NT$"),
               Column("landed", "Landed total NT$"), Column("per_piece", "Landed per piece"),
               Column("to_5121", "Damaged to 5121 NT$"), Column("to_stock", "Good to stock NT$"))
    rows = []
    for receipt in (GoodsReceipt.objects.filter(dataset_kind=kind, received_on__lte=as_of)
                    .select_related("po").order_by("po__po_number", "receipt_no")):
        if event_key(receipt) not in posted:
            continue
        values, _payload = value_pair(receipt, invoice_for(receipt))
        period = receipt.received_on.strftime("%Y-%m")
        for value in values:
            rows.append({
                "po": receipt.po.po_number, "receipt": receipt.receipt_no, "line": str(value.line_no),
                "sku": value.sku, "account": value.inventory_account,
                "good": known(value.qty_good, period, kind, unit="pcs"),
                "damaged": known(value.qty_damaged, period, kind, unit="pcs"),
                "line_amount": known(value.line_amount, period, kind), "setup": known(value.setup, period, kind),
                "freight": known(value.freight_share, period, kind), "tax": known(value.tax_share, period, kind),
                "landed": known(value.landed, period, kind),
                "per_piece": known(value.per_piece, period, kind, unit="TWD/pc"),
                "to_5121": known(value.damaged_value, period, kind),
                "to_stock": known(value.good_value, period, kind)})
    return Report("landed-cost", "Landed cost by PO line", as_of_text, kind, columns, rows,
                  ["Landed = line amount (pieces invoiced x unit price + setup, R-1.1) + share of supplier-billed "
                   "freight + share of non-creditable tax, both by line value; the remainder of each allocation "
                   "goes to the highest PO line number on the receipt (G.5.2, G.5.4).",
                   "Damaged value = landed x damaged / (good + damaged), half-up 4 dp; good = landed - damaged "
                   "(G.5.3). Per piece is landed / (good + damaged), shown for reading only; it is never "
                   "multiplied back.",
                   "Credited damaged pieces were not invoiced and appear nowhere. Only posted receipts are listed; "
                   "see Purchase exceptions for the rest."])


REPORT_BUILDERS = {"ig-pipeline": ig_pipeline, "repeat-rate": repeat_rate, "open-pos": open_pos,
                   "po-exceptions": po_exceptions, "landed-cost": landed_cost}
