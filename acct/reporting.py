"""Read-only Slice C reports. Missing evidence stays missing through every sum."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from acct.models import AcctManualEntry, JournalEntry, JournalLine
from core.models import DatasetSettings
from ops.models import InventoryMove, LedgerEvent, Order, Product

CENTI = Decimal("0.0001")
TAIPEI = ZoneInfo("Asia/Taipei")
DANGER_TWD = Decimal("200")
INVENTORY_ACCOUNTS = ("1231", "1232", "1233")
FEE_ACCOUNTS = ("6111", "6112", "6113", "6114")
AD_ACCOUNTS = {"etsy": "6141", "meta": "6142", "other": "6143"}
CONTRIBUTION_ACCOUNTS = ("4111", "4112", "4181", "4182", "4191", "6111", "6112", "6113",
                         "6114", "6116", "6131", "6132", "5111", "5114")


def quantize(value):
    return Decimal(value).quantize(CENTI, rounding=ROUND_HALF_UP)


def period_bounds(period):
    if len(period) != 7 or period[4] != "-" or not period[:4].isdigit() or not period[5:].isdigit():
        raise ValueError("period must be YYYY-MM")
    year, month = int(period[:4]), int(period[5:])
    if not 1 <= month <= 12:
        raise ValueError("period month must be 01–12")
    start = datetime(year, month, 1, tzinfo=TAIPEI)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=TAIPEI)
    return start, end


@dataclass(frozen=True)
class Figure:
    amount: Decimal | None
    dataset_kind: str
    cost_basis: str
    source_period: str
    reason: str = ""
    estimate: bool = False
    unit: str = "TWD"

    def __post_init__(self):
        if self.cost_basis not in ("actual", "provisional", "absent"):
            raise ValueError("invalid cost_basis")
        if self.amount is None and self.cost_basis != "absent":
            raise ValueError("missing amount must have absent basis")
        if self.amount is not None and self.cost_basis == "absent":
            raise ValueError("absent basis cannot carry a number")
        if self.amount is not None:
            object.__setattr__(self, "amount", quantize(self.amount))

    def display(self):
        if self.amount is None:
            return f"ABSENT — {self.reason}"
        amount = f"NT${self.amount:,.2f}" if self.unit == "TWD" else f"{self.amount:,.0f} {self.unit}"
        if self.cost_basis == "provisional":
            banner = "PROVISIONAL COST BASIS — NOT ACTUAL"
            if self.estimate:
                banner += " [ESTIMATE]"
            return f"{amount} {banner}: {self.reason or 'source basis is provisional'}"
        return amount


def known(value, period, kind, *, basis="actual", reason="", estimate=False, unit="TWD"):
    return Figure(quantize(value), kind, basis, period, reason, estimate, unit)


def absent(period, kind, reason, *, unit="TWD"):
    return Figure(None, kind, "absent", period, reason, unit=unit)


def combine(parts, period, kind, *, signs=None):
    parts = list(parts)
    unit = parts[0].unit if parts else "TWD"
    if any(part.unit != unit for part in parts):
        raise ValueError("cannot combine figures with different units")
    missing = [part.reason for part in parts if part.amount is None]
    if missing:
        return absent(period, kind, "; ".join(dict.fromkeys(missing)), unit=unit)
    signs = list(signs) if signs is not None else [1] * len(parts)
    value = sum((part.amount * sign for part, sign in zip(parts, signs)), Decimal(0))
    provisional = [part for part in parts if part.cost_basis == "provisional"]
    reason = "; ".join(dict.fromkeys(part.reason for part in provisional if part.reason))
    return known(value, period, kind, basis="provisional" if provisional else "actual",
                 reason=reason, estimate=any(part.estimate for part in provisional), unit=unit)


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    figure: bool = True


@dataclass
class Report:
    slug: str
    title: str
    period: str
    dataset_kind: str
    columns: tuple[Column, ...]
    rows: list[dict]
    notes: list[str] = field(default_factory=list)

    @property
    def cost_basis(self):
        figures = [row[column.key] for row in self.rows for column in self.columns
                   if column.figure and isinstance(row.get(column.key), Figure)]
        if any(fig.cost_basis == "absent" for fig in figures) or not figures:
            return "absent"
        if any(fig.cost_basis == "provisional" for fig in figures):
            return "provisional"
        return "actual"


def dataset_kind():
    return DatasetSettings.load().dataset_kind


def _net(lines, accounts, *, direction="debit"):
    accounts = set(accounts)
    value = sum((line.debit - line.credit for line in lines if line.account_id in accounts), Decimal(0))
    return quantize(value if direction == "debit" else -value)


def _lines(event):
    if event is None or event.posted_entry_id is None or event.posting_error is not None:
        return None
    return list(JournalLine.objects.filter(entry_id=event.posted_entry_id))


def _events_for_order(order, event_type):
    return list(LedgerEvent.objects.filter(entity_table="ops.order", entity_id=order.pk,
                                          event_type=event_type, dataset_kind=order.dataset_kind).order_by("id"))


def _event_component(order, event_type, accounts, period, kind, *, direction="debit",
                     basis="actual", reason="", estimate=False, require=True):
    events = _events_for_order(order, event_type)
    if not events:
        return absent(period, kind, f"{event_type} evidence missing") if require else known(0, period, kind)
    all_lines = []
    for event in events:
        lines = _lines(event)
        if lines is None:
            return absent(period, kind, f"{event_type} unposted or errored")
        all_lines += lines
    return known(_net(all_lines, accounts, direction=direction), period, kind,
                 basis=basis, reason=reason, estimate=estimate)


def _allocate(total, weighted_ids):
    """Allocate exact TWD 0.0001 units; final ID receives the residual."""
    weighted_ids = sorted(weighted_ids)
    weights = {key: Decimal(str(weight)) for key, weight in weighted_ids}
    if not weights or sum(weights.values()) <= 0:
        return {}
    remaining = quantize(total)
    result = {}
    items = list(weights.items())
    for key, weight in items[:-1]:
        share = quantize(Decimal(total) * weight / sum(weights.values()))
        result[key] = share
        remaining -= share
    result[items[-1][0]] = quantize(remaining)
    return result


def _settlement_allocations(period, kind):
    """Reporting-only allocation of 6116, never a journal allocation."""
    start, end = period_bounds(period)
    amounts = defaultdict(Decimal)
    covered = set()
    unresolved = set()
    settlements = LedgerEvent.objects.filter(event_type="settlement.received", dataset_kind=kind, occurred_at__gte=start,
                                               occurred_at__lt=end)
    for event in settlements:
        ids = event.payload.get("covers_order_ids") or []
        if not ids:
            continue
        lines = _lines(event)
        if lines is None:
            unresolved.update(str(item) for item in ids)
            continue
        orders = list(Order.objects.filter(channel_order_id__in=ids, dataset_kind=kind))
        if len(orders) != len(set(str(item) for item in ids)):
            unresolved.update(str(item) for item in ids)
            continue
        weight = [(str(order.channel_order_id), order.gross_minor) for order in orders]
        spread = _net(lines, ["6116"])
        for order_id, share in _allocate(spread, weight).items():
            amounts[order_id] += share
            covered.add(order_id)
    return amounts, covered, unresolved


@dataclass
class OrderResult:
    order: Order
    parts: dict[str, Figure]
    contribution: Figure
    after_acquisition: Figure


def _blended_cac(period, kind, count):
    start, end = period_bounds(period)
    lines = list(JournalLine.objects.filter(entry__dataset_kind=kind,
                                            entry__occurred_at__gte=start, entry__occurred_at__lt=end,
                                            account_id__in=AD_ACCOUNTS.values()))
    if not lines:
        return absent(period, kind, "no advertising spend recorded")
    if count <= 0:
        return absent(period, kind, "no dispatched orders for CAC denominator")
    basis, reason, estimate = _basis_from_lines(lines)
    return known(_net(lines, AD_ACCOUNTS.values()) / count, period, kind,
                 basis=basis, reason=reason, estimate=estimate)


def order_results(period):
    start, end = period_bounds(period)
    kind = dataset_kind()
    orders = list(Order.objects.filter(dataset_kind=kind, shipment__status="dispatched", shipment__ship_date__gte=start.date(),
                                       shipment__ship_date__lt=end.date()).select_related("channel").order_by("pk"))
    cac = _blended_cac(period, kind, len(orders))
    spread, covered, unresolved = _settlement_allocations(period, kind)
    results = []
    for order in orders:
        if order.dataset_kind != kind:
            raise ValueError("mixed dataset kinds in report period")
        shipped = _events_for_order(order, "order.shipped")
        ship_lines = _lines(shipped[0]) if len(shipped) == 1 else None
        if ship_lines is None:
            product = absent(period, kind, "dispatched revenue entry missing or unposted")
            shipping = absent(period, kind, "dispatched revenue entry missing or unposted")
            discount = absent(period, kind, "dispatched revenue entry missing or unposted")
        else:
            product = known(_net(ship_lines, ["4111", "4112"], direction="credit"), period, kind)
            shipping = known(_net(ship_lines, ["4181", "4182"], direction="credit"), period, kind)
            discount = known(_net(ship_lines, ["4191"]), period, kind)
        fees = _event_component(order, "order.fees_assessed", FEE_ACCOUNTS, period, kind)
        cogs_events = _events_for_order(order, "order.cogs_relieved")
        cogs_basis = "actual" if cogs_events and all(e.payload.get("cost_basis") == "actual" for e in cogs_events) else "provisional"
        cogs_reason = "no verified landed cost/opening count; COGS basis is provisional" if cogs_basis != "actual" else ""
        cogs = _event_component(order, "order.cogs_relieved", ["5111"], period, kind,
                                basis=cogs_basis, reason=cogs_reason)
        packaging = _event_component(order, "order.cogs_relieved", ["5114"], period, kind,
                                     basis=cogs_basis, reason=cogs_reason)
        freight_invoices = _events_for_order(order, "order.ship_cost_invoiced")
        freight_accruals = _events_for_order(order, "order.ship_cost_accrued")
        freight_events = freight_invoices + freight_accruals
        if freight_invoices and all(_lines(e) is not None for e in freight_events):
            freight_lines = [line for e in freight_events for line in _lines(e)]
            freight = known(_net(freight_lines, ["6131"]), period, kind)
        elif freight_accruals and all(_lines(e) is not None for e in freight_accruals):
            freight = known(_net([line for e in freight_accruals for line in _lines(e)], ["6131"]),
                            period, kind, basis="provisional", reason="carrier invoice missing; freight accrued from estimate", estimate=True)
        else:
            freight = absent(period, kind, "actual outbound freight invoice missing")
        duty_events = _events_for_order(order, "order.duty_incurred")
        duty_invoices = _events_for_order(order, "order.duty_invoiced")
        if any(e.payload.get("duty_position") == "unknown" for e in duty_events):
            duty = absent(period, kind, "DDP/DDU duty position unknown")
        elif duty_events and all(e.payload.get("duty_position") == "DDU" and _lines(e) == [] for e in duty_events):
            duty = known(0, period, kind)
        elif duty_invoices and all(_lines(e) is not None for e in duty_events + duty_invoices):
            duty_lines = [line for e in duty_events + duty_invoices for line in _lines(e)]
            duty = known(_net(duty_lines, ["6132"]), period, kind)
        elif duty_events and all(_lines(e) is not None for e in duty_events):
            duty = known(_net([line for e in duty_events for line in _lines(e)], ["6132"]),
                         period, kind, basis="provisional", reason="duty invoice missing; DDP duty accrued", estimate=True)
        else:
            duty = absent(period, kind, "DDP/DDU evidence or duty invoice missing")
        order_ref = str(order.channel_order_id)
        if order_ref in unresolved:
            fx = absent(period, kind, "settlement coverage unresolved")
        elif order_ref in covered:
            fx = known(spread[order_ref], period, kind)
        else:
            fx = absent(period, kind, "TWD settlement and channel rate missing")
        parts = {"product": product, "shipping": shipping, "discount": discount,
                 "fees": fees, "fx": fx, "freight": freight, "duty": duty,
                 "cogs": cogs, "packaging": packaging}
        contribution = combine(parts.values(), period, kind,
                               signs=[1, 1, -1, -1, -1, -1, -1, -1, -1])
        after = combine([contribution, cac], period, kind, signs=[1, -1])
        results.append(OrderResult(order, parts, contribution, after))
    return results, cac


def contribution_orders(period):
    results, cac = order_results(period)
    kind = dataset_kind()
    columns = (Column("order", "Order", False), Column("channel", "Channel", False),
               Column("product", "Product revenue"), Column("shipping", "Shipping revenue"),
               Column("discount", "Seller discount"), Column("fees", "Etsy fees 6111–6114"),
               Column("fx", "Conversion 6116"), Column("freight", "Outbound freight"),
               Column("duty", "DDP duty"), Column("cogs", "Product COGS"),
               Column("packaging", "Packaging COGS"), Column("contribution", "Contribution"),
               Column("gap", "Gap vs NT$200"), Column("after", "After blended CAC"))
    rows = []
    for result in results:
        gap = combine([result.contribution, known(DANGER_TWD, period, kind)], period, kind, signs=[1, -1])
        rows.append({"order": result.order.channel_order_id, "channel": result.order.channel.code,
                     **result.parts, "contribution": result.contribution, "gap": gap,
                     "after": result.after_acquisition})
    if not rows:
        rows.append({"order": "ABSENT", "channel": "ABSENT", **{c.key: absent(period, kind, "no dispatched orders") for c in columns if c.figure}})
    start, end = period_bounds(period)
    ledger_lines = list(JournalLine.objects.filter(entry__dataset_kind=kind,
        entry__occurred_at__gte=start, entry__occurred_at__lt=end,
        account_id__in=CONTRIBUTION_ACCOUNTS))
    ledger_total = sum((line.credit - line.debit for line in ledger_lines), Decimal(0))
    # Revenue credits and expense credits both increase this signed contribution.
    if not results or not ledger_lines or any(result.contribution.amount is None for result in results):
        check = "UNPROVABLE — dispatched orders or posted contribution components missing"
    else:
        order_total = sum((result.contribution.amount for result in results), Decimal(0))
        check = "TIES" if quantize(order_total) == quantize(ledger_total) else "MISMATCH — order and period ledger totals differ"
    return Report("contribution-orders", "Contribution per order", period, kind, columns, rows,
                  ["Seller discounts (4191) reduce contribution so it agrees with net revenue.",
                   "6115 Listing Fee remains a period cost and is never allocated to orders.",
                   f"Reporting cross-check against period contribution accounts: {check}. This is not a close gate.",
                   f"Blended CAC per dispatched order: {cac.display()}"])


def _allocated_figure(fig, shares, key, period, kind):
    if fig.amount is None:
        return absent(period, kind, fig.reason)
    return known(shares[key], period, kind, basis=fig.cost_basis, reason=fig.reason, estimate=fig.estimate)


def contribution_skus(period):
    results, _ = order_results(period)
    kind = dataset_kind()
    by_sku = defaultdict(list)
    qtys = defaultdict(int)
    for result in results:
        lines = list(result.order.lines.all().order_by("pk"))
        weights = defaultdict(int)
        for line in lines:
            weights[line.product_id] += line.qty_packs * line.unit_price_minor
            qtys[line.product_id] += line.qty_packs
        if not weights or sum(weights.values()) <= 0:
            continue
        cogs_events = _events_for_order(result.order, "order.cogs_relieved")
        tagged = defaultdict(Decimal)
        has_untagged = False
        for event in cogs_events:
            for line in _lines(event) or []:
                if line.account_id == "5111":
                    if line.sku:
                        tagged[line.sku] += line.debit - line.credit
                    else:
                        has_untagged = True
        cogs_tags_complete = (result.parts["cogs"].amount is not None and not has_untagged
                              and set(tagged) == set(weights)
                              and quantize(sum(tagged.values(), Decimal(0))) == result.parts["cogs"].amount)
        for sku in sorted(weights):
            parts = {}
            for name, fig in result.parts.items():
                if name == "cogs":
                    if fig.amount is None:
                        parts[name] = absent(period, kind, fig.reason)
                    elif not cogs_tags_complete:
                        parts[name] = absent(period, kind, "SKU-tagged COGS does not cover the order's posted COGS")
                    else:
                        parts[name] = known(tagged[sku], period, kind, basis=fig.cost_basis, reason=fig.reason)
                else:
                    shares = _allocate(fig.amount, weights.items()) if fig.amount is not None else {}
                    parts[name] = _allocated_figure(fig, shares, sku, period, kind) if shares else absent(period, kind, fig.reason)
            contribution = combine(parts.values(), period, kind,
                                   signs=[1, 1, -1, -1, -1, -1, -1, -1, -1])
            by_sku[sku].append(contribution)
    columns = (Column("sku", "SKU", False), Column("qty", "Packs"),
               Column("orders", "Orders"), Column("contribution", "Total contribution"),
               Column("average", "Contribution per order"), Column("gap", "Per-order gap vs NT$200"))
    rows = []
    for sku, figures in by_sku.items():
        contribution = combine(figures, period, kind)
        average = (known(contribution.amount / len(figures), period, kind, basis=contribution.cost_basis,
                         reason=contribution.reason, estimate=contribution.estimate)
                   if contribution.amount is not None else absent(period, kind, contribution.reason))
        rows.append({"sku": sku, "qty": known(qtys[sku], period, kind, unit="packs"),
                     "orders": known(len(figures), period, kind, unit="orders"),
                     "contribution": contribution, "average": average,
                     "gap": combine([average, known(DANGER_TWD, period, kind)], period, kind, signs=[1, -1])})
    rows.sort(key=lambda row: (row["average"].amount is None,
                               -(row["average"].amount or Decimal(0)), row["sku"]))
    if rows and all(row["average"].amount is not None for row in rows):
        winner = f"Highest computed SKU contribution per order: {rows[0]['sku']} ({rows[0]['average'].display()})."
    else:
        winner = "Which SKU earns most: ABSENT — required costs or settlement evidence missing."
    if not rows:
        rows = [{"sku": "ABSENT", "qty": absent(period, kind, "no dispatched SKU lines", unit="packs"),
                 "orders": absent(period, kind, "no dispatched SKU lines", unit="orders"),
                 "contribution": absent(period, kind, "no dispatched SKU lines"),
                 "average": absent(period, kind, "no dispatched SKU lines"),
                 "gap": absent(period, kind, "no dispatched SKU lines")}]
    return Report("contribution-skus", "Contribution per SKU", period, kind, columns, rows,
                  [winner, "Order-level shipping, discounts and fees allocate by gross product revenue share in this query only; COGS stays SKU-tagged in the journal."])


def contribution_channels(period):
    results, _ = order_results(period)
    kind = dataset_kind()
    groups = defaultdict(list)
    for result in results:
        groups[result.order.channel.code].append(result.contribution)
    columns = (Column("channel", "Channel", False), Column("orders", "Dispatched orders"),
               Column("contribution", "Total contribution"), Column("average", "Contribution per order"),
               Column("gap", "Per-order gap vs NT$200"))
    rows = []
    for channel, figures in sorted(groups.items()):
        value = combine(figures, period, kind)
        average = (known(value.amount / len(figures), period, kind, basis=value.cost_basis,
                         reason=value.reason, estimate=value.estimate) if value.amount is not None
                   else absent(period, kind, value.reason))
        rows.append({"channel": channel, "orders": known(len(figures), period, kind, unit="orders"), "contribution": value,
                     "average": average,
                     "gap": combine([average, known(DANGER_TWD, period, kind)], period, kind, signs=[1, -1])})
    if not rows:
        rows.append({"channel": "ABSENT", "orders": absent(period, kind, "no dispatched orders", unit="orders"),
                     "contribution": absent(period, kind, "no dispatched orders"),
                     "average": absent(period, kind, "no dispatched orders"),
                     "gap": absent(period, kind, "no dispatched orders")})
    return Report("contribution-channels", "Contribution per channel", period, kind, columns, rows)


def _journal_basis(entry_ids):
    result = {}
    for event in LedgerEvent.objects.filter(posted_entry_id__in=entry_ids):
        if event.payload.get("cost_basis") == "provisional":
            result[event.posted_entry_id] = ("provisional", "source cost basis is provisional", False)
        elif event.payload.get("basis") == "estimate":
            result[event.posted_entry_id] = ("provisional", "source amount is estimated", True)
    for event in AcctManualEntry.objects.filter(posted_entry_id__in=entry_ids):
        if event.basis == "estimate":
            result[event.posted_entry_id] = ("provisional", "manual accrual is estimated", True)
    return result


def _basis_from_lines(lines):
    by_entry = _journal_basis({line.entry_id for line in lines})
    provisional = list(by_entry.values())
    if not provisional:
        return "actual", "", False
    return ("provisional", "; ".join(dict.fromkeys(item[1] for item in provisional)),
            any(item[2] for item in provisional))


def _statement(period, statement):
    start, end = period_bounds(period)
    kind = dataset_kind()
    entries = list(JournalEntry.objects.filter(occurred_at__lt=end,
        **({"occurred_at__gte": start} if statement == "PL" else {})))
    entry_ids = [entry.pk for entry in entries if entry.dataset_kind == kind and not entry.memo_only]
    basis_by_entry = _journal_basis(entry_ids)
    lines = list(JournalLine.objects.filter(entry_id__in=entry_ids, account__statement=statement).select_related("account"))
    by_account = defaultdict(list)
    for line in lines:
        by_account[line.account_id].append(line)
    columns = (Column("account", "Account", False), Column("type", "Type", False), Column("balance", "TWD amount"))
    rows = []
    for account_id, account_lines in sorted(by_account.items()):
        account = account_lines[0].account
        raw = sum((line.debit-line.credit for line in account_lines), Decimal(0))
        value = raw if account.normal_balance == "debit" else -raw
        provisional = [basis_by_entry[line.entry_id] for line in account_lines if line.entry_id in basis_by_entry]
        reason = "; ".join(dict.fromkeys(item[1] for item in provisional))
        rows.append({"account": f"{account_id} {account.name_en}", "type": account.type,
                     "balance": known(value, period, kind, basis="provisional" if provisional else "actual",
                                      reason=reason, estimate=any(item[2] for item in provisional))})
    if not rows:
        rows.append({"account": "ABSENT", "type": "ABSENT", "balance": absent(period, kind, "no posted ledger lines")})
    title = "Profit and loss" if statement == "PL" else "Balance sheet account balances"
    notes = ["Only posted journal lines are included. Unposted facts are not silently estimated."]
    if statement == "BS":
        notes.append("Balances are cumulative through period end; current earnings remain in P&L until a real close.")
    return Report("profit-loss" if statement == "PL" else "balance-sheet", title, period, kind, columns, rows, notes)


def profit_loss(period):
    return _statement(period, "PL")


def balance_sheet(period):
    return _statement(period, "BS")


def cac_report(period):
    start, end = period_bounds(period)
    kind = dataset_kind()
    orders = list(Order.objects.filter(dataset_kind=kind, shipment__status="dispatched", shipment__ship_date__gte=start.date(),
                                       shipment__ship_date__lt=end.date()))
    columns = (Column("channel", "Advertising channel", False), Column("spend", "Recorded ad spend"),
               Column("orders", "Attributed orders"), Column("cac", "CAC"))
    rows = []
    all_lines = list(JournalLine.objects.filter(entry__dataset_kind=kind,
                                                entry__occurred_at__gte=start, entry__occurred_at__lt=end,
                                                account_id__in=AD_ACCOUNTS.values()))
    for channel, code in AD_ACCOUNTS.items():
        selected = [line for line in all_lines if line.account_id == code]
        if selected:
            basis, reason, estimate = _basis_from_lines(selected)
            spend = known(_net(selected, [code]), period, kind, basis=basis, reason=reason, estimate=estimate)
        else:
            spend = absent(period, kind, f"no {channel} ad spend recorded")
        attributed = None  # Sales channel is not proof of acquisition attribution.
        if spend.amount is None:
            cac = absent(period, kind, spend.reason)
        elif not attributed:
            cac = absent(period, kind, f"{channel} acquisition-order attribution missing")
        else:
            cac = known(spend.amount / attributed, period, kind)
        rows.append({"channel": channel, "spend": spend,
                     "orders": absent(period, kind, f"{channel} acquisition attribution missing", unit="orders"),
                     "cac": cac})
    if all_lines:
        basis, reason, estimate = _basis_from_lines(all_lines)
        blended_spend = known(_net(all_lines, AD_ACCOUNTS.values()), period, kind,
                              basis=basis, reason=reason, estimate=estimate)
    else:
        blended_spend = absent(period, kind, "no advertising spend recorded")
    blended = _blended_cac(period, kind, len(orders))
    rows.append({"channel":"blended", "spend":blended_spend,
                 "orders":known(len(orders), period, kind, unit="orders"), "cac":blended})
    return Report("cac", "Customer acquisition cost", period, kind, columns, rows,
                  ["Channel CAC stays ABSENT until orders carry acquisition attribution; sales channel alone is insufficient."])


def inventory_roll_forward(period):
    start, end = period_bounds(period)
    kind = dataset_kind()
    columns = (Column("sku", "SKU", False), Column("opening", "Opening packs"),
               Column("received", "Received / returned packs"), Column("sold", "Sold packs"),
               Column("written_off", "Written-off packs"), Column("adjusted", "Adjusted packs"),
               Column("closing", "Calculated closing packs"),
               Column("ops_value", "Ops closing value"), Column("gl_value", "GL inventory value"),
               Column("identity", "Identity", False))
    rows = []
    product_ids = set(Product.objects.values_list("sku", flat=True))
    for sku in sorted(product_ids):
        counts = LedgerEvent.objects.filter(event_type="inventory.opening_counted", dataset_kind=kind, occurred_at__lte=start,
            posted_entry_id__isnull=False).order_by("-occurred_at")
        count = next(((event, row) for event in counts for row in event.payload.get("lines", [])
                      if row.get("sku") == sku), None)
        opening_moves = list(InventoryMove.objects.filter(product_id=sku, dataset_kind=kind, kind="opening",
                                                          occurred_at__lte=start).order_by("occurred_at"))
        if count is None or len(opening_moves) != 1:
            opening = absent(period, kind, "no posted opening inventory count", unit="packs")
            opening_value = absent(period, kind, "no sourced opening inventory value")
        else:
            count_qty = Decimal(str(count[1]["qty_packs"]))
            opening_move = opening_moves[0]
            later = InventoryMove.objects.filter(product_id=sku, dataset_kind=kind, occurred_at__gt=count[0].occurred_at,
                                                  occurred_at__lt=start).exclude(kind="opening")
            later = list(later)
            if opening_move.qty_delta_packs != count_qty:
                opening = absent(period, kind, "opening move disagrees with posted count", unit="packs")
            else:
                opening = known(count_qty + sum((m.qty_delta_packs for m in later), 0), period, kind, unit="packs")
            if opening_move.value_delta_twd is None or any(m.value_delta_twd is None for m in later):
                opening_value = absent(period, kind, "opening or prior movement valuation missing")
            else:
                opening_value = known(opening_move.value_delta_twd + sum((m.value_delta_twd for m in later), Decimal(0)), period, kind)
        moves = list(InventoryMove.objects.filter(product_id=sku, dataset_kind=kind, occurred_at__gte=start, occurred_at__lt=end))
        received_qty = sum(m.qty_delta_packs for m in moves if m.kind in ("received", "returned"))
        sold_qty = -sum(m.qty_delta_packs for m in moves if m.kind == "sold")
        written_qty = -sum(m.qty_delta_packs for m in moves if m.kind == "written_off")
        adjusted_qty = sum(m.qty_delta_packs for m in moves if m.kind == "adjusted")
        received = known(received_qty, period, kind, unit="packs")
        sold = known(sold_qty, period, kind, unit="packs")
        written = known(written_qty, period, kind, unit="packs")
        adjusted = known(adjusted_qty, period, kind, unit="packs")
        closing = (combine([opening, received, sold, written, adjusted],
                           period, kind, signs=[1, 1, -1, -1, 1]) if opening.amount is not None
                   else absent(period, kind, "opening count missing; identity unprovable", unit="packs"))
        ops_value = (known(opening_value.amount + sum((m.value_delta_twd for m in moves), Decimal(0)), period, kind)
                     if opening_value.amount is not None and all(m.value_delta_twd is not None for m in moves)
                     else absent(period, kind, "opening count or movement values missing"))
        gl_lines = list(JournalLine.objects.filter(sku=sku, entry__dataset_kind=kind, entry__occurred_at__lt=end,
                                                   account_id__in=INVENTORY_ACCOUNTS))
        gl_value = known(_net(gl_lines, INVENTORY_ACCOUNTS), period, kind) if gl_lines else absent(period, kind, "no SKU-tagged inventory ledger value")
        if opening.amount is None or gl_value.amount is None or ops_value.amount is None:
            identity = "UNPROVABLE — opening count, ops value or SKU ledger value missing"
        else:
            observed_qty = sum(InventoryMove.objects.filter(product_id=sku, dataset_kind=kind, occurred_at__lt=end)
                               .values_list("qty_delta_packs", flat=True))
            identity = "TIES" if closing.amount == observed_qty and ops_value.amount == gl_value.amount else "MISMATCH — quantity or value disagrees"
        rows.append({"sku":sku, "opening":opening, "received":received, "sold":sold,
                     "written_off":written, "adjusted":adjusted, "closing":closing, "ops_value":ops_value,
                     "gl_value":gl_value, "identity":identity})
    if not rows:
        rows.append({"sku":"ABSENT", "opening":absent(period, kind, "no opening inventory count", unit="packs"),
                     "received":known(0, period, kind, unit="packs"), "sold":known(0, period, kind, unit="packs"),
                     "written_off":known(0, period, kind, unit="packs"), "adjusted":known(0, period, kind, unit="packs"),
                     "closing":absent(period, kind, "opening count missing; identity unprovable", unit="packs"),
                     "ops_value":absent(period, kind, "opening count missing"),
                     "gl_value":absent(period, kind, "no inventory ledger value"), "identity":"UNPROVABLE — no opening count"})
    all_inventory = list(JournalLine.objects.filter(entry__dataset_kind=kind, entry__occurred_at__lt=end,
                                                    account_id__in=INVENTORY_ACCOUNTS))
    tagged = [line for line in all_inventory if line.sku]
    untagged = [line for line in all_inventory if not line.sku]
    if not all_inventory or untagged or any(row["identity"] != "TIES" for row in rows):
        status = "UNPROVABLE" if not all_inventory or untagged or any(row["identity"].startswith("UNPROVABLE") for row in rows) else "MISMATCH"
    else:
        gl_total = _net(all_inventory, INVENTORY_ACCOUNTS)
        tagged_total = _net(tagged, INVENTORY_ACCOUNTS)
        status = "TIES" if gl_total == tagged_total else "MISMATCH"
    subtotal = {key: combine([row[key] for row in rows], period, kind)
                for key in ("opening", "received", "sold", "written_off", "adjusted", "closing", "ops_value")}
    subtotal["gl_value"] = (known(_net(all_inventory, INVENTORY_ACCOUNTS), period, kind)
                            if all_inventory else absent(period, kind, "no inventory ledger value"))
    rows.append({"sku": "TOTAL", **subtotal, "identity": status})
    return Report("inventory", "Inventory roll-forward", period, kind, columns, rows,
                  [f"G-3 reporting identity: {status}.",
                   "Opening is never inferred from movements without a posted count. Unassigned packaging value prevents a SKU-to-GL tie."])


REPORT_BUILDERS = {
    "contribution-orders": contribution_orders,
    "contribution-skus": contribution_skus,
    "contribution-channels": contribution_channels,
    "profit-loss": profit_loss,
    "balance-sheet": balance_sheet,
    "cac": cac_report,
    "inventory": inventory_roll_forward,
}
