"""Etsy import controls. Parse sample exports; never infer dataset kind from content."""

import csv
import calendar
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from django.db import transaction

from core.models import DatasetSettings
from ops.intake import ImportRefused, IntakeManifest, classify_filename, read_csv
from ops.models import (Channel, EtsyStatementPeriod, EtsyStatementRow, InventoryMove,
                        LedgerEvent, OnHand, OPS_EVENT_TYPES, Order, OrderLine, Product, Shipment)


_ACTUAL_NAME = re.compile(r"etsy_(?:orderitems|statement)_\d{4}-(?:0[1-9]|1[0-2])\.csv\Z")
_ORDER_REF = re.compile(r"Order #(\d+)")
_LISTING_REF = re.compile(r"Listing #(\d+)")
_TZ = ZoneInfo("Asia/Taipei")
_SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
_COUNTRIES = json.loads((_SCHEMAS / "country_names.json").read_text())
_FEE_CODES = {
    "Transaction Fee": "transaction_fee",
    "Processing Fee": "payment_processing_fee",
    "Offsite Ads Fee": "offsite_ads_fee",
    "Regulatory Operating Fee": "regulatory_operating_fee",
}
_TYPES = {"Sale", "Listing Fee", "Deposit", *_FEE_CODES}


@dataclass
class ImportResult:
    parsed_order_rows: int = 0
    parsed_statement_rows: int = 0
    inserted_rows: int = 0
    inserted_events: int = 0
    reconciling_items: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


def load_schema(kind: str) -> dict:
    return json.loads((_SCHEMAS / f"etsy_{kind}_header_v1.json").read_text())


def etsy_manifest(kind: str) -> IntakeManifest:
    fixture = load_schema(kind)
    return IntakeManifest(
        kind=kind, header=tuple(fixture["header"]), optional_columns=(),
        verified=fixture["verified"], actual_filename=_ACTUAL_NAME,
        target_models=("Order", "OrderLine", "Shipment", "InventoryMove") if kind == "orderitems"
                      else ("EtsyStatementPeriod", "EtsyStatementRow"),
        events=("order.placed", "order.shipped", "order.cogs_relieved") if kind == "orderitems"
               else ("order.fees_assessed", "cost.recorded", "settlement.received"),
        natural_key="Etsy order ID / transaction ID" if kind == "orderitems"
                    else "period + canonical statement row hash + duplicate occurrence",
    )


def _read_csv(path: Path, kind: str) -> list[dict]:
    return read_csv(path, etsy_manifest(kind))


def _minor(raw: str, *, nullable: bool = False) -> int | None:
    if raw == "--" or raw == "":
        if nullable:
            return None
        raise ImportRefused("Missing monetary value")
    try:
        amount = Decimal(raw)
        cents = amount * 100
        if not cents.is_finite() or cents != cents.to_integral_value():
            raise ImportRefused("Money has more than two decimal places")
        return int(cents)
    except InvalidOperation as exc:
        raise ImportRefused("Invalid monetary value") from exc


def _date(raw: str, kind: str):
    fmt = "%m/%d/%y" if kind == "orderitems" else "%b %d, %Y"
    try:
        return datetime.strptime(raw, fmt).replace(tzinfo=_TZ)
    except ValueError as exc:
        raise ImportRefused(f"Invalid {kind} date format") from exc


def _period(path: Path) -> str:
    # Sanitized in-repo tests use the guarded *_fixture.csv suffix. Real ACTUAL
    # filenames are still constrained by _ACTUAL_NAME in quarantine_file().
    match = re.search(r"(\d{4}-(?:0[1-9]|1[0-2]))(?:_fixture)?\.csv\Z", path.name)
    if not match:
        raise ImportRefused(f"Filename {path.name} has no YYYY-MM statement period")
    return match.group(1)


def load_coupon_funding(path: Path) -> list[dict]:
    """Read the founder-owned map; this code never creates or amends that file."""
    if not path.is_file():
        raise ImportRefused(f"Founder coupon-funding file is absent: {path.name}")
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"coupon_code", "funded_by", "valid_from", "valid_to"}
        if not reader.fieldnames or not required <= set(reader.fieldnames):
            raise ImportRefused("Coupon-funding header lacks required columns")
        rows = []
        for row in reader:
            if not row["coupon_code"] or row["funded_by"] not in {"seller", "platform", "none"}:
                raise ImportRefused("Coupon-funding row has invalid code or funder")
            try:
                start = date.fromisoformat(row["valid_from"]) if row["valid_from"] else None
                end = date.fromisoformat(row["valid_to"]) if row["valid_to"] else None
            except ValueError as exc:
                raise ImportRefused("Coupon-funding date is not ISO YYYY-MM-DD") from exc
            if start and end and start > end:
                raise ImportRefused("Coupon-funding validity range is inverted")
            rows.append({"code": row["coupon_code"].strip().upper(),
                         "funder": row["funded_by"], "start": start, "end": end})
    return rows


def _coupon_funder(code: str, discount: int, mapping: dict | list | None, order_date: date) -> str | None:
    if not discount:
        return "none"
    if isinstance(mapping, dict):  # in-memory synthetic tests
        value = mapping.get(code.strip().upper())
    else:
        matches = [row["funder"] for row in (mapping or [])
                   if row["code"] == code.strip().upper()
                   and (row["start"] is None or row["start"] <= order_date)
                   and (row["end"] is None or order_date <= row["end"])]
        value = matches[0] if len(matches) == 1 else None
    if value not in {"seller", "platform"}:
        return None
    return value


def _orders(rows: list[dict], coupon_funding: dict | None, result: ImportResult) -> dict:
    grouped = defaultdict(list)
    transaction_ids = set()
    for row in rows:
        order_id = row["Order ID"]
        txn_id = row["Transaction ID"]
        if not order_id.isdigit() or not txn_id.isdigit():
            raise ImportRefused("Invalid Etsy numeric order or transaction identifier")
        if txn_id in transaction_ids:
            raise ImportRefused(f"Duplicate Etsy transaction ID for order {order_id}")
        transaction_ids.add(txn_id)
        if row["Listings Type"] != "Physical" or row["Payment Type"] != "Etsy Payments":
            raise ImportRefused(f"Unmapped listing or payment type for order {order_id}")
        if row["Currency"] != "USD":
            raise ImportRefused(f"Unmapped currency for order {order_id}")
        if row["Ship Country"] not in _COUNTRIES:
            raise ImportRefused(f"Unmapped destination country for order {order_id}")
        grouped[order_id].append(row)
    prepared = {}
    for order_id, lines in grouped.items():
        first = lines[0]
        repeated = ("Sale Date", "Currency", "Coupon Code", "Order Shipping", "Shipping Discount",
                    "Order Sales Tax", "Ship Country", "Date Shipped")
        if any(any(line[key] != first[key] for key in repeated) for line in lines[1:]):
            raise ImportRefused(f"Conflicting order-level fields for order {order_id}")
        line_data = []
        for index, line in enumerate(sorted(lines, key=lambda r: (r["SKU"], r["Transaction ID"])), 1):
            try:
                qty = int(line["Quantity"])
            except ValueError as exc:
                raise ImportRefused(f"Invalid pack quantity for order {order_id}") from exc
            price = _minor(line["Price"])
            discount = _minor(line["Discount Amount"])
            total = _minor(line["Item Total"])
            if qty <= 0 or min(price, discount, total) < 0 or qty * price - discount != total:
                raise ImportRefused(f"Item Total identity failed for order {order_id}")
            line_data.append({"txn": line["Transaction ID"], "sku": line["SKU"],
                              "listing": line["Listing ID"], "index": index,
                              "qty": qty, "price": price, "discount": discount, "total": total})
        ship = _minor(first["Order Shipping"])
        ship_discount = _minor(first["Shipping Discount"])
        tax = _minor(first["Order Sales Tax"])
        gross = sum(x["qty"] * x["price"] for x in line_data) + ship + ship_discount
        discount = sum(x["discount"] for x in line_data) + ship_discount
        buyer_paid = sum(x["total"] for x in line_data) + ship
        if gross - discount != buyer_paid or min(ship, ship_discount, tax) < 0:
            raise ImportRefused(f"Gross identity failed for order {order_id}")
        order_date = _date(first["Sale Date"], "orderitems")
        if order_date.day == 1 or (order_date + timedelta(days=1)).month != order_date.month:
            result.reconciling_items.append(f"Order {order_id}: period-boundary timezone risk")
        funder = _coupon_funder(first["Coupon Code"], discount, coupon_funding, order_date.date())
        if funder is None:
            result.blockers.append(f"Order {order_id}: coupon has no founder funder mapping")
        shipped = _date(first["Date Shipped"], "orderitems") if first["Date Shipped"] else None
        prepared[order_id] = {
            "date": order_date, "currency": first["Currency"],
            "coupon": first["Coupon Code"], "country": _COUNTRIES[first["Ship Country"]],
            "gross": gross, "discount": discount, "buyer_paid": buyer_paid,
            "ship": ship, "ship_discount": ship_discount, "tax": tax,
            "funder": funder, "shipped": shipped, "lines": line_data,
        }
        if ship_discount:
            result.reconciling_items.append(f"Order {order_id}: shipping-discount gross leg unproven by a Sale row")
    return prepared


def _statement(rows: list[dict], period: str, orders: dict, result: ImportResult) -> tuple[list[dict], str]:
    counts = Counter()
    prepared = []
    sales = {}
    net_total = 0
    deposit_count = 0
    for row in rows:
        typ = row["Type"]
        if typ not in _TYPES:
            raise ImportRefused("Unmapped Etsy statement Type; inspect source offline")
        if row["Currency"] != "USD":
            raise ImportRefused(f"Unmapped statement currency for {typ}")
        if row["Tax Details"] not in ("--", ""):
            raise ImportRefused("Statement Tax Details is populated; needs ruling")
        occurred = _date(row["Date"], "statement")
        if occurred.day == 1 or (occurred + timedelta(days=1)).month != occurred.month:
            marker = f"Statement {period}: period-boundary timezone risk"
            if marker not in result.reconciling_items:
                result.reconciling_items.append(marker)
        if occurred.strftime("%Y-%m") != period:
            raise ImportRefused(f"Statement row date outside {period}")
        amount = _minor(row["Amount"], nullable=True)
        fee = _minor(row["Fees & Taxes"], nullable=True)
        net = _minor(row["Net"])
        if (amount is None) == (fee is None) or net != (amount if amount is not None else fee):
            raise ImportRefused(f"Statement money columns disagree for {typ}")
        if typ in ("Sale", "Deposit") and amount is None:
            raise ImportRefused(f"Expected Amount for {typ}")
        if typ == "Sale" and amount <= 0:
            raise ImportRefused("Sale amount must be positive")
        if typ not in ("Sale", "Deposit") and (fee is None or fee >= 0):
            raise ImportRefused(f"Expected negative fee for {typ}")
        order_ref = ""
        listing_ref = ""
        if typ in {"Sale", *_FEE_CODES}:
            match = _ORDER_REF.search(row["Info"])
            if not match:
                raise ImportRefused(f"Missing Order # reference for {typ}")
            order_ref = match.group(1)
            if order_ref not in orders and not Order.objects.filter(channel__code="etsy", channel_order_id=order_ref).exists():
                raise ImportRefused(f"Statement references unknown order {order_ref}")
        elif typ == "Listing Fee":
            match = _LISTING_REF.search(row["Info"])
            if not match:
                raise ImportRefused("Listing Fee has no Listing # reference")
            listing_ref = match.group(1)
        elif typ == "Deposit":
            deposit_count += 1
            if net > 0:
                result.blockers.append("Positive Deposit: payout reversal needs a bank reference and explicit reversal evidence")
            elif net == 0:
                raise ImportRefused("Zero Deposit is ambiguous")
        if typ == "Sale":
            if order_ref in sales:
                raise ImportRefused(f"Duplicate Sale control for order {order_ref}")
            sales[order_ref] = amount
        net_total += net
        canonical = [period, occurred.date().isoformat(), typ,
                     " ".join(row["Info"].split()), row["Currency"], amount, fee, net]
        row_hash = hashlib.sha256(json.dumps(canonical, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        counts[row_hash] += 1
        key = f"stmt|etsy|{period}|{row_hash[:16]}|#{counts[row_hash]}"
        prepared.append({"type": typ, "date": occurred, "currency": row["Currency"],
                         "amount": amount, "fee": fee, "net": net, "order_ref": order_ref,
                         "listing_ref": listing_ref, "key": key, "info": row["Info"]})
    for order_id, sale in sales.items():
        gross = (orders[order_id]["gross"] if order_id in orders else
                 Order.objects.get(channel__code="etsy", channel_order_id=order_id).gross_minor)
        if sale != gross:
            raise ImportRefused(f"Gross-before-discount Sale mismatch for order {order_id}")
    year, month = (int(part) for part in period.split("-"))
    period_end = date(year, month, calendar.monthrange(year, month)[1])
    pending_dates = {key: value["date"].date() for key, value in orders.items()}
    pending_dates.update(Order.objects.filter(channel__code="etsy", order_date__lte=period_end)
                         .values_list("channel_order_id", "order_date"))
    previously_sold = set(EtsyStatementRow.objects.filter(row_type="Sale")
                          .values_list("order_ref", flat=True))
    for order_id, order_date in pending_dates.items():
        if order_id in sales or order_id in previously_sold:
            continue
        age = (period_end - order_date).days
        if age >= 60:
            result.blockers.append(f"Order {order_id}: no Sale after {age} days")
        elif age >= 35:
            result.reconciling_items.append(f"Order {order_id}: no Sale after {age} days (RISK)")
    for item in prepared:
        if item["order_ref"] and item["order_ref"] not in sales and item["type"] != "Sale":
            message = f"Order {item['order_ref']}: {item['type']} without Sale in this statement"
            if message not in result.reconciling_items:
                result.reconciling_items.append(message)
    if deposit_count and net_total != 0:
        result.reconciling_items.append(f"Statement {period}: deposit control residual {net_total} minor units")
    if not deposit_count:
        result.reconciling_items.append(f"Statement {period}: settlement still open")
    digest = hashlib.sha256(json.dumps(sorted(x["key"] for x in prepared)).encode()).hexdigest()
    return prepared, digest


def emit_event(*, event_type: str, entity_table: str, entity_id: int, occurred_at,
               idempotency_key: str, source_filename: str, dataset_kind: str,
               amount_minor: int | None = None, currency: str | None = None,
               payload: dict | None = None) -> bool:
    """Emit one catalogue event; never create a journal row."""
    if event_type not in OPS_EVENT_TYPES:
        raise ImportRefused(f"Uncatalogued ops event {event_type}")
    payload = payload or {}
    if event_type in {"order.shipped", "order.cogs_relieved"}:
        if entity_table != "ops.order" or not Shipment.objects.filter(
            order_id=entity_id, status="dispatched", ship_date__isnull=False
        ).exists():
            raise ImportRefused(f"{event_type} requires a dispatched shipment with ship_date")
    if event_type == "order.placed" and payload.get("discount_funded_by") not in {"seller", "platform", "none"}:
        raise ImportRefused("order.placed requires discount_funded_by")
    if event_type == "cost.recorded" and payload.get("category") == "platform_listing_fee" and payload.get("settled_via") != "etsy_rail":
        raise ImportRefused("Listing Fee requires settled_via=etsy_rail")
    if event_type == "cost.recorded" and payload.get("category") == "advertising" and not payload.get("channel_attribution"):
        raise ImportRefused("Advertising requires channel_attribution")
    if event_type in {"order.cancelled", "order.refunded", "settlement.reversed"} and not payload.get("evidence_ref"):
        raise ImportRefused(f"{event_type} requires evidence_ref")
    if event_type == "inventory.opening_counted":
        from acct.posting import PostingError, opening_counted
        candidate = LedgerEvent(event_type=event_type, entity_table=entity_table, entity_id=entity_id,
            occurred_at=occurred_at, payload=payload, idempotency_key=idempotency_key,
            source_filename=source_filename, dataset_kind=dataset_kind)
        try:
            opening_counted(candidate)
        except PostingError as exc:
            raise ImportRefused(str(exc)) from exc
    if amount_minor is not None and amount_minor < 0:
        raise ImportRefused(f"{event_type} amount must be nonnegative")
    obj, created = LedgerEvent.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={"event_type": event_type, "entity_table": entity_table, "entity_id": entity_id,
                  "occurred_at": occurred_at, "amount_minor": amount_minor, "currency": currency,
                  "payload": payload, "source_filename": source_filename, "dataset_kind": dataset_kind},
    )
    if not created and (obj.event_type != event_type or obj.entity_table != entity_table or
                        obj.entity_id != entity_id or obj.amount_minor != amount_minor or
                        obj.currency != currency or obj.payload != payload or
                        obj.source_filename != source_filename or obj.dataset_kind != dataset_kind):
        raise ImportRefused(f"Idempotency key {idempotency_key} already belongs to a changed event")
    return created


@transaction.atomic
def import_etsy(order_path, statement_path, *, commit: bool = False,
                coupon_funding: dict | list | None = None) -> ImportResult:
    """Import one pair of pinned Etsy exports; dry-run by default."""
    order_path, statement_path = Path(order_path), Path(statement_path)
    settings = DatasetSettings.objects.get(pk=1)
    for path in (order_path, statement_path):
        quarantine_file(path.name, settings.dataset_kind)
    if "orderitems" not in order_path.name or "statement" not in statement_path.name:
        raise ImportRefused("Expected orderitems file followed by statement file")
    if _period(order_path) != _period(statement_path):
        raise ImportRefused("Order and statement filename periods disagree")
    for kind in ("orderitems", "statement"):
        if commit and not etsy_manifest(kind).verified:
            raise ImportRefused(f"Cannot --commit: {kind} schema fixture is unverified")
    result = ImportResult()
    order_rows = _read_csv(order_path, "orderitems")
    statement_rows = _read_csv(statement_path, "statement")
    result.parsed_order_rows = len(order_rows)
    result.parsed_statement_rows = len(statement_rows)
    orders = _orders(order_rows, coupon_funding, result)
    period = _period(statement_path)
    statement, digest = _statement(statement_rows, period, orders, result)
    known_products = set(Product.objects.filter(
        sku__in={line["sku"] for order in orders.values() for line in order["lines"]}
    ).values_list("sku", flat=True))
    unknown_products = sorted({line["sku"] for order in orders.values()
                               for line in order["lines"]} - known_products)
    if unknown_products:
        result.blockers.append(f"Unknown SKU(s): {', '.join(unknown_products)}")
    existing_period = EtsyStatementPeriod.objects.filter(period=period).first()
    if existing_period and existing_period.multiset_digest != digest:
        raise ImportRefused(f"Statement {period} multiset changed; founder review required")
    if result.blockers and commit:
        raise ImportRefused("; ".join(result.blockers))
    if not commit:
        return result
    channel, _ = Channel.objects.get_or_create(code="etsy", defaults={"name": "Etsy"})
    products = Product.objects.in_bulk({line["sku"] for order in orders.values() for line in order["lines"]})
    missing = sorted({line["sku"] for order in orders.values() for line in order["lines"]} - set(products))
    if missing:
        raise ImportRefused(f"Unknown SKU(s): {', '.join(missing)}")
    # Lock SKU masters before checking the derived view, serialising concurrent imports.
    list(Product.objects.select_for_update().filter(sku__in=products).order_by("sku"))
    required = Counter()
    for order_id, parsed in orders.items():
        if parsed["shipped"] and not Order.objects.filter(channel=channel, channel_order_id=order_id).exists():
            for line in parsed["lines"]:
                required[line["sku"]] += line["qty"]
    available = dict(OnHand.objects.filter(sku__in=required).values_list("sku", "qty_packs"))
    for sku, needed in required.items():
        if available.get(sku, 0) < needed:
            raise ImportRefused(f"Insufficient counted packs for SKU {sku}; need {needed}")
    for order_id, parsed in orders.items():
        existing = Order.objects.filter(channel=channel, channel_order_id=order_id).first()
        if existing:
            expected_lines = sorted((x["txn"], x["sku"], x["listing"], x["qty"],
                                     x["price"], x["discount"], x["total"]) for x in parsed["lines"])
            actual_lines = sorted(existing.lines.values_list(
                "platform_transaction_id", "product_id", "listing_id", "qty_packs",
                "unit_price_minor", "line_discount_minor", "item_total_minor"
            ))
            shipment = Shipment.objects.filter(order=existing).first()
            if (existing.gross_minor != parsed["gross"] or existing.discount_minor != parsed["discount"] or
                existing.buyer_paid_minor != parsed["buyer_paid"] or
                existing.shipping_minor != parsed["ship"] or
                existing.shipping_discount_minor != parsed["ship_discount"] or
                existing.tax_remitted_by_platform_minor != parsed["tax"] or
                existing.order_date != parsed["date"].date() or
                existing.currency != parsed["currency"] or
                existing.coupon_code != parsed["coupon"] or
                existing.dest_country != parsed["country"] or
                existing.discount_funded_by != parsed["funder"] or
                (shipment.ship_date if shipment else None) != (parsed["shipped"].date() if parsed["shipped"] else None) or
                actual_lines != expected_lines):
                raise ImportRefused(f"Previously imported order {order_id} changed")
            continue
        obj = Order.objects.create(
            channel=channel, channel_order_id=order_id, order_date=parsed["date"].date(),
            currency=parsed["currency"], coupon_code=parsed["coupon"],
            discount_funded_by=parsed["funder"], gross_minor=parsed["gross"],
            discount_minor=parsed["discount"], buyer_paid_minor=parsed["buyer_paid"],
            shipping_minor=parsed["ship"], shipping_discount_minor=parsed["ship_discount"],
            tax_remitted_by_platform_minor=parsed["tax"], dest_country=parsed["country"],
            status="shipped" if parsed["shipped"] else "placed",
            source_filename=order_path.name, dataset_kind=settings.dataset_kind,
        )
        result.inserted_rows += 1
        for line in parsed["lines"]:
            OrderLine.objects.create(
                order=obj, product=products[line["sku"]], platform_transaction_id=line["txn"],
                listing_id=line["listing"], line_index=line["index"], qty_packs=line["qty"],
                unit_price_minor=line["price"], line_discount_minor=line["discount"],
                item_total_minor=line["total"], source_filename=order_path.name,
                dataset_kind=settings.dataset_kind,
            )
            result.inserted_rows += 1
        result.inserted_events += emit_event(
            event_type="order.placed", entity_table="ops.order", entity_id=obj.pk,
            occurred_at=parsed["date"], idempotency_key=f"order.placed|etsy|{order_id}",
            amount_minor=parsed["gross"], currency=parsed["currency"],
            payload={"discount": parsed["discount"], "discount_funded_by": parsed["funder"],
                     "tax_remitted_by_platform": parsed["tax"],
                     "tax_treatment_hint": "domestic" if parsed["country"] == "TW" else "export"},
            source_filename=order_path.name, dataset_kind=settings.dataset_kind,
        )
        if parsed["shipped"]:
            Shipment.objects.create(order=obj, status="dispatched", ship_date=parsed["shipped"].date(),
                                    source_filename=order_path.name, dataset_kind=settings.dataset_kind)
            result.inserted_rows += 1
            for line in parsed["lines"]:
                InventoryMove.objects.create(
                    product=products[line["sku"]], kind="sold", qty_delta_packs=-line["qty"],
                    occurred_at=parsed["shipped"], idempotency_key=f"sold|etsy|{line['txn']}",
                    source_filename=order_path.name, dataset_kind=settings.dataset_kind,
                )
                result.inserted_rows += 1
            for typ, key in (("order.shipped", "order.shipped"), ("order.cogs_relieved", "order.cogs")):
                result.inserted_events += emit_event(
                    event_type=typ, entity_table="ops.order", entity_id=obj.pk,
                    occurred_at=parsed["shipped"], idempotency_key=f"{key}|{order_id}",
                    amount_minor=None if typ == "order.cogs_relieved" else parsed["gross"],
                    currency=parsed["currency"], payload={"cost_basis": "provisional"} if typ == "order.cogs_relieved" else {},
                    source_filename=order_path.name, dataset_kind=settings.dataset_kind,
                )
    if not existing_period:
        batch = EtsyStatementPeriod.objects.create(
            period=period, multiset_digest=digest, row_count=len(statement),
            source_sha256=hashlib.sha256(statement_path.read_bytes()).hexdigest(),
            source_filename=statement_path.name, dataset_kind=settings.dataset_kind,
        )
        result.inserted_rows += 1
        deposits = [x for x in statement if x["type"] == "Deposit"]
        composition_ok = len(deposits) == 1 and sum(x["net"] for x in statement) == 0
        for item in statement:
            row = EtsyStatementRow.objects.create(
                period=batch, row_key=item["key"], row_type=item["type"], occurred_at=item["date"],
                order_ref=item["order_ref"], listing_ref=item["listing_ref"],
                currency=item["currency"], amount_minor=item["amount"], fee_minor=item["fee"],
                net_minor=item["net"], source_filename=statement_path.name,
                dataset_kind=settings.dataset_kind,
            )
            result.inserted_rows += 1
            if item["type"] in _FEE_CODES:
                event_type = "order.fees_assessed"
                payload = {"fee_components": [{"code": _FEE_CODES[item["type"]], "amount": abs(item["fee"])}],
                           "order_id": item["order_ref"]}
                amount = abs(item["fee"])
                entity_table, entity_id = "ops.order", Order.objects.get(channel=channel, channel_order_id=item["order_ref"]).pk
            elif item["type"] == "Listing Fee":
                event_type, amount = "cost.recorded", abs(item["fee"])
                payload = {"category": "platform_listing_fee", "settled_via": "etsy_rail",
                           "listing_id": item["listing_ref"]}
                entity_table, entity_id = "ops.etsystatementrow", row.pk
            elif item["type"] == "Deposit" and item["net"] < 0:
                event_type, amount = "settlement.received", abs(item["net"])
                payload = {"composition_unresolved": not composition_ok,
                           "bank_account_ref_partial": item["info"],
                           "value_date": None, "bank_credit_ref": None,
                           "covers_order_ids": sorted({x["order_ref"] for x in statement if x["order_ref"]}) if composition_ok else []}
                entity_table, entity_id = "ops.etsystatementrow", row.pk
            else:
                continue  # Sale is a control; a positive Deposit needs reversal evidence.
            result.inserted_events += emit_event(
                event_type=event_type, entity_table=entity_table, entity_id=entity_id,
                occurred_at=item["date"], idempotency_key=f"{event_type}|{item['key']}",
                amount_minor=amount, currency=item["currency"], payload=payload,
                source_filename=statement_path.name, dataset_kind=settings.dataset_kind,
            )
    return result


def quarantine_file(filename: str, application_dataset_kind: str) -> str:
    """Return the filename-derived kind, or refuse before opening the file."""
    try:
        return classify_filename(Path(filename), application_dataset_kind, etsy_manifest("orderitems"))
    except ImportRefused as exc:
        # Preserve Slice A's public diagnostic while using the shared classifier.
        raise ImportRefused(str(exc).replace("Unclassified orderitems filename", "Unclassified Etsy filename")) from exc
