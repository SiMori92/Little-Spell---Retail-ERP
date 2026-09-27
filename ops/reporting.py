"""Read-only operational reports: the Instagram pipeline and open purchase orders."""

from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from acct.reporting import Column, Report, ReportSection, absent, known, period_bounds
from core.models import DatasetSettings
from ops.models import IgDeal, PurchaseOrderLine

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


REPORT_BUILDERS = {"ig-pipeline": ig_pipeline, "repeat-rate": repeat_rate, "open-pos": open_pos}
