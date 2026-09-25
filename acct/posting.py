"""Frozen v1.3 event catalogue binding. No catch-all or guessed amounts."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from functools import partial

from django.db import transaction
from django.conf import settings
from django.utils import timezone

from acct.models import Account, AcctManualEntry, FxRate, JournalEntry, JournalLine, MANUAL_EVENT_TYPES, WacPosition
from core.models import DatasetSettings
from ops.models import LedgerEvent, OPS_EVENT_TYPES, Order, InventoryMove

Q = Decimal("0.0001")


class PostingError(ValueError):
    pass


def money(value):
    try:
        d = Decimal(str(value)).quantize(Q, rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise PostingError("amount is missing or invalid") from exc
    if d < 0:
        raise PostingError("amount must be nonnegative")
    return d


def required(payload, key):
    value = payload.get(key)
    if value is None or value == "":
        raise PostingError(f"required payload field {key} is missing")
    return value


def amt(event, payload=None):
    if event.amount_minor is not None:
        return money(Decimal(event.amount_minor) / 100)
    return money(required(payload or event.payload, "amount"))


@dataclass(frozen=True)
class Leg:
    account: str
    debit: Decimal = Decimal(0)
    credit: Decimal = Decimal(0)
    txn_amount: Decimal | None = None
    txn_currency: str | None = None
    fx_rate: FxRate | None = None
    sku: str | None = None
    qty_delta_packs: Decimal | None = None


def dr(code, value, **kwargs):
    return Leg(str(code), debit=money(value), **kwargs)


def cr(code, value, **kwargs):
    return Leg(str(code), credit=money(value), **kwargs)


def pair(debit_code, credit_code, value):
    value = money(value)
    if not value:
        raise PostingError("zero-value journal entry")
    return [dr(debit_code, value), cr(credit_code, value)]


def difference(debit_code, credit_code, base, actual, variance_code):
    """Clear an accrual at its booked value and allocate the invoice variance."""
    base, actual = money(base), money(actual)
    lines = [dr(debit_code, base), cr(credit_code, actual)]
    if actual > base:
        lines.append(dr(variance_code, actual-base))
    elif base > actual:
        lines.append(cr(variance_code, base-actual))
    return lines


def public_fx(event):
    if event.currency == "TWD":
        return Decimal(1), None
    rate = FxRate.objects.filter(rate_date=event.occurred_at.astimezone(timezone.get_current_timezone()).date(), currency=event.currency, kind="public", source_event_key="").first()
    if rate is None:
        raise PostingError("transaction-date Bank of Taiwan public rate missing")
    return rate.rate, rate


def translated(event, amount=None):
    factor, rate = public_fx(event)
    return money((amount if amount is not None else amt(event)) * factor), rate


def standard(event, debit_code, credit_code):
    value, rate = translated(event)
    if rate:
        txn = amt(event)
        return [dr(debit_code, value, txn_amount=txn, txn_currency=event.currency, fx_rate=rate),
                cr(credit_code, value, txn_amount=txn, txn_currency=event.currency, fx_rate=rate)]
    return pair(debit_code, credit_code, value)


def placed(e):
    if e.payload.get("discount_funded_by") not in ("seller", "platform", "none"):
        raise PostingError("discount_funded_by missing")
    if e.entity_table != "ops.order":
        raise PostingError("order.placed must reference ops.order")
    order = Order.objects.get(pk=e.entity_id)
    rail_minor = e.amount_minor
    if rail_minor is None:
        raise PostingError("order.placed requires statement rail amount")
    expected = order.gross_minor - order.discount_minor if order.discount_funded_by == "seller" else order.gross_minor
    if rail_minor != expected:
        raise PostingError("rail amount contradicts discount funder; refuse both readings")
    rate, fx = public_fx(e)
    rail = money(Decimal(rail_minor) / 100 * rate)
    kwargs = {"txn_amount": money(Decimal(rail_minor) / 100), "txn_currency": e.currency, "fx_rate": fx} if fx else {}
    return [dr("1191", rail, **kwargs), cr("2211", rail, **kwargs)]


def fees(e):
    components = required(e.payload, "fee_components")
    required(e.payload, "channel_applied_fx_rate")
    fee_accounts = {"transaction_fee": "6111", "payment_processing_fee": "6112",
                    "offsite_ads_fee": "6113", "regulatory_operating_fee": "6114"}
    allowed = set(fee_accounts.values())
    rate, _ = public_fx(e)
    lines = []
    for item in components:
        code = fee_accounts.get(str(required(item, "code")), str(item["code"]))
        if code not in allowed:
            raise PostingError(f"unmapped original fee account {code}")
        value = money(Decimal(str(required(item, "amount"))) / 100 * rate)
        txn = money(Decimal(str(item["amount"])) / 100)
        kwargs = {"txn_amount": txn, "txn_currency": e.currency, "fx_rate": _} if _ else {}
        lines += [dr(code, value, **kwargs), cr("1191", value, **kwargs)]
    return lines


def shipped(e):
    order = Order.objects.get(pk=e.entity_id)
    ship_date = getattr(order.shipment, "ship_date", None)
    if not ship_date:
        raise PostingError("order.shipped requires ship_date")
    if order.dest_country == "TW":
        product_code, shipping_code = "4112", "4182"
    elif order.dest_country in ("US", "JP", "FR", "GB", "AU"):
        product_code, shipping_code = "4111", "4181"
    else:
        raise PostingError("tax_treatment unresolved for destination")
    original = LedgerEvent.objects.get(event_type="order.placed", entity_table="ops.order", entity_id=order.pk)
    factor, _ = public_fx(original)
    product = money(Decimal(sum(line.qty_packs * line.unit_price_minor for line in order.lines.all())) / 100 * factor)
    shipping = money(Decimal(order.shipping_minor + order.shipping_discount_minor) / 100 * factor)
    discount = money(Decimal(order.discount_minor) / 100 * factor)
    deposit = money(Decimal(original.amount_minor) / 100 * factor)
    lines = [dr("2211", deposit), cr(product_code, product)]
    if shipping:
        lines.append(cr(shipping_code, shipping))
    if discount:
        if order.discount_funded_by == "seller":
            if deposit != product + shipping - discount:
                raise PostingError("seller-funded discount conflicts with held deposit")
            lines.append(dr("4191", discount))
        elif order.discount_funded_by == "platform":
            if deposit != product + shipping:
                raise PostingError("platform-funded discount conflicts with held deposit")
        else:
            raise PostingError("discount funding unresolved")
    elif deposit != product + shipping:
        raise PostingError("held deposit differs from gross revenue")
    return lines


def cogs(e, reprint=False):
    order = Order.objects.get(pk=e.entity_id)
    if not order.shipment.ship_date:
        raise PostingError("COGS requires dispatch")
    if reprint and not e.payload.get("decisions_ref"):
        raise PostingError("reprint requires decisions_ref")
    lines = []
    for line in order.lines.all():
        sku = line.product_id
        qty = line.qty_packs
        position = WacPosition.objects.select_for_update().filter(pk=sku).first()
        if position is None or position.qty_packs < qty or position.qty_packs <= 0:
            raise PostingError(f"SKU {sku} has no sufficient weighted-average stock")
        onhand = InventoryMove.objects.filter(product_id=sku, occurred_at__lte=e.occurred_at).values_list("qty_delta_packs", flat=True)
        if sum(onhand) < 0:
            raise PostingError(f"SKU {sku} on-hand would be negative")
        value = money(Decimal(qty) * position.value_twd / position.qty_packs)
        lines += [dr("5111", value, sku=sku), cr("1231", value, sku=sku, qty_delta_packs=-Decimal(qty))]
    packaging = e.payload.get("packaging_twd")
    if packaging:
        lines += pair("5114", "1233", packaging)
    return lines


def ship_accrued(e):
    if e.payload.get("basis") == "estimate" and not e.payload.get("basis_note"):
        raise PostingError("freight estimate needs basis_note")
    return standard(e, "6131", "2191")


def ship_invoiced(e):
    if not e.payload.get("accrual_ref"):
        raise PostingError("freight invoice must match an accrual")
    value, _ = translated(e)
    return difference("2191", "2172", required(e.payload, "accrued_twd"), value, "6131")


def duty_incurred(e):
    position = required(e.payload, "duty_position")
    if position in ("DDU", "unknown"):
        return None
    if position != "DDP":
        raise PostingError("unknown duty_position")
    return standard(e, "6132", "2192")


def duty_invoiced(e):
    if not e.payload.get("accrual_ref"):
        raise PostingError("duty invoice must match an accrual")
    value, _ = translated(e)
    return difference("2192", e.payload.get("payable_account", "2172"), required(e.payload, "accrued_twd"), value, "6132")


def cancelled(e):
    phase = required(e.payload, "dispatch_phase")
    if phase not in ("pre", "post"):
        raise PostingError("dispatch_phase must be pre or post")
    return standard(e, "2211" if phase == "pre" else "4192", "1191")


def refunded(e):
    value, _ = translated(e)
    lines = pair("4192", "1191", value)
    for item in e.payload.get("fee_refunds", []):
        code = str(required(item, "original_account"))
        if code not in ("6111", "6112", "6113", "6114"):
            raise PostingError("refund fee must name original fee account")
        amount = money(required(item, "amount_twd"))
        lines += [dr("1191", amount), cr(code, amount)]
    return lines


def blocked_gateway(e):
    raise PostingError("1193 local gateway is RESERVED; payment route blocked")


def settlement(e):
    p = e.payload
    try:
        applied = Decimal(str(required(p, "channel_applied_fx_rate"))).quantize(Decimal("0.000001"))
    except Exception as exc:
        raise PostingError("channel_applied_fx_rate must be decimal(12,6)") from exc
    if applied <= 0:
        raise PostingError("channel_applied_fx_rate must be positive")
    source = required(p, "rate_source")
    if source not in ("derived", "stated"):
        raise PostingError("rate_source must be derived or stated")
    if e.currency != "TWD":
        raise PostingError("Etsy settlement must deposit TWD")
    usd = money(required(p, "usd_settled"))
    public = FxRate.objects.filter(rate_date=e.occurred_at.astimezone(timezone.get_current_timezone()).date(), currency="USD", kind="public", source_event_key="").first()
    if public is None:
        raise PostingError("settlement requires public USD rate")
    deposited = amt(e)
    if not deposited or not usd:
        raise PostingError("settlement amounts must be positive")
    if source == "derived" and (deposited / usd).quantize(Decimal("0.000001")) != applied:
        raise PostingError("derived channel rate does not match deposit / USD settled")
    carrying = money(usd * public.rate)
    spread = carrying - deposited
    if abs(spread) / deposited > settings.SETTLEMENT_SPREAD_TOLERANCE_FRACTION:
        raise PostingError("settlement rate spread exceeds provisional tolerance; escalate rate evidence")
    channel, _ = FxRate.objects.get_or_create(
        rate_date=e.occurred_at.astimezone(timezone.get_current_timezone()).date(),
        currency="USD", kind="channel", source_event_key=e.idempotency_key,
        defaults={"rate": applied, "rate_source": source, "evidence_ref": required(p, "rate_evidence_ref")},
    )
    if channel.rate != applied or channel.rate_source != source:
        raise PostingError("stored channel rate conflicts with event")
    lines = [dr("1121", deposited), cr("1191", carrying, txn_amount=usd, txn_currency="USD", fx_rate=public)]
    if spread > 0:
        lines.append(dr("6116", spread))
    elif spread < 0:
        lines.append(cr("6116", -spread))
    return lines


def settlement_reversed(e):
    original = money(required(e.payload, "original_carrying_twd"))
    bank = money(required(e.payload, "bank_reversal_twd"))
    fee = money(e.payload.get("reversal_fee_twd", 0))
    lines = [dr("1191", original), cr("1121", bank)]
    if fee:
        lines.append(dr("6181", fee))
    delta = bank - original - fee
    if delta > 0:
        lines.append(dr("6116", delta))
    elif delta < 0:
        lines.append(cr("6116", -delta))
    return lines


def po_received(e):
    p = e.payload
    components = required(p, "landed_components_twd")
    if set(components) != {"product", "packaging", "supplier", "freight", "duty", "in_transit"}:
        raise PostingError("PO landed components incomplete")
    c = {k: money(v) for k, v in components.items()}
    receipts = required(p, "sku_receipts")
    if money(sum(money(required(row, "landed_cost_twd")) for row in receipts)) != c["product"]:
        raise PostingError("SKU landed cost does not tie to product inventory debit")
    if any(money(required(row, "qty_packs")) <= 0 or not row.get("sku") for row in receipts):
        raise PostingError("PO receipt needs positive SKU quantities")
    lines = [dr("1231", row["landed_cost_twd"], sku=row["sku"],
                qty_delta_packs=money(row["qty_packs"])) for row in receipts]
    lines += [dr("1233", c["packaging"]), cr("2171", c["supplier"]), cr("2172", c["freight"]), cr("2192", c["duty"]), cr("1232", c["in_transit"])]
    return [x for x in lines if x.debit or x.credit]


def po_adjusted(e):
    p = e.payload
    onhand = money(required(p, "onhand_ratio"))
    if onhand > 1 or not p.get("lot_ref") or not p.get("sku"):
        raise PostingError("late PO cost needs known lot and on-hand ratio")
    value, _ = translated(e)
    onhand_amount = money(value * onhand)
    return [dr("1231", onhand_amount, sku=p["sku"]), dr("5112", value-onhand_amount, sku=p["sku"]), cr(p.get("payable_account", "2172"), value)]


def po_paid(e):
    if not e.payload.get("bank_ref"):
        raise PostingError("PO payment needs bank_ref")
    return standard(e, e.payload.get("payable_account", "2171"), e.payload.get("bank_account", "1121"))


def inventory_adjusted(e):
    if not e.payload.get("evidence_ref") or e.payload.get("qty") is None or not e.payload.get("sku"):
        raise PostingError("inventory adjustment needs count evidence, SKU and qty")
    position = WacPosition.objects.select_for_update().filter(pk=e.payload["sku"]).first()
    qty = money(e.payload["qty"])
    if position is None or position.qty_packs < qty or position.qty_packs <= 0:
        raise PostingError("inventory adjustment lacks sufficient SKU WAC stock")
    value = money(position.value_twd * qty / position.qty_packs)
    return [dr("5121", value, sku=e.payload["sku"]), cr(e.payload.get("inventory_account", "1231"), value,
            sku=e.payload["sku"], qty_delta_packs=-qty)]


def opening_counted(e):
    if LedgerEvent.objects.filter(event_type="inventory.opening_counted", dataset_kind=e.dataset_kind).exclude(pk=e.pk).exists():
        raise PostingError("opening count fires once per dataset")
    required(e.payload, "sku")
    value = money(money(required(e.payload, "qty")) * money(required(e.payload, "agreed_unit_cost_twd")))
    return [dr(e.payload.get("inventory_account", "1231"), value, sku=e.payload["sku"],
               qty_delta_packs=money(e.payload["qty"])), cr(e.payload.get("capital_account", "3111"), value)]


def cost_recorded(e):
    p = e.payload
    category = required(p, "category")
    if category == "platform_listing_fee":
        debit_code = "6115"
        if e.entity_table != "ops.etsystatementrow":
            raise PostingError("listing fee is a period cost from a statement row")
    elif category == "advertising":
        channel = required(p, "channel_attribution")
        debit_code = {"etsy": "6141", "meta": "6142", "other": "6143"}.get(channel)
        if debit_code is None:
            raise PostingError("unknown advertising channel")
    else:
        debit_code = {"rent":"6151", "software":"6161", "professional":"6162", "utilities":"6163", "wages":"6171", "bank_fee":"6181", "other":"6199"}.get(category)
        if debit_code is None:
            raise PostingError("unmapped cost category")
    settled = required(p, "settled_via")
    credit_code = {"etsy_rail":"1191", "payable":"2173", "bank":p.get("bank_account", "1121")}.get(settled)
    if credit_code is None:
        raise PostingError("unknown cost settlement route")
    value, _ = translated(e)
    future = money(p.get("future_period_twd", 0))
    if future > value:
        raise PostingError("future-period cost exceeds total")
    lines = [cr(credit_code, value)]
    if value - future:
        lines.append(dr(debit_code, value-future))
    if future:
        lines.append(dr(p.get("prepayment_account", "1261"), future))
    return lines


def manual(e):
    p = e.payload
    value = money(e.amount)
    t = e.event_type
    if t == "period.revalued":
        account = required(p, "revalued_account")
        if account in ("1231", "1232", "1233"):
            raise PostingError("inventory cannot be revalued")
        if not p.get("rate_source"):
            raise PostingError("revaluation rate source missing")
        return pair("7112", account, value) if p.get("direction") == "loss" else pair(account, "7112", value)
    if t == "period.accrued":
        if e.basis != "estimate" or not p.get("basis_note"):
            raise PostingError("accrual estimate needs basis_note")
        payable = required(p, "accrual_account")
        if payable not in ("2191", "2193", "2197"):
            raise PostingError("invalid accrual account")
        return pair(required(p, "expense_account"), payable, value)
    if t == "period.accrual_reversed":
        if not e.reverses_id or e.reverses.event_type != "period.accrued" or not e.reverses.posted_entry_id:
            raise PostingError("reversal needs posted original accrual")
        if AcctManualEntry.objects.filter(event_type=t, reverses=e.reverses).exclude(pk=e.pk).exists():
            raise PostingError("accrual already reversed")
        old = e.reverses
        if value != old.amount:
            raise PostingError("reversal amount differs from original")
        return pair(required(old.payload, "accrual_account"), required(old.payload, "expense_account"), value)
    if t == "tax.assessed":
        if not e.evidence_ref or not e.needs_prof_conf:
            raise PostingError("tax assessment needs voucher and professional confirmation flag")
        return pair("6182", "2194", value)
    if t == "tax.paid":
        if not e.evidence_ref:
            raise PostingError("tax payment needs voucher")
        return pair("2194", "1121", value)
    if t == "owner.funds_moved":
        return {"capital":lambda:pair("1121","3111",value), "drawings":lambda:pair("3211","1121",value), "loan":lambda:pair("1121","2281",value)}[required(p,"funds_type")]()
    raise PostingError(f"unhandled manual event type {t}")


OPS_RULES = {
    "order.placed": placed, "order.fees_assessed": fees, "order.shipped": shipped,
    "order.cogs_relieved": cogs, "order.ship_cost_accrued": ship_accrued,
    "order.ship_cost_invoiced": ship_invoiced, "order.duty_incurred": duty_incurred,
    "order.duty_invoiced": duty_invoiced, "order.reprint_issued": partial(cogs, reprint=True),
    "order.cancelled": cancelled, "order.refunded": refunded,
    "payment.received": blocked_gateway, "payment.refunded": blocked_gateway,
    "settlement.received": settlement, "settlement.reversed": settlement_reversed,
    "po.in_transit": partial(standard, debit_code="1232", credit_code="2171"),
    "po.received": po_received, "po.landed_cost_adjusted": po_adjusted,
    "po.paid": po_paid, "inventory.adjusted": inventory_adjusted,
    "inventory.opening_counted": opening_counted, "cost.recorded": cost_recorded,
}
MANUAL_RULES = {event_type: manual for event_type in MANUAL_EVENT_TYPES}
assert set(OPS_RULES) == set(OPS_EVENT_TYPES)
assert len(OPS_RULES) + len(MANUAL_RULES) == 28


def plan(event):
    rules = OPS_RULES if isinstance(event, LedgerEvent) else MANUAL_RULES
    rule = rules.get(event.event_type)
    if rule is None:
        raise PostingError(f"unhandled event type {event.event_type}")
    lines = rule(event)
    if lines is None:
        return None
    if not lines:
        raise PostingError("rule produced no journal lines")
    if any(not x.debit and not x.credit for x in lines):
        raise PostingError("zero journal line")
    if sum((x.debit - x.credit for x in lines), Decimal(0)) != 0:
        raise PostingError(f"rule {event.event_type} produced unbalanced TWD entry")
    return lines


def apply_wac(event, lines):
    """Move SKU quantity and value only after its balanced journal is inserted."""
    if not isinstance(event, LedgerEvent):
        return
    kind = event.event_type
    p = event.payload
    if kind in ("inventory.opening_counted", "po.received"):
        rows = ([{"sku": p["sku"], "qty_packs": p["qty"], "landed_cost_twd": lines[0].debit}]
                if kind == "inventory.opening_counted" else p["sku_receipts"])
        for row in rows:
            position, _ = WacPosition.objects.select_for_update().get_or_create(sku=row["sku"])
            position.qty_packs += money(row["qty_packs"])
            position.value_twd += money(row["landed_cost_twd"])
            position.save(update_fields=["qty_packs", "value_twd"])
    elif kind in ("order.cogs_relieved", "order.reprint_issued"):
        order = Order.objects.get(pk=event.entity_id)
        for order_line, cost_line in zip(order.lines.all(), (line for line in lines if line.account == "5111")):
            position = WacPosition.objects.select_for_update().get(pk=order_line.product_id)
            position.qty_packs -= Decimal(order_line.qty_packs)
            position.value_twd -= cost_line.debit
            if position.qty_packs == 0:
                position.value_twd = Decimal(0)
            position.save(update_fields=["qty_packs", "value_twd"])
    elif kind == "inventory.adjusted":
        position = WacPosition.objects.select_for_update().get(pk=p["sku"])
        position.qty_packs -= money(p["qty"])
        position.value_twd -= lines[0].debit
        if position.qty_packs == 0:
            position.value_twd = Decimal(0)
        position.save(update_fields=["qty_packs", "value_twd"])
    elif kind == "po.landed_cost_adjusted":
        position = WacPosition.objects.select_for_update().get(pk=p["sku"])
        position.value_twd += next(line.debit for line in lines if line.account == "1231")
        position.save(update_fields=["value_twd"])


@transaction.atomic
def post_event(event):
    if event.posted_entry_id:
        return event.posted_entry_id
    if isinstance(event, LedgerEvent) and event.event_type == "order.shipped" and not LedgerEvent.objects.filter(
        event_type="order.placed", entity_table=event.entity_table, entity_id=event.entity_id,
        posted_entry_id__isnull=False,
    ).exists():
        raise PostingError("order.shipped requires its order.placed deposit to be posted first")
    lines = plan(event)
    memo_only = lines is None
    period = event.occurred_at.astimezone(timezone.get_current_timezone()).strftime("%Y-%m")
    source_kind = "ops" if isinstance(event, LedgerEvent) else "manual"
    source_ref = f"{source_kind}:{event.idempotency_key}"
    entry = JournalEntry.objects.create(occurred_at=event.occurred_at, period=period,
        dataset_kind=event.dataset_kind if source_kind == "ops" else DatasetSettings.load().dataset_kind,
        source_kind=source_kind, source_ref=source_ref, memo_only=memo_only,
        memo="No financial entry: duty position DDU or unknown" if memo_only else "")
    for item in lines or ():
        account = Account.objects.get(pk=item.account)
        if account.is_reserved:
            raise PostingError(f"account {item.account} is RESERVED")
        estimated = (event.payload.get("basis") == "estimate" if isinstance(event, LedgerEvent)
                     else event.basis == "estimate")
        basis_note = event.payload.get("basis_note", "") if estimated else ""
        line_memo = f"[ESTIMATE] basis: {basis_note}" if estimated else ""
        JournalLine.objects.create(entry=entry, account=account, debit=item.debit, credit=item.credit,
            txn_amount=item.txn_amount, txn_currency=item.txn_currency, fx_rate=item.fx_rate, sku=item.sku,
            qty_delta_packs=item.qty_delta_packs, source_ref=source_ref, memo=line_memo[:255])
    if lines:
        apply_wac(event, lines)
    if source_kind == "ops":
        LedgerEvent.objects.filter(pk=event.pk, posted_entry_id__isnull=True).update(posted_entry_id=entry.pk, posting_error=None)
    else:
        AcctManualEntry.objects.filter(pk=event.pk, posted_entry_id__isnull=True).update(posted_entry_id=entry.pk, posting_error=None)
    return entry.pk
