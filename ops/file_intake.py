"""Evidenced receipt and physical-count CSV intake; dry-run is the default."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Sum

from acct.models import Account, WacPosition
from acct.posting import PostingError, plan
from core.models import DatasetSettings
from ops.etsy_import import emit_event
from ops.intake import ImportRefused, IntakeManifest, prepare_source
from ops.models import InventoryMove, LedgerEvent, Product, Receipt, StockCount, StockCountLine

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
RECEIPT_CATEGORIES = {"advertising", "rent", "software", "professional", "utilities",
                      "wages", "bank_fee", "other"}
CONDITIONS = {"sellable", "damaged_unsellable"}
TZ = ZoneInfo("Asia/Taipei")


@dataclass
class IntakeResult:
    parsed_rows: int = 0
    inserted_rows: int = 0
    inserted_events: int = 0


def load_schema(kind: str) -> dict:
    return json.loads((SCHEMAS / f"{kind}_header_v1.json").read_text())


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _receipt_payload(row):
    payload = {"category": row["category"], "settled_via": row["settled_via"],
               "evidence_ref": row["evidence_ref"], "description": row["description"]}
    if row["channel_attribution"]:
        payload["channel_attribution"] = row["channel_attribution"]
    if row["bank_account"]:
        payload["bank_account"] = row["bank_account"]
    return payload


def _opening_payload(counted_at, evidence, lines, total):
    payload_lines = [{**line, "agreed_unit_cost_twd": str(line["agreed_unit_cost_twd"]),
                      "line_value_twd": str(line["line_value_twd"])} for line in lines]
    payload = {"counted_at": counted_at.isoformat(), "evidence_ref": evidence,
               "lines": payload_lines, "total_value_twd": str(total)}
    if Decimal(payload["total_value_twd"]) != sum(
            (Decimal(line["line_value_twd"]) for line in payload_lines), Decimal(0)):
        raise ImportRefused("opening count total_value_twd disagrees with sum of lines")
    return payload


def _adjustment_payload(sku, delta, evidence, value):
    return {"sku": sku, "qty": str(delta), "evidence_ref": evidence,
            "source_value_twd": str(value)}


def manifest(kind: str) -> IntakeManifest:
    if kind not in {"receipts", "counts"}:
        raise ImportRefused(f"Unknown intake kind {kind}")
    fixture = load_schema(kind)
    return IntakeManifest(
        kind=kind, header=tuple(fixture["header"]),
        optional_columns=tuple(fixture.get("optional_columns", [])), verified=fixture["verified"],
        actual_filename=re.compile(r"receipts_\d{4}-(?:0[1-9]|1[0-2])\.csv\Z" if kind == "receipts"
                                   else r"count_\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\.csv\Z"),
        target_models=("Receipt",) if kind == "receipts" else
                      ("StockCount", "StockCountLine", "InventoryMove"),
        events=("cost.recorded",) if kind == "receipts" else
               ("inventory.opening_counted", "inventory.adjusted"),
        natural_key="dataset + evidence_ref" if kind == "receipts" else
                    "dataset + count evidence_ref, then SKU",
        key_from=lambda row: _digest(row["evidence_ref"]),
        payload_builders={"cost.recorded": lambda row: _receipt_payload(row)} if kind == "receipts" else {
            "inventory.opening_counted": lambda counted_at, evidence, lines, total:
                _opening_payload(counted_at, evidence, lines, total),
            "inventory.adjusted": lambda sku, delta, evidence, value:
                _adjustment_payload(sku, delta, evidence, value),
        },
    )


def _date(raw: str, field: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ImportRefused(f"{field} must be ISO YYYY-MM-DD") from exc


def _money(raw: str, field: str, *, cents: bool = False) -> Decimal:
    try:
        value = Decimal(raw)
        unit = Decimal("0.01" if cents else "0.0001")
        precise = value.quantize(unit)
    except (InvalidOperation, TypeError) as exc:
        raise ImportRefused(f"{field} must be a decimal amount") from exc
    if not value.is_finite() or value < 0 or value != precise:
        raise ImportRefused(f"{field} must be nonnegative with at most {2 if cents else 4} decimal places")
    return value


def _occurred(day: date) -> datetime:
    return datetime.combine(day, time(12), TZ)


def _receipt(row: dict) -> dict:
    evidence = row["evidence_ref"].strip()
    if not evidence:
        raise ImportRefused("receipt evidence_ref is mandatory")
    category, settled = row["category"].strip(), row["settled_via"].strip()
    if category not in RECEIPT_CATEGORIES:
        raise ImportRefused("receipt category is unmapped; platform_listing_fee belongs to an Etsy statement")
    if settled not in {"payable", "bank"}:
        raise ImportRefused("receipt settled_via must be payable or bank; etsy_rail is not a receipt route")
    channel = row.get("channel_attribution", "").strip()
    if category == "advertising" and channel not in {"etsy", "meta", "other"}:
        raise ImportRefused("advertising receipt requires channel_attribution=etsy, meta or other")
    if category != "advertising" and channel:
        raise ImportRefused("channel_attribution is only used for advertising receipts")
    bank = row.get("bank_account", "").strip()
    if bank and settled != "bank":
        raise ImportRefused("bank_account requires settled_via=bank")
    if bank and not Account.objects.filter(pk=bank, type="asset", is_reserved=False).exists():
        raise ImportRefused("bank_account is not an active asset account")
    amount = _money(row["amount_twd"], "amount_twd", cents=True)
    if amount <= 0:
        raise ImportRefused("receipt amount_twd must be positive")
    description = row["description"].strip()
    if not description:
        raise ImportRefused("receipt description is mandatory")
    return {"occurred_on": _date(row["occurred_on"], "occurred_on"), "category": category,
            "amount_twd": amount, "settled_via": settled, "evidence_ref": evidence,
            "description": description, "channel_attribution": channel, "bank_account": bank}


@transaction.atomic
def import_receipts(path, *, commit: bool = False) -> IntakeResult:
    path = Path(path)
    settings = DatasetSettings.objects.select_for_update().get(pk=1)
    source = manifest("receipts")
    parsed = [_receipt(row) for row in prepare_source(path, settings.dataset_kind, source, commit=commit)]
    if not path.name.startswith("SAMPLE_"):
        period = path.stem.removeprefix("receipts_")
        if any(row["occurred_on"].strftime("%Y-%m") != period for row in parsed):
            raise ImportRefused("receipt occurred_on is outside filename period")
    result = IntakeResult(parsed_rows=len(parsed))
    keys = [row["evidence_ref"] for row in parsed]
    if len(keys) != len(set(keys)):
        raise ImportRefused("receipt evidence_ref repeats in one file")
    existing = {receipt.evidence_ref: receipt for receipt in
                Receipt.objects.filter(dataset_kind=settings.dataset_kind, evidence_ref__in=keys)}
    for row in parsed:
        prior = existing.get(row["evidence_ref"])
        if prior and any(getattr(prior, field) != value for field, value in row.items()):
            raise ImportRefused("Previously imported receipt evidence_ref has changed")
        if prior or not commit:
            continue
        key = f"receipt|{settings.dataset_kind}|{source.key_from(row)}"
        receipt = Receipt.objects.create(**row, idempotency_key=key,
                                         source_filename=path.name, dataset_kind=settings.dataset_kind)
        result.inserted_rows += 1
        payload = source.payload_for("cost.recorded", row=row)
        event_key = f"cost.recorded|{key}"
        candidate = LedgerEvent(event_type="cost.recorded", entity_table="ops.receipt", entity_id=receipt.pk,
            occurred_at=_occurred(row["occurred_on"]), amount_minor=int(row["amount_twd"] * 100),
            currency="TWD", payload=payload, idempotency_key=event_key,
            source_filename=path.name, dataset_kind=settings.dataset_kind)
        try:
            plan(candidate)
        except PostingError as exc:
            raise ImportRefused(f"receipt posting rule refused: {exc}") from exc
        result.inserted_events += emit_event(
            event_type="cost.recorded", entity_table="ops.receipt", entity_id=receipt.pk,
            occurred_at=candidate.occurred_at, amount_minor=candidate.amount_minor, currency="TWD",
            payload=payload, idempotency_key=event_key,
            source_filename=path.name, dataset_kind=settings.dataset_kind,
        )
    return result


def _count_rows(source_rows: list[dict]) -> tuple[date, str, list[dict], Decimal]:
    if not source_rows:
        raise ImportRefused("count file has no SKU rows")
    days, references, lines = set(), set(), []
    for row in source_rows:
        days.add(_date(row["counted_at"], "counted_at"))
        reference = row["evidence_ref"].strip()
        if not reference:
            raise ImportRefused("count evidence_ref is mandatory")
        references.add(reference)
        sku = row["sku"].strip()
        if not sku:
            raise ImportRefused("count SKU is mandatory")
        raw_qty = row["qty_packs"].strip()
        if not raw_qty.isdigit():
            raise ImportRefused(f"count {sku} qty_packs must be a nonnegative whole number; blank is unknown")
        qty = int(raw_qty)
        unit = _money(row["agreed_unit_cost_twd"], "agreed_unit_cost_twd")
        condition = row["condition"].strip()
        if condition not in CONDITIONS:
            raise ImportRefused(f"count {sku} condition must be sellable or damaged_unsellable")
        lines.append({"sku": sku, "qty_packs": qty, "agreed_unit_cost_twd": unit,
                      "line_value_twd": unit * qty, "condition": condition})
    if len(days) != 1:
        raise ImportRefused("counted_at must be one date for the whole count schedule")
    if len(references) != 1:
        raise ImportRefused("evidence_ref must be one reference for the whole count schedule")
    if len({line["sku"] for line in lines}) != len(lines):
        raise ImportRefused("count file repeats a SKU")
    known = set(Product.objects.values_list("sku", flat=True))
    missing = sorted(known - {line["sku"] for line in lines})
    if missing:
        raise ImportRefused(f"count file omits active SKU(s): {', '.join(missing)}; use explicit zero rows")
    unknown = sorted({line["sku"] for line in lines} - known)
    if unknown:
        raise ImportRefused(f"count file has unknown SKU(s): {', '.join(unknown)}")
    return days.pop(), references.pop(), sorted(lines, key=lambda row: row["sku"]), sum(
        (line["line_value_twd"] for line in lines), Decimal(0))


@transaction.atomic
def import_counts(path, *, commit: bool = False) -> IntakeResult:
    path = Path(path)
    settings = DatasetSettings.objects.select_for_update().get(pk=1)
    source = manifest("counts")
    source_rows = prepare_source(path, settings.dataset_kind, source, commit=commit)
    counted_at, evidence, lines, total = _count_rows(source_rows)
    if not path.name.startswith("SAMPLE_") and path.stem != f"count_{counted_at.isoformat()}":
        raise ImportRefused("counted_at disagrees with count filename date")
    result = IntakeResult(parsed_rows=len(lines))
    prior = StockCount.objects.filter(dataset_kind=settings.dataset_kind, evidence_ref=evidence).first()
    if prior:
        saved = [(line.product_id, line.qty_packs, line.agreed_unit_cost_twd,
                  line.line_value_twd, line.condition) for line in prior.lines.order_by("product_id")]
        observed = [(line["sku"], line["qty_packs"], line["agreed_unit_cost_twd"],
                     line["line_value_twd"], line["condition"]) for line in lines]
        if prior.counted_at != counted_at or prior.total_value_twd != total or saved != observed:
            raise ImportRefused("Previously imported count evidence_ref has changed")
        return result
    opening = LedgerEvent.objects.filter(event_type="inventory.opening_counted",
                                          dataset_kind=settings.dataset_kind).first()
    kind = "adjustment" if opening else "opening"
    positions = {}
    if kind == "adjustment":
        if not opening.posted_entry_id:
            raise ImportRefused("opening count must be posted before adjustment intake")
        positions = WacPosition.objects.select_for_update().in_bulk([line["sku"] for line in lines])
        onhand = dict(InventoryMove.objects.filter(dataset_kind=settings.dataset_kind,
            product_id__in=positions).values("product_id").annotate(total=Sum("qty_delta_packs"))
            .values_list("product_id", "total"))
        for line in lines:
            sku, target = line["sku"], line["qty_packs"]
            position = positions.get(sku)
            if position is None or position.qty_packs != Decimal(onhand.get(sku, 0)):
                raise ImportRefused(f"count {sku} has no tied WAC/on-hand position")
            if Decimal(target) > position.qty_packs:
                raise ImportRefused(f"count {sku} implies an increase; a receipt is needed, not an adjustment")
            if target < position.qty_packs and position.value_twd <= 0:
                raise ImportRefused(f"count {sku} cannot reduce zero-value WAC stock")
    if not commit:
        return result
    key = f"count|{settings.dataset_kind}|{source.key_from({'evidence_ref': evidence})}"
    count = StockCount.objects.create(counted_at=counted_at, evidence_ref=evidence,
        kind=kind, total_value_twd=total, idempotency_key=key,
        source_filename=path.name, dataset_kind=settings.dataset_kind)
    result.inserted_rows += 1
    line_models = {}
    for line in lines:
        item = StockCountLine.objects.create(count=count, product_id=line["sku"],
            qty_packs=line["qty_packs"], agreed_unit_cost_twd=line["agreed_unit_cost_twd"],
            line_value_twd=line["line_value_twd"], condition=line["condition"],
            source_filename=path.name, dataset_kind=settings.dataset_kind)
        line_models[line["sku"]] = item
        result.inserted_rows += 1
    occurred_at = _occurred(counted_at)
    if kind == "opening":
        payload = source.payload_for("inventory.opening_counted", counted_at=counted_at,
                                     evidence=evidence, lines=lines, total=total)
        for line in lines:
            InventoryMove.objects.create(product_id=line["sku"], kind="opening",
                qty_delta_packs=line["qty_packs"], value_delta_twd=line["line_value_twd"],
                occurred_at=occurred_at, idempotency_key=f"opening-move|{key}|{line['sku']}",
                source_filename=path.name, dataset_kind=settings.dataset_kind)
            result.inserted_rows += 1
        result.inserted_events += emit_event(event_type="inventory.opening_counted",
            entity_table="ops.stockcount", entity_id=count.pk, occurred_at=occurred_at,
            idempotency_key=f"opening-count|{settings.dataset_kind}", payload=payload,
            source_filename=path.name, dataset_kind=settings.dataset_kind)
    else:
        for line in lines:
            sku = line["sku"]
            position = positions[sku]
            delta = position.qty_packs - Decimal(line["qty_packs"])
            if not delta:
                continue
            value = (position.value_twd * delta / position.qty_packs).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if value <= 0:
                raise ImportRefused(f"count {sku} adjustment rounds to zero WAC value")
            InventoryMove.objects.create(product_id=sku, kind="adjusted", qty_delta_packs=-int(delta),
                value_delta_twd=-value, occurred_at=occurred_at,
                idempotency_key=f"adjustment-move|{key}|{sku}", source_filename=path.name,
                dataset_kind=settings.dataset_kind)
            result.inserted_rows += 1
            candidate = LedgerEvent(event_type="inventory.adjusted", entity_table="ops.stockcountline",
                entity_id=line_models[sku].pk, occurred_at=occurred_at,
                payload=source.payload_for("inventory.adjusted", sku=sku, delta=delta,
                                           evidence=evidence, value=value),
                idempotency_key=f"inventory.adjusted|{key}|{sku}", source_filename=path.name,
                dataset_kind=settings.dataset_kind)
            try:
                plan(candidate)
            except PostingError as exc:
                raise ImportRefused(f"count {sku} adjustment posting rule refused: {exc}") from exc
            result.inserted_events += emit_event(event_type="inventory.adjusted",
                entity_table="ops.stockcountline", entity_id=line_models[sku].pk,
                occurred_at=occurred_at, idempotency_key=candidate.idempotency_key,
                payload=candidate.payload, source_filename=path.name, dataset_kind=settings.dataset_kind)
    return result
