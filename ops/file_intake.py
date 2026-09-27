"""Manifest-driven operational CSV intakes; dry-run is the default."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Sum

from acct.models import Account, WacPosition
from acct.posting import PostingError, plan
from core.models import DatasetSettings
from ops.etsy_import import emit_event
from ops.intake import ImportRefused, IntakeManifest, prepare_source
from ops.models import (NOT_APPLICABLE, PO_INCOTERMS, PO_STATUSES, PRODUCT_TYPES, InventoryMove,
                        LedgerEvent, Product, ProductComplianceChange, IgDeal, IgDealStatus, Order,
                        PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus, Receipt, StockCount,
                        StockCountLine, Supplier, SupplierChange)
from ops.compliance import PoBlocked, assert_po_eligible
from ops.pii import refuse_pii

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
RECEIPT_CATEGORIES = {"advertising", "rent", "software", "professional", "utilities",
                      "wages", "bank_fee", "other"}
CONDITIONS = {"sellable", "damaged_unsellable"}
INCOTERMS = set(PO_INCOTERMS)  # the G-0 enum, shared with purchase orders
TAX_ID_STATES = {"yes", "no", "unknown"}
COUNTRY_CODES = set(
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW".split()
)
CURRENCY_CODES = set(
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HRK HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW UZS VED VES VND VUV WST XAF XAG XAU XBA XBB XBC XBD XCD XCG XDR XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWG".split()
)
SKU_PATTERN = re.compile(r"TS-[A-Z]{2}-\d{3}-[SMLP]\Z")
PACKAGING_SKU_PATTERN = re.compile(r"PKG-[A-Z]{2,8}-[A-Z]{2,4}\Z")
DEAL_PATTERN = re.compile(r"IG-\d{6}-\d{3}\Z")
CUSTOMER_PATTERN = re.compile(r"C-\d{4,}\Z")
PHONE_PATTERN = re.compile(r"\+?\d[\d\s-]{7,}")
IG_STATUSES = ("enquiry", "quoted", "paid", "shipped", "followed_up", "lost")
IG_STATUS_RANK = {status: rank for rank, status in enumerate(IG_STATUSES)}
LOST_REASONS = {"no_reply", "price", "shipping_cost", "out_of_stock", "other"}
TZ = ZoneInfo("Asia/Taipei")


@dataclass
class IntakeResult:
    parsed_rows: int = 0
    inserted_rows: int = 0
    inserted_events: int = 0
    would_write_rows: int = 0


def load_schema(kind: str) -> dict:
    version = {"products": 3, "counts": 2, "ig_deals": 2}.get(kind, 1)
    fixture = json.loads((SCHEMAS / f"{kind}_header_v{version}.json").read_text())
    if fixture.get("source") not in {"authored", "observed"}:
        raise ImportRefused(f"{kind} schema fixture must declare source as authored or observed")
    return fixture


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
    return {"sku": sku, "qty_pieces": str(delta), "evidence_ref": evidence,
            "source_value_twd": str(value)}


MANIFESTS: dict[str, Callable[[], IntakeManifest]] = {}


def register_manifest(kind: str, builder: Callable[[], IntakeManifest]) -> None:
    """Register an intake source without changing manifest dispatch code."""
    if kind in MANIFESTS:
        raise RuntimeError(f"Duplicate intake manifest registration: {kind}")
    MANIFESTS[kind] = builder


def manifest(kind: str) -> IntakeManifest:
    try:
        return MANIFESTS[kind]()
    except KeyError as exc:
        raise ImportRefused(f"Unknown intake kind {kind}") from exc


def _receipt_manifest() -> IntakeManifest:
    fixture = load_schema("receipts")
    return IntakeManifest(
        kind="receipts", header=tuple(fixture["header"]),
        optional_columns=tuple(fixture.get("optional_columns", [])), verified=fixture["verified"],
        actual_filename=re.compile(r"receipts_\d{4}-(?:0[1-9]|1[0-2])\.csv\Z"),
        target_models=("Receipt",), events=("cost.recorded",),
        natural_key="dataset + evidence_ref",
        key_from=lambda row: _digest(row["evidence_ref"]),
        payload_builders={"cost.recorded": lambda row: _receipt_payload(row)},
    )


def _count_manifest() -> IntakeManifest:
    fixture = load_schema("counts")
    return IntakeManifest(
        kind="counts", header=tuple(fixture["header"]),
        optional_columns=tuple(fixture.get("optional_columns", [])), verified=fixture["verified"],
        actual_filename=re.compile(r"count_\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\.csv\Z"),
        target_models=("StockCount", "StockCountLine", "InventoryMove"),
        events=("inventory.opening_counted", "inventory.adjusted"),
        natural_key="dataset + count evidence_ref, then SKU",
        key_from=lambda row: _digest(row["evidence_ref"]),
        payload_builders={
            "inventory.opening_counted": lambda counted_at, evidence, lines, total:
                _opening_payload(counted_at, evidence, lines, total),
            "inventory.adjusted": lambda sku, delta, evidence, value:
                _adjustment_payload(sku, delta, evidence, value),
        },
        version=2,
    )


def _reference_manifest(kind: str, target_models: tuple[str, ...]) -> IntakeManifest:
    fixture = load_schema(kind)
    if fixture["source"] != "authored":
        raise ImportRefused(f"{kind} schema fixture must have source authored")
    return IntakeManifest(
        kind=kind, header=tuple(fixture["header"]), optional_columns=(),
        verified=fixture["verified"],
        actual_filename=re.compile(rf"{kind}_\d{{4}}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\.csv\Z"),
        target_models=target_models, events=(), natural_key=f"dataset + {kind} natural key",
        sample_filename=re.compile(rf"SAMPLE_{kind}_\d{{4}}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\.csv\Z"),
        version=3 if kind == "products" else 1,
    )


def _ig_manifest() -> IntakeManifest:
    fixture = load_schema("ig_deals")
    if fixture["source"] != "authored":
        raise ImportRefused("ig_deals schema fixture must have source authored")
    month = r"\d{4}-(?:0[1-9]|1[0-2])"
    return IntakeManifest(
        kind="ig_deals", header=tuple(fixture["header"]), optional_columns=(),
        verified=fixture["verified"],
        actual_filename=re.compile(rf"ig_deals_{month}\.csv\Z"),
        sample_filename=re.compile(rf"SAMPLE_ig_deals_{month}\.csv\Z"),
        target_models=("IgDeal", "IgDealStatus"), events=(),
        natural_key="dataset + deal_id + line_no",
        version=2,
    )


register_manifest("receipts", _receipt_manifest)
register_manifest("counts", _count_manifest)
register_manifest("suppliers", lambda: _reference_manifest(
    "suppliers", ("Supplier", "SupplierChange")))
register_manifest("products", lambda: _reference_manifest(
    "products", ("Product", "ProductComplianceChange")))
register_manifest("ig_deals", _ig_manifest)


def _po_manifest() -> IntakeManifest:
    fixture = load_schema("po")
    if fixture["source"] != "authored":
        raise ImportRefused("po schema fixture must have source authored")
    number = r"PO-\d{4}-\d{3}"
    return IntakeManifest(
        kind="po", header=tuple(fixture["header"]), optional_columns=(),
        verified=fixture["verified"],
        actual_filename=re.compile(rf"po_{number}\.csv\Z"),
        sample_filename=re.compile(rf"SAMPLE_po_{number}\.csv\Z"),
        target_models=("PurchaseOrder", "PurchaseOrderLine", "PurchaseOrderStatus"), events=(),
        natural_key="dataset + po_number + line_no",
    )


register_manifest("po", _po_manifest)


def _required(row: dict, field: str) -> str:
    value = row[field].strip()
    if not value:
        raise ImportRefused(f"{field} is required")
    return value


def _supplier_row(row: dict, columns) -> dict:
    refuse_pii(row, columns)
    supplier_ref = _required(row, "supplier_ref")
    if not re.fullmatch(r"SUP-\d{3}", supplier_ref):
        raise ImportRefused("supplier_ref must match ^SUP-\\d{3}$")
    country = _required(row, "country")
    if country not in COUNTRY_CODES:
        raise ImportRefused("country must be an ISO 3166-1 alpha-2 code")
    currency = _required(row, "currency")
    if currency not in CURRENCY_CODES:
        raise ImportRefused("currency must be an ISO 4217 code in three uppercase letters")
    incoterm = _required(row, "default_incoterm")
    if incoterm not in INCOTERMS:
        raise ImportRefused("default_incoterm is not an allowed Incoterm")
    tax_state = _required(row, "can_invoice_to_tax_id")
    if tax_state not in TAX_ID_STATES:
        raise ImportRefused("can_invoice_to_tax_id must be yes, no or unknown")
    declaration = row["declaration_ref"].strip()
    if declaration and not declaration.startswith("compliance/suppliers/"):
        raise ImportRefused("declaration_ref must be blank or start with compliance/suppliers/")
    return {
        "supplier_ref": supplier_ref,
        "legal_name": _required(row, "legal_name"),
        "country": country,
        "currency": currency,
        "default_incoterm": incoterm,
        "payment_terms": _required(row, "payment_terms"),
        "can_invoice_to_tax_id": tax_state,
        "declaration_ref": declaration,
        "evidence_ref": _required(row, "evidence_ref"),
    }


@transaction.atomic
def import_suppliers(path, *, commit: bool = False) -> IntakeResult:
    path = Path(path)
    settings = DatasetSettings.objects.select_for_update().get(pk=1)
    source = manifest("suppliers")
    rows = prepare_source(path, settings.dataset_kind, source, commit=commit)
    parsed = [_supplier_row(row, source.header) for row in rows]
    refs = [row["supplier_ref"] for row in parsed]
    if len(refs) != len(set(refs)):
        raise ImportRefused("supplier_ref repeats in one file")
    existing = {item.supplier_ref: item for item in Supplier.objects.select_for_update().filter(
        dataset_kind=settings.dataset_kind)}
    missing = sorted(set(existing) - set(refs))
    if missing:
        raise ImportRefused(f"a missing supplier is not a deletion: {', '.join(missing)}")
    mutable = {"declaration_ref", "can_invoice_to_tax_id", "payment_terms"}
    ignored = {"supplier_ref", "evidence_ref"}
    changes = []
    for row in parsed:
        prior = existing.get(row["supplier_ref"])
        if not prior:
            continue
        for field, value in row.items():
            if field in ignored or getattr(prior, field) == value:
                continue
            if field not in mutable:
                raise ImportRefused(f"supplier field {field} cannot change")
            changes.append((prior, field, getattr(prior, field), value, row["evidence_ref"]))
    result = IntakeResult(parsed_rows=len(parsed))
    result.would_write_rows = len([row for row in parsed if row["supplier_ref"] not in existing]) + len(changes)
    if not commit:
        return result
    for row in parsed:
        if row["supplier_ref"] in existing:
            continue
        Supplier.objects.create(**row, source_filename=path.name,
                                dataset_kind=settings.dataset_kind)
        result.inserted_rows += 1
    changed_suppliers = set()
    for prior, field, old, new, evidence in changes:
        SupplierChange.objects.create(
            supplier_ref=prior.supplier_ref, field=field, old=old, new=new,
            source_filename=path.name, dataset_kind=settings.dataset_kind,
            evidence_ref=evidence,
        )
        setattr(prior, field, new)
        prior.evidence_ref = evidence
        prior.source_filename = path.name
        changed_suppliers.add(prior)
        result.inserted_rows += 1
    for prior in changed_suppliers:
        prior.save(update_fields=["declaration_ref", "can_invoice_to_tax_id", "payment_terms",
                                  "evidence_ref", "source_filename"])
    return result


def _product_row(row: dict, columns) -> dict:
    refuse_pii(row, columns)
    sku = _required(row, "sku")
    product_type = _required(row, "product_type")
    if product_type not in PRODUCT_TYPES:
        raise ImportRefused(f"product {sku} product_type must be sellable or packaging")
    pattern = SKU_PATTERN if product_type == "sellable" else PACKAGING_SKU_PATTERN
    if not pattern.fullmatch(sku):
        raise ImportRefused(f"sku does not match the {product_type} product mapping pattern: {sku}")
    raw_qty = _required(row, "pieces_per_sale_unit")
    if not raw_qty.isdigit() or int(raw_qty) <= 0:
        raise ImportRefused(f"product {sku} pieces_per_sale_unit must be a positive whole number")
    ingredient = _required(row, "ingredient_ref")
    if product_type == "packaging":
        if ingredient != NOT_APPLICABLE:
            raise ImportRefused(f"packaging product {sku} ingredient_ref must be {NOT_APPLICABLE}")
    elif ingredient == NOT_APPLICABLE:
        raise ImportRefused(f"sellable product {sku} ingredient_ref cannot be {NOT_APPLICABLE}; "
                            "only packaging may carry it")
    elif ingredient != "UNKNOWN" and not ingredient.startswith("compliance/suppliers/"):
        raise ImportRefused("ingredient_ref must be UNKNOWN or start with compliance/suppliers/")
    return {
        "sku": sku,
        "name": _required(row, "name"),
        "pieces_per_sale_unit": int(raw_qty),
        "supplier_ref": row["supplier_ref"].strip(),
        "ingredient_ref": ingredient,
        "evidence_ref": _required(row, "evidence_ref"),
        "product_type": product_type,
    }


@transaction.atomic
def import_products(path, *, commit: bool = False) -> IntakeResult:
    path = Path(path)
    settings = DatasetSettings.objects.select_for_update().get(pk=1)
    source = manifest("products")
    rows = prepare_source(path, settings.dataset_kind, source, commit=commit)
    parsed = [_product_row(row, source.header) for row in rows]
    skus = [row["sku"] for row in parsed]
    if len(skus) != len(set(skus)):
        raise ImportRefused("duplicate sku in product file")
    supplier_refs = {row["supplier_ref"] for row in parsed if row["supplier_ref"]}
    suppliers = {item.supplier_ref: item for item in Supplier.objects.filter(
        dataset_kind=settings.dataset_kind, supplier_ref__in=supplier_refs)}
    unknown = sorted(supplier_refs - set(suppliers))
    if unknown:
        raise ImportRefused(f"unknown supplier_ref: {', '.join(unknown)}")
    for row in parsed:
        supplier = suppliers.get(row["supplier_ref"])
        if row["ingredient_ref"].startswith("compliance/suppliers/") and (
                supplier is None or not supplier.declaration_ref):
            raise ImportRefused(
                f"product {row['sku']}: a product cannot be cleared by a supplier with no declaration on file"
            )
    existing = Product.objects.select_for_update().in_bulk(skus)
    changes = []
    for row in parsed:
        prior = existing.get(row["sku"])
        if not prior:
            continue
        comparisons = {
            "name": row["name"], "pieces_per_sale_unit": row["pieces_per_sale_unit"],
            "supplier": suppliers.get(row["supplier_ref"]), "product_type": row["product_type"],
        }
        for field, value in comparisons.items():
            if getattr(prior, field) != value:
                raise ImportRefused(f"product field {field} cannot change")
        if prior.ingredient_ref != row["ingredient_ref"]:
            changes.append((prior, row))
    result = IntakeResult(parsed_rows=len(parsed))
    result.would_write_rows = len([row for row in parsed if row["sku"] not in existing]) + len(changes)
    if not commit:
        return result
    for row in parsed:
        if row["sku"] in existing:
            continue
        Product.objects.create(
            sku=row["sku"], name=row["name"], uom="PC",
            pieces_per_sale_unit=row["pieces_per_sale_unit"],
            supplier=suppliers.get(row["supplier_ref"]), ingredient_ref=row["ingredient_ref"],
            product_type=row["product_type"],
        )
        result.inserted_rows += 1
    for prior, row in changes:
        ProductComplianceChange.objects.create(
            sku=prior.sku, field="ingredient_ref", old=prior.ingredient_ref,
            new=row["ingredient_ref"], source_filename=path.name,
            dataset_kind=settings.dataset_kind, evidence_ref=row["evidence_ref"],
        )
        prior.ingredient_ref = row["ingredient_ref"]
        prior.save(update_fields=["ingredient_ref"])
        result.inserted_rows += 1
    return result


def _optional_date(raw: str, field: str):
    return _date(raw, field) if raw.strip() else None


def _optional_money(raw: str, field: str):
    return _money(raw, field) if raw.strip() else None


def _refuse_ig_date_order(deal_id, enquiry_at, quoted_at, paid_at, ship_date, follow_up_on):
    previous_field, previous_date = "enquiry_at", enquiry_at
    for field, value in (("quoted_at", quoted_at), ("paid_at", paid_at),
                         ("ship_date", ship_date)):
        if value is None:
            continue
        if value < previous_date:
            raise ImportRefused(
                f"deal {deal_id}: {field} {value} is before {previous_field} {previous_date}"
            )
        previous_field, previous_date = field, value
    if follow_up_on is not None and follow_up_on < enquiry_at:
        raise ImportRefused(
            f"deal {deal_id}: follow_up_on {follow_up_on} is before enquiry_at {enquiry_at}"
        )


def _ig_row(row: dict, columns) -> dict:
    refuse_pii(row, columns)
    evidence = _required(row, "evidence_ref")
    if PHONE_PATTERN.search(evidence):
        raise ImportRefused("phone-shaped value detected in evidence_ref")
    deal_id = _required(row, "deal_id")
    if not DEAL_PATTERN.fullmatch(deal_id):
        raise ImportRefused(f"deal_id must match ^IG-\\d{{6}}-\\d{{3}}$: {deal_id}")
    raw_line = _required(row, "line_no")
    if not raw_line.isdigit() or int(raw_line) < 1:
        raise ImportRefused(f"deal {deal_id} line_no must be an integer >= 1")
    customer_ref = _required(row, "customer_ref")
    if not CUSTOMER_PATTERN.fullmatch(customer_ref):
        raise ImportRefused(f"customer_ref must match ^C-\\d{{4,}}$: {customer_ref}")
    status = _required(row, "status")
    if status not in IG_STATUSES:
        raise ImportRefused(f"deal {deal_id} status is not allowed: {status}")
    enquiry_at = _date(_required(row, "enquiry_at"), "enquiry_at")
    quoted_at = _optional_date(row["quoted_at"], "quoted_at")
    quote = _optional_money(row["quote_twd"], "quote_twd")
    follow_up = _optional_date(row["follow_up_on"], "follow_up_on")
    lost_reason = row["lost_reason"].strip()
    quoted_or_later = status in {"quoted", "paid", "shipped", "followed_up"}
    paid_or_later = status in {"paid", "shipped", "followed_up"}
    shipped_or_later = status in {"shipped", "followed_up"}
    if quoted_or_later and (quoted_at is None or quote is None or quote <= 0):
        raise ImportRefused(f"deal {deal_id} quoted_at and positive quote_twd are required from quoted onward")
    if status in {"enquiry", "quoted"} and follow_up is None:
        raise ImportRefused(f"deal {deal_id}: an open deal with no next action")
    if status == "lost" and lost_reason not in LOST_REASONS:
        raise ImportRefused(f"deal {deal_id} lost_reason is required when lost")
    if status != "lost" and lost_reason:
        raise ImportRefused(f"deal {deal_id} lost_reason is allowed only when lost")
    sku = row["sku"].strip()
    raw_qty = row["qty_sale_units"].strip()
    unit_price = _optional_money(row["unit_price_twd"], "unit_price_twd")
    shipping = _optional_money(row["shipping_charged_twd"], "shipping_charged_twd")
    country = row["ship_country"].strip()
    paid_at = _optional_date(row["paid_at"], "paid_at")
    wallet = row["wallet_txn_id"].strip()
    if paid_or_later:
        if not sku:
            raise ImportRefused(f"deal {deal_id} sku is required from paid onward")
        if not raw_qty.isdigit() or int(raw_qty) <= 0:
            raise ImportRefused(f"deal {deal_id} qty_sale_units must be a whole number > 0 from paid onward")
        if unit_price is None or unit_price <= 0:
            raise ImportRefused(f"deal {deal_id} unit_price_twd must be positive from paid onward")
        if shipping is None:
            raise ImportRefused(f"deal {deal_id} shipping_charged_twd is required from paid onward")
        if country not in COUNTRY_CODES:
            raise ImportRefused(f"deal {deal_id} ship_country must be ISO 3166-1 alpha-2 from paid onward")
        if paid_at is None:
            raise ImportRefused(f"deal {deal_id} paid_at is required from paid onward")
        if not wallet:
            raise ImportRefused(f"deal {deal_id} wallet_txn_id is required from paid onward")
    qty = int(raw_qty) if raw_qty else None
    ship_date = _optional_date(row["ship_date"], "ship_date")
    if shipped_or_later and ship_date is None:
        raise ImportRefused(f"deal {deal_id} ship_date is required from shipped onward")
    _refuse_ig_date_order(
        deal_id, enquiry_at, quoted_at, paid_at, ship_date, follow_up,
    )
    consent = row["consent_marketing"].strip()
    if consent not in {"", "yes", "no"}:
        raise ImportRefused(f"deal {deal_id} consent_marketing must be yes, no or blank")
    journey = _required(row, "journey_sent")
    if journey not in {"none", "d0", "d10", "d30"}:
        raise ImportRefused(f"deal {deal_id} journey_sent must be none, d0, d10 or d30")
    return {
        "deal_id": deal_id, "line_no": int(raw_line), "customer_ref": customer_ref,
        "status": status, "enquiry_at": enquiry_at, "quoted_at": quoted_at,
        "quote_twd": quote, "follow_up_on": follow_up, "lost_reason": lost_reason,
        "product_id": sku or None, "qty_sale_units": qty, "unit_price_twd": unit_price,
        "shipping_charged_twd": shipping, "ship_country": country, "paid_at": paid_at,
        "wallet_txn_id": wallet, "ship_date": ship_date, "consent_marketing": consent,
        "journey_sent": journey, "evidence_ref": evidence,
    }


def _ig_effective_on(row: dict) -> date:
    return row["ship_date"] or row["paid_at"] or row["quoted_at"] or row["enquiry_at"]


@transaction.atomic
def import_ig_deals(path, *, commit: bool = False) -> IntakeResult:
    path = Path(path)
    settings = DatasetSettings.objects.select_for_update().get(pk=1)
    source = manifest("ig_deals")
    source_rows = prepare_source(path, settings.dataset_kind, source, commit=commit)
    parsed = [_ig_row(row, source.header) for row in source_rows]
    filename_month = path.name.removeprefix("SAMPLE_").removeprefix("ig_deals_").removesuffix(".csv")
    for row in parsed:
        enquiry_month = row["enquiry_at"].strftime("%Y-%m")
        if enquiry_month != filename_month or row["deal_id"][3:9] != enquiry_month.replace("-", ""):
            raise ImportRefused(f"deal {row['deal_id']} enquiry_at and deal_id month must match filename month {filename_month}")
    keys = [(row["deal_id"], row["line_no"]) for row in parsed]
    if len(keys) != len(set(keys)):
        raise ImportRefused("Instagram file repeats a (deal_id, line_no)")
    by_deal = {}
    for row in parsed:
        by_deal.setdefault(row["deal_id"], []).append(row)
    common_fields = ("customer_ref", "status", "enquiry_at", "quoted_at", "quote_twd",
                     "follow_up_on", "lost_reason", "shipping_charged_twd", "ship_country",
                     "paid_at", "wallet_txn_id", "ship_date", "consent_marketing",
                     "journey_sent", "evidence_ref")
    for deal_id, rows in by_deal.items():
        numbers = sorted(row["line_no"] for row in rows)
        if numbers != list(range(1, len(numbers) + 1)):
            raise ImportRefused(f"deal {deal_id} has line_no gaps")
        for field in common_fields:
            if len({row[field] for row in rows}) != 1:
                raise ImportRefused(f"deal {deal_id} has conflicting {field} across lines")
    if settings.dataset_kind == "ACTUAL" and any(
            row["status"] in {"paid", "shipped", "followed_up"} for row in parsed):
        raise ImportRefused(
            "paid Instagram deals cannot be committed as ACTUAL until H-0b (wallet statement + ledger) "
            "is built — a paid deal with no payment evidence is cash nobody can prove"
        )
    product_ids = {row["product_id"] for row in parsed if row["product_id"]}
    unknown_products = sorted(product_ids - set(Product.objects.filter(
        pk__in=product_ids).values_list("pk", flat=True)))
    if unknown_products:
        raise ImportRefused(f"Instagram deal has unknown sku(s): {', '.join(unknown_products)}")
    customer_refs = {row["customer_ref"] for row in parsed}
    etsy_refs = sorted(Order.objects.filter(channel__code__iexact="etsy",
        channel_order_id__in=customer_refs).values_list("channel_order_id", flat=True))
    if etsy_refs:
        raise ImportRefused(f"customer_ref appears on an Etsy order; C- codes are Instagram-only: {', '.join(etsy_refs)}")
    wallets = {}
    for row in parsed:
        if row["wallet_txn_id"]:
            wallets.setdefault(row["wallet_txn_id"], set()).add(row["deal_id"])
    repeated = sorted(wallet for wallet, deals in wallets.items() if len(deals) > 1)
    for wallet, deal_id in IgDeal.objects.filter(dataset_kind=settings.dataset_kind,
            wallet_txn_id__in=wallets).values_list("wallet_txn_id", "deal_id"):
        wallets[wallet].add(deal_id)
        if len(wallets[wallet]) > 1:
            repeated.append(wallet)
    if repeated:
        raise ImportRefused(f"wallet_txn_id is used by two different deal_ids: {', '.join(sorted(set(repeated)))}")
    existing_rows = list(IgDeal.objects.select_for_update().filter(
        dataset_kind=settings.dataset_kind, deal_id__in=by_deal).order_by("deal_id", "line_no"))
    existing_by_deal = {}
    for item in existing_rows:
        existing_by_deal.setdefault(item.deal_id, []).append(item)
    transitions = []
    protected = ("quote_twd", "product_id", "qty_sale_units", "unit_price_twd", "wallet_txn_id")
    all_fields = tuple(field.name for field in IgDeal._meta.fields
                       if field.name not in {"id", "source_filename", "dataset_kind", "product"}) + ("product_id",)
    for deal_id, rows in by_deal.items():
        prior_rows = existing_by_deal.get(deal_id, [])
        if not prior_rows:
            transitions.append((deal_id, None, rows[0]))
            continue
        prior_statuses = {item.status for item in prior_rows}
        if len(prior_statuses) != 1:
            raise ImportRefused(f"deal {deal_id} stored lines have conflicting status")
        old_status, new_status = prior_rows[0].status, rows[0]["status"]
        old_lines = {item.line_no for item in prior_rows}
        new_lines = {row["line_no"] for row in rows}
        omitted = sorted(old_lines - new_lines)
        if omitted:
            raise ImportRefused(f"deal {deal_id} omits existing line_no(s): {', '.join(map(str, omitted))}")
        if old_status == "lost" and new_status != "lost" or (
                old_status != "lost" and new_status != "lost" and
                IG_STATUS_RANK[new_status] < IG_STATUS_RANK[old_status]):
            raise ImportRefused(f"deal {deal_id} status cannot move backward from {old_status} to {new_status}")
        prior_by_line = {item.line_no: item for item in prior_rows}
        changed = bool(new_lines - old_lines)
        for row in rows:
            prior = prior_by_line.get(row["line_no"])
            if prior is None:
                continue
            if prior.customer_ref != row["customer_ref"]:
                raise ImportRefused(f"deal {deal_id} customer_ref cannot change")
            if prior.enquiry_at != row["enquiry_at"]:
                raise ImportRefused(f"deal {deal_id} enquiry_at cannot change")
            if row["status"] in {"paid", "shipped", "followed_up"} and prior.quote_twd is not None and prior.quote_twd != row["quote_twd"]:
                raise ImportRefused(f"deal {deal_id} quote_twd cannot change once status >= paid")
            if old_status in {"paid", "shipped", "followed_up"}:
                for field in protected:
                    if getattr(prior, field) != row[field]:
                        label = "sku" if field == "product_id" else field
                        raise ImportRefused(f"deal {deal_id} {label} cannot change once status >= paid")
            changed = changed or any(getattr(prior, field) != row[field] for field in all_fields)
        if new_status == old_status and changed:
            raise ImportRefused(f"deal {deal_id} current state can change only with a forward status move")
        if new_status != old_status:
            transitions.append((deal_id, old_status, rows[0]))
    result = IntakeResult(parsed_rows=len(parsed))
    new_rows = sum(1 for row in parsed if not any(
        item.line_no == row["line_no"] for item in existing_by_deal.get(row["deal_id"], [])))
    result.would_write_rows = new_rows + len(transitions)
    if not commit:
        return result
    # History is inserted first so the database current-state trigger can prove
    # every update is explained. The surrounding atomic block rolls both back together.
    for deal_id, _old_status, row in transitions:
        IgDealStatus.objects.create(
            deal_id=deal_id, status=row["status"], effective_on=_ig_effective_on(row),
            source_filename=path.name, dataset_kind=settings.dataset_kind,
        )
        result.inserted_rows += 1
    for deal_id, rows in by_deal.items():
        prior_by_line = {item.line_no: item for item in existing_by_deal.get(deal_id, [])}
        for row in rows:
            values = {key: value for key, value in row.items() if key != "product_id"}
            values["product_id"] = row["product_id"]
            prior = prior_by_line.get(row["line_no"])
            if prior is None:
                IgDeal.objects.create(**values, source_filename=path.name,
                                      dataset_kind=settings.dataset_kind)
                result.inserted_rows += 1
            elif prior.status != row["status"]:
                for field, value in values.items():
                    setattr(prior, field, value)
                prior.source_filename = path.name
                # ``product_id`` is a field attname rather than the model field name;
                # a full save also keeps the status and its complete new snapshot atomic.
                prior.save()
    return result


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
        raw_qty = row["qty_pieces"].strip()
        if not raw_qty.isdigit():
            raise ImportRefused(f"count {sku} qty_pieces must be a nonnegative whole number; blank is unknown")
        qty = int(raw_qty)
        unit = _money(row["agreed_unit_cost_twd"], "agreed_unit_cost_twd")
        condition = row["condition"].strip()
        if condition not in CONDITIONS:
            raise ImportRefused(f"count {sku} condition must be sellable or damaged_unsellable")
        lines.append({"sku": sku, "qty_pieces": qty, "agreed_unit_cost_twd": unit,
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
        saved = [(line.product_id, line.qty_pieces, line.agreed_unit_cost_twd,
                  line.line_value_twd, line.condition) for line in prior.lines.order_by("product_id")]
        observed = [(line["sku"], line["qty_pieces"], line["agreed_unit_cost_twd"],
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
            product_id__in=positions).values("product_id").annotate(total=Sum("qty_delta_pieces"))
            .values_list("product_id", "total"))
        for line in lines:
            sku, target = line["sku"], line["qty_pieces"]
            position = positions.get(sku)
            if position is None or position.qty_pieces != Decimal(onhand.get(sku, 0)):
                raise ImportRefused(f"count {sku} has no tied WAC/on-hand position")
            if Decimal(target) > position.qty_pieces:
                raise ImportRefused(f"count {sku} implies an increase; a receipt is needed, not an adjustment")
            if target < position.qty_pieces and position.value_twd <= 0:
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
            qty_pieces=line["qty_pieces"], agreed_unit_cost_twd=line["agreed_unit_cost_twd"],
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
                qty_delta_pieces=line["qty_pieces"], value_delta_twd=line["line_value_twd"],
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
            delta = position.qty_pieces - Decimal(line["qty_pieces"])
            if not delta:
                continue
            value = (position.value_twd * delta / position.qty_pieces).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if value <= 0:
                raise ImportRefused(f"count {sku} adjustment rounds to zero WAC value")
            InventoryMove.objects.create(product_id=sku, kind="adjusted", qty_delta_pieces=-int(delta),
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


PO_NUMBER_PATTERN = re.compile(r"PO-\d{4}-\d{3}\Z")
PO_FORWARD = {"draft": ("sent", "cancelled"), "sent": ("acknowledged", "cancelled"),
              "acknowledged": ("cancelled",), "cancelled": ()}
# A PO is always created as draft; a file first seen later walks these steps.
PO_STEPS_FROM_DRAFT = {"draft": (), "sent": ("sent",), "acknowledged": ("sent", "acknowledged"),
                       "cancelled": ("cancelled",)}
PO_HEADER_FIELDS = ("po_number", "supplier_ref", "po_date", "target_delivery_date", "currency",
                    "payment_terms", "incoterm", "quote_ref", "status")
PO_FROZEN_HEADER = ("supplier_ref", "currency", "quote_ref")
PO_FROZEN_LINE = ("sku", "qty_pieces", "unit_price_twd", "setup_charge_twd")
PO_LINE_FIELDS = PO_FROZEN_LINE + ("line_total_twd", "min_order_qty_pieces", "artwork_ref", "evidence_ref")


def _whole_pieces(raw: str, field: str, context: str) -> int:
    raw = raw.strip()
    if not raw.isdigit() or int(raw) <= 0:
        raise ImportRefused(f"{context} {field} must be a whole number of pieces > 0")
    return int(raw)


def _po_row(row: dict, columns) -> dict:
    refuse_pii(row, columns)
    po_number = _required(row, "po_number")
    if not PO_NUMBER_PATTERN.fullmatch(po_number):
        raise ImportRefused(f"po_number must match ^PO-\\d{{4}}-\\d{{3}}$: {po_number}")
    raw_line = _required(row, "line_no")
    if not raw_line.isdigit() or int(raw_line) < 1:
        raise ImportRefused(f"PO {po_number} line_no must be an integer >= 1")
    line_no = int(raw_line)
    context = f"PO {po_number} line {line_no}"
    status = _required(row, "status")
    if status not in PO_STATUSES:
        raise ImportRefused(f"PO {po_number} status must be draft, sent, acknowledged or cancelled: {status}")
    incoterm = _required(row, "incoterm")
    if incoterm not in INCOTERMS:
        raise ImportRefused(f"PO {po_number} incoterm is not an allowed Incoterm: {incoterm}")
    quote_ref = row["quote_ref"].strip()
    if not quote_ref:
        raise ImportRefused(f"PO {po_number} quote_ref is required; a PO accepts a supplier quote")
    po_date = _date(_required(row, "po_date"), "po_date")
    target = _date(_required(row, "target_delivery_date"), "target_delivery_date")
    if target < po_date:
        raise ImportRefused(f"PO {po_number} target_delivery_date {target} is before po_date {po_date}")
    qty = _whole_pieces(row["qty_pieces"], "qty_pieces", context)
    unit_price = _money(_required(row, "unit_price_twd"), "unit_price_twd")
    if unit_price <= 0:
        raise ImportRefused(f"{context} unit_price_twd must be a positive price per piece")
    setup = _money(_required(row, "setup_charge_twd"), "setup_charge_twd")
    total = _money(_required(row, "line_total_twd"), "line_total_twd")
    expected = qty * unit_price + setup
    if total != expected:
        raise ImportRefused(
            f"{context} line_total_twd {total} disagrees with qty_pieces x unit_price_twd + "
            f"setup_charge_twd = {expected}"
        )
    raw_moq = row["min_order_qty_pieces"].strip()
    moq = _whole_pieces(raw_moq, "min_order_qty_pieces", context) if raw_moq else None
    if moq is not None and qty < moq:
        raise ImportRefused(f"{context} qty_pieces {qty} is below min_order_qty_pieces {moq}")
    return {
        "po_number": po_number, "supplier_ref": _required(row, "supplier_ref"),
        "po_date": po_date, "target_delivery_date": target,
        "currency": _required(row, "currency"), "payment_terms": _required(row, "payment_terms"),
        "incoterm": incoterm, "quote_ref": quote_ref, "status": status, "line_no": line_no,
        "sku": _required(row, "sku"), "qty_pieces": qty, "unit_price_twd": unit_price,
        "setup_charge_twd": setup, "line_total_twd": total, "min_order_qty_pieces": moq,
        "artwork_ref": row["artwork_ref"].strip(), "evidence_ref": _required(row, "evidence_ref"),
    }


def _po_line_values(row: dict) -> dict:
    values = {field: row[field] for field in PO_LINE_FIELDS if field != "sku"}
    return {**values, "product_id": row["sku"]}


def _stored_po_line(line: PurchaseOrderLine) -> dict:
    return {field: (line.product_id if field == "sku" else getattr(line, field)) for field in PO_LINE_FIELDS}


@transaction.atomic
def import_po(path, *, commit: bool = False) -> IntakeResult:
    """One file per PO. A PO is a commitment: this intake writes no ledger row (G-1 I-1)."""
    path = Path(path)
    settings = DatasetSettings.objects.select_for_update().get(pk=1)
    source = manifest("po")
    source_rows = prepare_source(path, settings.dataset_kind, source, commit=commit)
    if not source_rows:
        raise ImportRefused(f"PO file {path.name} has no lines")
    parsed = [_po_row(row, source.header) for row in source_rows]
    filename_number = path.name.removeprefix("SAMPLE_").removeprefix("po_").removesuffix(".csv")
    for row in parsed:
        if row["po_number"] != filename_number:
            raise ImportRefused(f"po_number {row['po_number']} does not match filename PO number {filename_number}")
    po_number = filename_number
    for field in PO_HEADER_FIELDS:
        if len({row[field] for row in parsed}) != 1:
            raise ImportRefused(f"PO {po_number} has conflicting {field} across lines")
    numbers = [row["line_no"] for row in parsed]
    repeated = sorted({number for number in numbers if numbers.count(number) > 1})
    if repeated:
        raise ImportRefused(f"PO {po_number} repeats line_no {', '.join(map(str, repeated))}")
    if sorted(numbers) != list(range(1, len(numbers) + 1)):
        raise ImportRefused(f"PO {po_number} has line_no gaps")
    header = parsed[0]
    supplier = Supplier.objects.filter(dataset_kind=settings.dataset_kind,
                                       supplier_ref=header["supplier_ref"]).first()
    if supplier is None:
        raise ImportRefused(f"unknown supplier_ref: {header['supplier_ref']}")
    if header["currency"] != supplier.currency:
        raise ImportRefused(f"PO {po_number} currency {header['currency']} must equal supplier "
                            f"{supplier.supplier_ref} currency {supplier.currency}")
    if header["currency"] != "TWD":
        raise ImportRefused(f"PO {po_number} currency {header['currency']} is refused: a non-TWD PO needs "
                            "the FX ruling (Agent 2 R-2.6, IFRIC 22), which does not exist yet")
    skus = {row["sku"] for row in parsed}
    unknown = sorted(skus - set(Product.objects.filter(pk__in=skus).values_list("pk", flat=True)))
    if unknown:
        raise ImportRefused(f"PO {po_number} has unknown sku(s): {', '.join(unknown)}")
    status = header["status"]
    if status in {"sent", "acknowledged"}:
        try:
            assert_po_eligible(skus)
        except PoBlocked as exc:
            raise ImportRefused(f"PO {po_number} cannot be {status}: {exc}") from exc

    existing = PurchaseOrder.objects.select_for_update().filter(
        dataset_kind=settings.dataset_kind, po_number=po_number).first()
    header_values = {"supplier_id": supplier.pk, "po_date": header["po_date"],
                     "target_delivery_date": header["target_delivery_date"],
                     "currency": header["currency"], "payment_terms": header["payment_terms"],
                     "incoterm": header["incoterm"], "quote_ref": header["quote_ref"]}
    result = IntakeResult(parsed_rows=len(parsed))
    if existing is None:
        result.would_write_rows = 2 + len(parsed) + len(PO_STEPS_FROM_DRAFT[status])
        if not commit:
            return result
        PurchaseOrderStatus.objects.create(po_number=po_number, status="draft",
                                           effective_on=header["po_date"], source_filename=path.name,
                                           dataset_kind=settings.dataset_kind)
        po = PurchaseOrder.objects.create(po_number=po_number, status="draft", **header_values,
                                          source_filename=path.name, dataset_kind=settings.dataset_kind)
        for row in parsed:
            PurchaseOrderLine.objects.create(po=po, line_no=row["line_no"], **_po_line_values(row),
                                             source_filename=path.name, dataset_kind=settings.dataset_kind)
        result.inserted_rows += 2 + len(parsed)
        for step in PO_STEPS_FROM_DRAFT[status]:
            _move_po(po, step, header["po_date"], path, settings.dataset_kind)
            result.inserted_rows += 1
        return result

    old_status = existing.status
    if status != old_status and status not in PO_FORWARD[old_status]:
        suffix = "; nothing leaves cancelled" if old_status == "cancelled" else ""
        raise ImportRefused(f"PO {po_number} status cannot move from {old_status} to {status}{suffix}")
    prior_lines = {line.line_no: line for line in existing.lines.select_for_update()}
    omitted = sorted(set(prior_lines) - set(numbers))
    if omitted:
        raise ImportRefused(f"PO {po_number} omits existing line_no(s): {', '.join(map(str, omitted))}; "
                            "a missing line is not a deletion")
    changed_header = [field for field, value in header_values.items() if getattr(existing, field) != value]
    added = [row for row in parsed if row["line_no"] not in prior_lines]
    changed_lines = []
    for row in parsed:
        prior = prior_lines.get(row["line_no"])
        if prior is None:
            continue
        stored = _stored_po_line(prior)
        fields = [field for field in PO_LINE_FIELDS if stored[field] != row[field]]
        if fields:
            changed_lines.append((prior, row, fields))
    if old_status == "cancelled" and (changed_header or added or changed_lines):
        raise ImportRefused(f"PO {po_number} is cancelled and cannot change")
    if old_status in {"sent", "acknowledged"}:
        for field in PO_FROZEN_HEADER:
            model_field = "supplier_id" if field == "supplier_ref" else field
            if model_field in changed_header:
                raise ImportRefused(f"PO {po_number} {field} cannot change once sent")
        if added:
            raise ImportRefused(f"PO {po_number} line {added[0]['line_no']} cannot be added once sent")
        for _prior, row, fields in changed_lines:
            frozen = [field for field in PO_FROZEN_LINE if field in fields]
            if frozen:
                raise ImportRefused(f"PO {po_number} line {row['line_no']} {frozen[0]} cannot change once sent")
    moving = status != old_status
    result.would_write_rows = (len(changed_lines) + len(added) +
                               (1 if changed_header or moving else 0) + (1 if moving else 0))
    if not commit:
        return result
    # Lines first, while the stored PO still has its old status: the database lets a
    # draft's lines change and refuses frozen fields after that.
    for prior, row, _fields in changed_lines:
        for field, value in _po_line_values(row).items():
            setattr(prior, field, value)
        prior.source_filename = path.name
        prior.save()
        result.inserted_rows += 1
    for row in added:
        PurchaseOrderLine.objects.create(po=existing, line_no=row["line_no"], **_po_line_values(row),
                                         source_filename=path.name, dataset_kind=settings.dataset_kind)
        result.inserted_rows += 1
    if changed_header or moving:
        for field, value in header_values.items():
            setattr(existing, field, value)
        existing.source_filename = path.name
        if moving:
            _move_po(existing, status, datetime.now(TZ).date(), path, settings.dataset_kind)
            result.inserted_rows += 1
        else:
            existing.save()
        result.inserted_rows += 1
    return result


def _move_po(po: PurchaseOrder, status: str, effective_on: date, path: Path, dataset_kind: str) -> None:
    # History first: the database trigger refuses a status with no history row.
    PurchaseOrderStatus.objects.create(po_number=po.po_number, status=status, effective_on=effective_on,
                                       source_filename=path.name, dataset_kind=dataset_kind)
    po.status = status
    po.save()
