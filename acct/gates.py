"""Executable G-1 through G-5 checks; missing evidence never passes."""
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from acct.models import AcctManualEntry, Account, ClearingCause, JournalLine
from acct.reporting import (CONTRIBUTION_ACCOUNTS, _net, contribution_skus, dataset_kind,
                            order_results, period_bounds, quantize, TAIPEI)
from ops.models import InventoryMove, LedgerEvent
from django.db.models import Q

RAILS = ("1191", "1192", "1193")
INVENTORY = ("1231", "1232", "1233")
CHART = Path(__file__).resolve().parent / "data" / "coa_snapshot.json"


@dataclass(frozen=True)
class GateResult:
    gate: str
    status: str
    reason: str
    details: dict

    def record(self):
        return asdict(self)


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


def g1(period):
    _, end = period_bounds(period)
    counts = g1_unposted_counts(end)
    failed = any(counts.values())
    return GateResult("G-1", "FAIL" if failed else "PASS",
                      "unposted or errored facts in unscoped event streams" if failed else
                      "both event streams posted without errors", counts)


def business_days(start, end):
    """Weekdays after source date through as-of date; no holiday calendar is supplied."""
    day = start + timedelta(days=1)
    count = 0
    while day <= end:
        count += day.weekday() < 5
        day += timedelta(days=1)
    return count


def settlement_aging(period):
    """FIFO open items in each rail, retaining source date and named cause."""
    _, end = period_bounds(period)
    kind = dataset_kind()
    cutoff = end.date() - timedelta(days=1)
    causes = {cause.line_id: cause for cause in ClearingCause.objects.all()}
    items = []
    for account in RAILS + ("2205",):
        lines = JournalLine.objects.filter(account_id=account, entry__dataset_kind=kind,
            entry__occurred_at__lt=end).select_related("entry").order_by("entry__occurred_at", "pk")
        debits, credits = [], []
        for line in lines:
            balance = line.debit - line.credit
            opposite = credits if balance > 0 else debits
            while balance and opposite:
                first = opposite[0]
                used = min(abs(balance), abs(first["amount"]))
                balance += -used if balance > 0 else used
                first["amount"] += used if first["amount"] < 0 else -used
                if not first["amount"]:
                    opposite.pop(0)
            if balance:
                (debits if balance > 0 else credits).append({"line": line, "amount": balance})
        for item in debits + credits:
            line = item["line"]
            cause = causes.get(line.pk)
            named = cause and cause.cause.strip() and cause.evidence_ref.strip()
            items.append({"account": account, "line_id": line.pk,
                          "occurred_at": line.entry.occurred_at.isoformat(),
                          "open_twd": str(quantize(item["amount"])),
                          "business_days": business_days(line.entry.occurred_at.astimezone(TAIPEI).date(), cutoff),
                          "cause": cause.cause if named else None,
                          "evidence_ref": cause.evidence_ref if named else None})
    tax_items = [item for item in items if item["account"] == "2205"]
    rail_items = [item for item in items if item["account"] in RAILS]
    total = sum((Decimal(item["open_twd"]) for item in rail_items), Decimal(0))
    return {"period": period, "items": rail_items, "tax_items": tax_items,
            "total_twd": str(quantize(total)),
            "calendar_basis": "Monday-Friday; public-holiday calendar not supplied"}


def g2(period):
    _, end = period_bounds(period)
    kind = dataset_kind()
    aging = settlement_aging(period)
    tax = _net(JournalLine.objects.filter(account_id="2205", entry__dataset_kind=kind,
                                          entry__occurred_at__lt=end), ["2205"], direction="credit")
    old = [item for item in aging["items"] if item["business_days"] > 15 and not item["cause"]]
    details = {"aging": aging, "unexplained_over_15_business_days": len(old), "account_2205_twd": str(tax)}
    source = LedgerEvent.objects.filter(event_type="settlement.received", dataset_kind=kind,
        occurred_at__lt=end, posted_entry_id__isnull=False, posting_error__isnull=True).exists()
    if not source:
        return GateResult("G-2", "NOT_RUNNABLE", "Q-1 OPEN: no posted TWD settlement source; aging cannot be certified", details)
    if old or tax != 0:
        return GateResult("G-2", "FAIL", "unexplained item over 15 business days or 2205 nonzero", details)
    return GateResult("G-2", "PASS", "rail aging explained and 2205 exactly zero", details)


def g3(period):
    start, end = period_bounds(period)
    kind = dataset_kind()
    lines = list(JournalLine.objects.filter(account_id__in=INVENTORY, entry__dataset_kind=kind,
                                             entry__occurred_at__lt=end))
    moves = list(InventoryMove.objects.filter(dataset_kind=kind, occurred_at__lt=end))
    skus = sorted({move.product_id for move in moves} | {line.sku for line in lines if line.sku})
    gaps = []
    if not skus:
        gaps.append("no sourced opening inventory count or valued movements")
    if any(not line.sku for line in lines):
        gaps.append("untagged inventory GL value in 1231/1232/1233")
    rows = []
    for sku in skus:
        count = LedgerEvent.objects.filter(event_type="inventory.opening_counted", dataset_kind=kind,
            occurred_at__lte=start, posted_entry_id__isnull=False, posting_error__isnull=True,
            payload__sku=sku).order_by("-occurred_at").first()
        sku_moves = [move for move in moves if move.product_id == sku]
        sku_lines = [line for line in lines if line.sku == sku]
        opening_moves = [move for move in sku_moves if move.kind == "opening"]
        if not count or len(opening_moves) != 1:
            gaps.append(f"{sku}: posted opening count and move missing")
        elif Decimal(str(count.payload.get("qty", "0"))) != Decimal(opening_moves[0].qty_delta_packs):
            gaps.append(f"{sku}: opening count quantity disagrees with sourced move")
        if any(move.value_delta_twd is None for move in sku_moves):
            gaps.append(f"{sku}: ops movement valuation missing")
        if any(line.qty_delta_packs is None for line in sku_lines):
            gaps.append(f"{sku}: independent journal quantity missing")
        ops_qty = sum((Decimal(move.qty_delta_packs) for move in sku_moves), Decimal(0))
        gl_qty = sum((line.qty_delta_packs or Decimal(0) for line in sku_lines), Decimal(0))
        ops_value = sum((move.value_delta_twd or Decimal(0) for move in sku_moves), Decimal(0))
        gl_value = _net(sku_lines, INVENTORY)
        rows.append({"sku": sku, "ops_packs": str(ops_qty), "gl_packs": str(gl_qty),
                     "ops_twd": str(quantize(ops_value)), "gl_twd": str(gl_value)})
    if gaps:
        return GateResult("G-3", "NOT_RUNNABLE", "; ".join(dict.fromkeys(gaps)), {"rows": rows})
    mismatches = [row for row in rows if Decimal(row["ops_packs"]) != Decimal(row["gl_packs"])
                  or Decimal(row["ops_twd"]) != Decimal(row["gl_twd"])]
    return GateResult("G-3", "FAIL" if mismatches else "PASS",
                      "quantity or value differs from GL with zero tolerance" if mismatches else
                      "SKU quantity and value tie exactly", {"rows": rows, "mismatch_count": len(mismatches)})


def _gross_shares(total, weights):
    """Independent G-4 gross-revenue-share calculation; last SKU takes residue."""
    weights = sorted(weights.items())
    denominator = sum((weight for _, weight in weights), Decimal(0))
    if denominator <= 0:
        return None
    left = quantize(total)
    shares = {}
    for sku, weight in weights[:-1]:
        shares[sku] = quantize(Decimal(total) * weight / denominator)
        left -= shares[sku]
    shares[weights[-1][0]] = quantize(left)
    return shares


def g4(period):
    start, end = period_bounds(period)
    kind = dataset_kind()
    results, _ = order_results(period)
    if not results:
        return GateResult("G-4", "NOT_RUNNABLE", "no dispatched orders with contribution evidence", {})
    if any(result.contribution.amount is None for result in results):
        return GateResult("G-4", "NOT_RUNNABLE", "one or more contribution inputs are ABSENT", {})
    lines = list(JournalLine.objects.filter(entry__dataset_kind=kind, entry__occurred_at__gte=start,
                                             entry__occurred_at__lt=end, account_id__in=CONTRIBUTION_ACCOUNTS))
    ledger_total = quantize(sum((line.credit - line.debit for line in lines), Decimal(0)))
    order_total = quantize(sum((result.contribution.amount for result in results), Decimal(0)))
    expected_sku = defaultdict(Decimal)
    for result in results:
        weights = defaultdict(Decimal)
        for line in result.order.lines.all():
            weights[line.product_id] += Decimal(line.qty_packs * line.unit_price_minor)
        for name, figure in result.parts.items():
            if name == "cogs":
                continue
            shares = _gross_shares(figure.amount, weights)
            if shares is None or sum(shares.values(), Decimal(0)) != figure.amount:
                return GateResult("G-4", "FAIL", "P-4 allocation does not sum to header", {})
            sign = 1 if name in ("product", "shipping") else -1
            for sku, share in shares.items():
                expected_sku[sku] += sign * share
        events = LedgerEvent.objects.filter(event_type="order.cogs_relieved", entity_table="ops.order",
            entity_id=result.order.pk, dataset_kind=kind)
        for event in events:
            for line in JournalLine.objects.filter(entry_id=event.posted_entry_id, account_id="5111"):
                if not line.sku:
                    return GateResult("G-4", "NOT_RUNNABLE", "COGS lacks SKU attribution", {})
                expected_sku[line.sku] -= line.debit - line.credit
    actual_sku = {row["sku"]: row["contribution"].amount for row in contribution_skus(period).rows}
    bad_sku = sorted(sku for sku, amount in expected_sku.items()
                     if actual_sku.get(sku) is None or quantize(amount) != actual_sku[sku])
    bad = order_total != ledger_total or bad_sku or set(expected_sku) != set(actual_sku)
    return GateResult("G-4", "FAIL" if bad else "PASS",
                      "order/P&L or gross-share SKU allocation differs" if bad else
                      "orders, SKU allocations and period P&L tie exactly",
                      {"orders_twd": str(order_total), "ledger_twd": str(ledger_total), "sku_mismatches": bad_sku})


def g5(period):
    _, end = period_bounds(period)
    kind = dataset_kind()
    rows = json.loads(CHART.read_text(encoding="utf-8"))["rows"]
    names = [(str(row["account_code"]), str(row["account_name_en"])) for row in rows]
    names += list(Account.objects.values_list("code", "name_en"))
    bad_accounts = sorted({code for code, name in names if re.search(r"suspense|rounding|difference", name, re.I)})
    bad_lines, bad_estimates = [], []
    estimated_entries = set(AcctManualEntry.objects.filter(occurred_at__lt=end, basis="estimate",
        posted_entry_id__isnull=False).values_list("posted_entry_id", flat=True))
    for event in LedgerEvent.objects.filter(dataset_kind=kind, occurred_at__lt=end,
                                             posted_entry_id__isnull=False):
        if event.payload.get("basis") == "estimate":
            estimated_entries.add(event.posted_entry_id)
    open_freight_entries = set()
    accruals = LedgerEvent.objects.filter(dataset_kind=kind, event_type="order.ship_cost_accrued",
        occurred_at__lt=end, posted_entry_id__isnull=False)
    for accrual in accruals:
        invoiced = LedgerEvent.objects.filter(dataset_kind=kind, event_type="order.ship_cost_invoiced",
            entity_table=accrual.entity_table, entity_id=accrual.entity_id,
            occurred_at__lt=end, posted_entry_id__isnull=False).exists()
        if not invoiced:
            open_freight_entries.add(accrual.posted_entry_id)
    for line in JournalLine.objects.filter(entry__dataset_kind=kind, entry__occurred_at__lt=end):
        memo = line.memo or ""
        if re.search(r"to balance|difference|adjust", memo, re.I) and not line.source_ref:
            bad_lines.append(line.pk)
        needs_basis = ("[ESTIMATE]" in memo or line.entry_id in estimated_entries
                       or line.entry_id in open_freight_entries)
        if needs_basis and not ("[ESTIMATE]" in memo and re.search(r"\bbasis:\s*\S", memo, re.I)):
            bad_estimates.append(line.pk)
    details = {"prohibited_accounts": bad_accounts, "unreferenced_adjustment_lines": bad_lines,
               "estimates_without_stated_basis": bad_estimates}
    bad = any(details.values())
    return GateResult("G-5", "FAIL" if bad else "PASS",
                      "suspense, difference, unreferenced adjustment or unsupported estimate" if bad else
                      "no plug account, unreferenced adjustment or unsupported estimate", details)


GATES = (g1, g2, g3, g4, g5)


def diagnostic_results(period):
    """Read-only diagnostics; a close itself stops at the first non-PASS gate."""
    return [gate(period) for gate in GATES]
