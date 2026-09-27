"""Slice G-2: receive stock at landed cost, by three-way match.

A goods receipt (what arrived) and a supplier invoice (what was billed) are each imported
from their own file and stored append-only. When both exist for one (PO, receipt_no) and
agree with each other and with the PO, ONE `po.received` is emitted with the catalogue
Addendum G payload and posted through the existing posting path. Anything unmatched posts
nothing and is listed by /reports/po-exceptions/ (I-1). Dry-run is the default.
"""

import csv
import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from django.db import transaction
from django.db.models import Q

from acct.posting import PostingError, plan, post_event
from core.models import DatasetSettings
from ops.etsy_import import emit_event
from ops.file_intake import (IntakeResult, _date, _money, _occurred, _required, load_schema, manifest,
                             register_manifest)
from ops.intake import ImportRefused, IntakeManifest, prepare_source
from ops.landed_cost import LandedCostError, ReceiptLineInput, receipt_payload, value_receipt
from ops.models import (GoodsReceipt, GoodsReceiptLine, InventoryMove, LedgerEvent, PurchaseOrder,
                        PurchaseOrderLine, PurchaseOrderStatus, SupplierInvoice, SupplierInvoiceLine)
from ops.pii import refuse_pii

PO_NUMBER = r"PO-\d{4}-\d{3}"
DOC_NUMBER = r"[A-Z0-9][A-Z0-9-]{0,31}"
DOC_NUMBER_PATTERN = re.compile(rf"{DOC_NUMBER}\Z")
GUI_PATTERN = re.compile(r"[A-Z]{2}\d{8}\Z")
RECEIVABLE = ("sent", "acknowledged")
# Carrier freight (2172) and duty (2192) have no allocation built yet (catalogue G.5.2).
CARRIER_MARKERS = ("carrier", "duty")
GRN_HEADER_FIELDS = ("po_number", "receipt_no", "received_on")
INV_HEADER_FIELDS = ("invoice_no", "gui_no", "invoice_date", "po_number", "receipt_no", "freight_twd",
                     "tax_twd", "tax_creditable_twd", "invoice_total_twd", "deposit_applied_twd",
                     "evidence_ref")
YES_NO = {"yes": True, "no": False}
FOUR_DP = Decimal("0.0001")


def _authored(kind: str) -> dict:
    fixture = load_schema(kind)
    if fixture["source"] != "authored":
        raise ImportRefused(f"{kind} schema fixture must have source authored")
    return fixture


def _grn_manifest() -> IntakeManifest:
    fixture = _authored("grn")
    return IntakeManifest(
        kind="grn", header=tuple(fixture["header"]), optional_columns=(), verified=fixture["verified"],
        actual_filename=re.compile(rf"grn_{PO_NUMBER}_{DOC_NUMBER}\.csv\Z"),
        sample_filename=re.compile(rf"SAMPLE_grn_{PO_NUMBER}_{DOC_NUMBER}\.csv\Z"),
        target_models=("GoodsReceipt", "GoodsReceiptLine"), events=("po.received",),
        natural_key="PO + receipt_no, then PO line_no",
    )


def _inv_manifest() -> IntakeManifest:
    fixture = _authored("inv")
    return IntakeManifest(
        kind="inv", header=tuple(fixture["header"]), optional_columns=(), verified=fixture["verified"],
        actual_filename=re.compile(rf"inv_{DOC_NUMBER}\.csv\Z"),
        sample_filename=re.compile(rf"SAMPLE_inv_{DOC_NUMBER}\.csv\Z"),
        target_models=("SupplierInvoice", "SupplierInvoiceLine"), events=("po.received",),
        natural_key="dataset + invoice_no, then PO line_no",
    )


register_manifest("grn", _grn_manifest)
register_manifest("inv", _inv_manifest)


@dataclass
class ReceivingResult(IntakeResult):
    match_refusals: list[str] = field(default_factory=list)


def _refuse_carrier_columns(path: Path) -> None:
    """A receipt carrying carrier freight or duty is refused by name, before the header check."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            header = next(csv.reader(stream), [])
    except (UnicodeError, csv.Error):
        return  # read_csv names the parse failure
    carried = [column for column in header if any(marker in column.lower() for marker in CARRIER_MARKERS)]
    if carried:
        raise ImportRefused(f"{path.name} carries carrier freight or duty ({', '.join(carried)}); carrier "
                            "freight and duty on a receipt arrive in Slice I (catalogue G.5.2)")


def _pieces(raw: str, field_name: str, context: str, *, positive: bool) -> int:
    raw = raw.strip()
    if not raw.isdigit() or (positive and int(raw) <= 0):
        bound = "> 0" if positive else ">= 0"
        raise ImportRefused(f"{context} {field_name} must be a whole number of pieces {bound}")
    return int(raw)


def _yes_no(raw: str, field_name: str, context: str) -> bool:
    value = raw.strip()
    if value not in YES_NO:
        raise ImportRefused(f"{context} {field_name} must be yes or no")
    return YES_NO[value]


def _line_no(raw: str, context: str) -> int:
    raw = raw.strip()
    if not raw.isdigit() or int(raw) < 1:
        raise ImportRefused(f"{context} line_no must be an integer >= 1")
    return int(raw)


def _agree(parsed: list[dict], fields, label: str) -> dict:
    for name in fields:
        if len({row[name] for row in parsed}) != 1:
            raise ImportRefused(f"{label} has conflicting {name} across lines")
    return parsed[0]


def _no_repeats(parsed: list[dict], label: str) -> None:
    numbers = [row["line_no"] for row in parsed]
    repeated = sorted({number for number in numbers if numbers.count(number) > 1})
    if repeated:
        raise ImportRefused(f"{label} repeats line_no {', '.join(map(str, repeated))}")


def _receivable_po(dataset_kind: str, po_number: str, document: str) -> PurchaseOrder:
    po = PurchaseOrder.objects.select_for_update().filter(dataset_kind=dataset_kind, po_number=po_number).first()
    if po is None:
        raise ImportRefused(f"unknown PO: {po_number}")
    if po.status not in RECEIVABLE:
        raise ImportRefused(f"PO {po_number} is {po.status}; a {document} is accepted only against a sent or "
                            "acknowledged PO")
    return po


def in_transit_event_exists(po: PurchaseOrder) -> bool:
    """I-11: event 16 has no emitter yet; any such event for this PO blocks its receipt (G.5.5)."""
    return LedgerEvent.objects.filter(event_type="po.in_transit", dataset_kind=po.dataset_kind).filter(
        Q(entity_table="ops.purchaseorder", entity_id=po.pk) | Q(payload__po_number=po.po_number)).exists()


def _refuse_in_transit(po: PurchaseOrder) -> None:
    if in_transit_event_exists(po):
        raise ImportRefused(f"PO {po.po_number} has a po.in_transit event; a receipt after goods in transit "
                            "arrives in G-2b (catalogue G.5.5)")


def _po_lines(po: PurchaseOrder) -> dict[int, PurchaseOrderLine]:
    return {line.line_no: line for line in po.lines.select_related("product")}


# ---------------------------------------------------------------------------------------------
# Goods receipt


def _grn_row(row: dict, columns) -> dict:
    refuse_pii(row, columns)
    po_number = _required(row, "po_number")
    receipt_no = _required(row, "receipt_no")
    if not DOC_NUMBER_PATTERN.fullmatch(receipt_no):
        raise ImportRefused(f"receipt_no must match ^{DOC_NUMBER}$: {receipt_no}")
    label = f"GRN {po_number}/{receipt_no}"
    line_no = _line_no(row["line_no"], label)
    context = f"{label} line {line_no}"
    good = _pieces(row["qty_pieces_good"], "qty_pieces_good", context, positive=False)
    damaged = _pieces(row["qty_pieces_damaged"], "qty_pieces_damaged", context, positive=False)
    credited = _yes_no(row["damaged_credited"], "damaged_credited", context)
    short_close = _yes_no(row["short_close"], "short_close", context)
    reason = row["short_close_reason"].strip()
    if credited and not damaged:
        raise ImportRefused(f"{context} damaged_credited must be no when qty_pieces_damaged is 0")
    if short_close and not reason:
        raise ImportRefused(f"{context} short_close=yes needs a short_close_reason")
    if reason and not short_close:
        raise ImportRefused(f"{context} short_close_reason is allowed only with short_close=yes")
    accepted = good + (0 if credited else damaged)
    if accepted <= 0:
        raise ImportRefused(f"{context} accepts no pieces; a line with nothing received cannot carry its setup "
                            "(R-1.2)")
    return {"po_number": po_number, "receipt_no": receipt_no,
            "received_on": _date(_required(row, "received_on"), "received_on"), "line_no": line_no,
            "sku": _required(row, "sku"), "qty_pieces_good": good, "qty_pieces_damaged": damaged,
            "damaged_credited": credited, "short_close": short_close, "short_close_reason": reason,
            "evidence_ref": _required(row, "evidence_ref"), "accepted": accepted}


GRN_LINE_FIELDS = ("line_no", "sku", "qty_pieces_good", "qty_pieces_damaged", "damaged_credited",
                   "short_close", "short_close_reason", "evidence_ref")


def _stored_grn_line(line: GoodsReceiptLine) -> dict:
    return {name: (line.product_id if name == "sku" else getattr(line, name)) for name in GRN_LINE_FIELDS}


@transaction.atomic
def import_grn(path, *, commit: bool = False) -> ReceivingResult:
    path = Path(path)
    settings = DatasetSettings.objects.select_for_update().get(pk=1)
    source = manifest("grn")
    _refuse_carrier_columns(path)
    source_rows = prepare_source(path, settings.dataset_kind, source, commit=commit)
    if not source_rows:
        raise ImportRefused(f"GRN file {path.name} has no lines")
    parsed = [_grn_row(row, source.header) for row in source_rows]
    stem = path.name.removeprefix("SAMPLE_").removeprefix("grn_").removesuffix(".csv")
    file_po, _, file_receipt = stem.partition("_")
    for row in parsed:
        if (row["po_number"], row["receipt_no"]) != (file_po, file_receipt):
            raise ImportRefused(f"po_number/receipt_no {row['po_number']}/{row['receipt_no']} does not match "
                                f"filename {file_po}/{file_receipt}")
    label = f"GRN {file_po}/{file_receipt}"
    header = _agree(parsed, GRN_HEADER_FIELDS, label)
    _no_repeats(parsed, label)
    result = ReceivingResult(parsed_rows=len(parsed))

    po = PurchaseOrder.objects.select_for_update().filter(dataset_kind=settings.dataset_kind,
                                                          po_number=file_po).first()
    prior = GoodsReceipt.objects.filter(po=po, receipt_no=file_receipt).first() if po else None
    if prior is not None:
        saved = sorted((_stored_grn_line(line) for line in prior.lines.all()), key=lambda item: item["line_no"])
        observed = sorted(({name: row[name] for name in GRN_LINE_FIELDS} for row in parsed),
                          key=lambda item: item["line_no"])
        if prior.received_on != header["received_on"] or saved != observed:
            raise ImportRefused(f"Previously imported goods receipt {file_po}/{file_receipt} has changed; goods "
                                "receipts are append-only")
        if commit:
            _match(prior, result)
        return result

    po = _receivable_po(settings.dataset_kind, file_po, "goods receipt")
    _refuse_in_transit(po)
    if header["received_on"] < po.po_date:
        raise ImportRefused(f"{label} received_on {header['received_on']} is before PO {po.po_number} po_date "
                            f"{po.po_date}")
    lines = _po_lines(po)
    for row in parsed:
        po_line = lines.get(row["line_no"])
        context = f"{label} line {row['line_no']}"
        if po_line is None:
            raise ImportRefused(f"PO {po.po_number} has no line {row['line_no']}")
        if row["sku"] != po_line.product_id:
            raise ImportRefused(f"{context} sku {row['sku']} disagrees with PO {po.po_number} line "
                                f"{row['line_no']} sku {po_line.product_id}")
        existing = GoodsReceiptLine.objects.filter(po_line=po_line).select_related("receipt").first()
        if existing is not None:
            raise ImportRefused(f"PO {po.po_number} line {row['line_no']} already has receipt "
                                f"{existing.receipt.receipt_no}; multi-delivery lines arrive in G-2b")
        ordered = po_line.qty_pieces
        if row["accepted"] < ordered and not row["short_close"]:
            raise ImportRefused(f"{context} accepts {row['accepted']} of {ordered} ordered pieces; a short "
                                "delivery closes the line: short_close=yes with a short_close_reason "
                                "(multi-delivery lines arrive in G-2b)")
        if row["short_close"] and row["accepted"] >= ordered:
            raise ImportRefused(f"{context} short_close=yes but the line is not short ({row['accepted']} of "
                                f"{ordered} ordered pieces)")
    result.would_write_rows = 1 + len(parsed)
    if not commit:
        return result
    receipt = GoodsReceipt.objects.create(po=po, receipt_no=file_receipt, received_on=header["received_on"],
                                          source_filename=path.name, dataset_kind=settings.dataset_kind)
    for row in parsed:
        GoodsReceiptLine.objects.create(
            receipt=receipt, po_line=lines[row["line_no"]], line_no=row["line_no"], product_id=row["sku"],
            qty_pieces_good=row["qty_pieces_good"], qty_pieces_damaged=row["qty_pieces_damaged"],
            damaged_credited=row["damaged_credited"], short_close=row["short_close"],
            short_close_reason=row["short_close_reason"], evidence_ref=row["evidence_ref"],
            source_filename=path.name, dataset_kind=settings.dataset_kind)
    result.inserted_rows += 1 + len(parsed)
    _match(receipt, result)
    return result


# ---------------------------------------------------------------------------------------------
# Supplier invoice


def _inv_row(row: dict, columns) -> dict:
    refuse_pii(row, columns)
    invoice_no = _required(row, "invoice_no")
    if not DOC_NUMBER_PATTERN.fullmatch(invoice_no):
        raise ImportRefused(f"invoice_no must match ^{DOC_NUMBER}$: {invoice_no}")
    label = f"INV {invoice_no}"
    gui_no = row["gui_no"].strip()
    if gui_no and not GUI_PATTERN.fullmatch(gui_no):
        raise ImportRefused(f"{label} gui_no must be blank or two letters and eight digits")
    receipt_no = _required(row, "receipt_no")
    if not DOC_NUMBER_PATTERN.fullmatch(receipt_no):
        raise ImportRefused(f"receipt_no must match ^{DOC_NUMBER}$: {receipt_no}")
    line_no = _line_no(row["line_no"], label)
    context = f"{label} line {line_no}"
    qty = _pieces(row["qty_pieces_invoiced"], "qty_pieces_invoiced", context, positive=True)
    unit_price = _money(_required(row, "unit_price_twd"), "unit_price_twd")
    setup = _money(_required(row, "setup_charge_twd"), "setup_charge_twd")
    amount = _money(_required(row, "line_amount_twd"), "line_amount_twd")
    expected = qty * unit_price + setup
    if amount != expected:
        raise ImportRefused(f"{context} line_amount_twd {amount} disagrees with qty_pieces_invoiced x "
                            f"unit_price_twd + setup_charge_twd = {expected}")
    return {"invoice_no": invoice_no, "gui_no": gui_no,
            "invoice_date": _date(_required(row, "invoice_date"), "invoice_date"),
            "po_number": _required(row, "po_number"), "receipt_no": receipt_no, "line_no": line_no,
            "sku": _required(row, "sku"), "qty_pieces_invoiced": qty, "unit_price_twd": unit_price,
            "setup_charge_twd": setup, "line_amount_twd": amount,
            "freight_twd": _money(_required(row, "freight_twd"), "freight_twd"),
            "tax_twd": _money(_required(row, "tax_twd"), "tax_twd"),
            "tax_creditable_twd": _money(_required(row, "tax_creditable_twd"), "tax_creditable_twd"),
            "invoice_total_twd": _money(_required(row, "invoice_total_twd"), "invoice_total_twd"),
            "deposit_applied_twd": _money(_required(row, "deposit_applied_twd"), "deposit_applied_twd"),
            "evidence_ref": _required(row, "evidence_ref")}


INV_LINE_FIELDS = ("line_no", "sku", "qty_pieces_invoiced", "unit_price_twd", "setup_charge_twd",
                   "line_amount_twd")
INV_STORED_HEADER = ("gui_no", "invoice_date", "receipt_no", "freight_twd", "tax_twd", "tax_creditable_twd",
                     "invoice_total_twd", "deposit_applied_twd", "evidence_ref")


@transaction.atomic
def import_invoice(path, *, commit: bool = False) -> ReceivingResult:
    path = Path(path)
    settings = DatasetSettings.objects.select_for_update().get(pk=1)
    source = manifest("inv")
    _refuse_carrier_columns(path)
    source_rows = prepare_source(path, settings.dataset_kind, source, commit=commit)
    if not source_rows:
        raise ImportRefused(f"invoice file {path.name} has no lines")
    parsed = [_inv_row(row, source.header) for row in source_rows]
    file_number = path.name.removeprefix("SAMPLE_").removeprefix("inv_").removesuffix(".csv")
    for row in parsed:
        if row["invoice_no"] != file_number:
            raise ImportRefused(f"invoice_no {row['invoice_no']} does not match filename invoice number "
                                f"{file_number}")
    label = f"INV {file_number}"
    header = _agree(parsed, INV_HEADER_FIELDS, label)
    _no_repeats(parsed, label)
    result = ReceivingResult(parsed_rows=len(parsed))

    prior = SupplierInvoice.objects.filter(dataset_kind=settings.dataset_kind, invoice_no=file_number).first()
    if prior is not None:
        saved_lines = sorted(({name: (line.product_id if name == "sku" else getattr(line, name))
                               for name in INV_LINE_FIELDS} for line in prior.lines.all()),
                             key=lambda item: item["line_no"])
        observed = sorted(({name: row[name] for name in INV_LINE_FIELDS} for row in parsed),
                          key=lambda item: item["line_no"])
        if (prior.po.po_number != header["po_number"] or saved_lines != observed or
                any(getattr(prior, name) != header[name] for name in INV_STORED_HEADER)):
            raise ImportRefused(f"Previously imported supplier invoice {file_number} has changed; supplier "
                                "invoices are append-only")
        receipt = GoodsReceipt.objects.filter(po=prior.po, receipt_no=prior.receipt_no).first()
        if commit and receipt is not None:
            _match(receipt, result)
        return result

    tax, creditable = header["tax_twd"], header["tax_creditable_twd"]
    if creditable > tax:
        raise ImportRefused(f"{label} tax_creditable_twd {creditable} exceeds tax_twd {tax}")
    if creditable and not header["gui_no"]:
        raise ImportRefused(f"{label} tax_creditable_twd > 0 requires a gui_no; a blank gui_no means the tax is "
                            "not creditable (catalogue G.1)")
    if creditable and settings.business_tax_regime == "unregistered":
        raise ImportRefused(f"{label} tax_creditable_twd > 0 requires business_tax_regime assessed or general; "
                            "this dataset is unregistered (catalogue G.5.6)")
    lines_total = sum((row["line_amount_twd"] for row in parsed), Decimal(0))
    expected_total = lines_total + header["freight_twd"] + tax
    if header["invoice_total_twd"] != expected_total:
        raise ImportRefused(f"{label} invoice_total_twd {header['invoice_total_twd']} disagrees with "
                            f"sum(line_amount_twd) + freight_twd + tax_twd = {expected_total}")

    po = _receivable_po(settings.dataset_kind, header["po_number"], "supplier invoice")
    lines = _po_lines(po)
    for row in parsed:
        po_line = lines.get(row["line_no"])
        context = f"{label} line {row['line_no']}"
        if po_line is None:
            raise ImportRefused(f"PO {po.po_number} has no line {row['line_no']}")
        # I-6: the PO is frozen after sent; a variance is refused by name, never absorbed.
        if row["sku"] != po_line.product_id:
            raise ImportRefused(f"{context} sku {row['sku']} disagrees with PO {po.po_number} line "
                                f"{row['line_no']} sku {po_line.product_id}")
        for name in ("unit_price_twd", "setup_charge_twd"):
            if row[name] != getattr(po_line, name):
                raise ImportRefused(f"{context} {name} {row[name]} disagrees with PO {po.po_number} line "
                                    f"{row['line_no']} {name} {getattr(po_line, name)}; a price variance is "
                                    "refused, not absorbed (the PO is frozen once sent)")
        billed = SupplierInvoiceLine.objects.filter(po_line=po_line).select_related("invoice").first()
        if billed is not None:
            raise ImportRefused(f"PO {po.po_number} line {row['line_no']} is already invoiced by "
                                f"{billed.invoice.invoice_no}; multi-delivery lines arrive in G-2b")
    other = SupplierInvoice.objects.filter(po=po, receipt_no=header["receipt_no"]).first()
    if other is not None:
        raise ImportRefused(f"receipt {header['receipt_no']} on PO {po.po_number} is already invoiced by "
                            f"{other.invoice_no}")
    result.would_write_rows = 1 + len(parsed)
    if not commit:
        return result
    invoice = SupplierInvoice.objects.create(
        invoice_no=file_number, po=po, **{name: header[name] for name in INV_STORED_HEADER},
        source_filename=path.name, dataset_kind=settings.dataset_kind)
    for row in parsed:
        SupplierInvoiceLine.objects.create(
            invoice=invoice, po_line=lines[row["line_no"]], line_no=row["line_no"], product_id=row["sku"],
            qty_pieces_invoiced=row["qty_pieces_invoiced"], unit_price_twd=row["unit_price_twd"],
            setup_charge_twd=row["setup_charge_twd"], line_amount_twd=row["line_amount_twd"],
            source_filename=path.name, dataset_kind=settings.dataset_kind)
    result.inserted_rows += 1 + len(parsed)
    receipt = GoodsReceipt.objects.filter(po=po, receipt_no=header["receipt_no"]).first()
    if receipt is not None:
        _match(receipt, result)
    return result


# ---------------------------------------------------------------------------------------------
# Three-way match


def event_key(receipt: GoodsReceipt) -> str:
    return f"po.received|{receipt.dataset_kind}|{receipt.po.po_number}|{receipt.receipt_no}"


def invoice_for(receipt: GoodsReceipt) -> SupplierInvoice | None:
    return SupplierInvoice.objects.filter(po=receipt.po, receipt_no=receipt.receipt_no).first()


@dataclass
class MatchOutcome:
    problems: list[str]
    values: list = field(default_factory=list)
    payload: dict | None = None


def evaluate_match(receipt: GoodsReceipt, invoice: SupplierInvoice) -> MatchOutcome:
    """Every reason the pair cannot post, or the valued payload when it can. Never writes."""
    po = receipt.po
    label = f"INV {invoice.invoice_no} against GRN {po.po_number}/{receipt.receipt_no}"
    problems = []
    if po.status not in RECEIVABLE:
        problems.append(f"PO {po.po_number} is {po.status}; po.received needs a sent or acknowledged PO")
    if in_transit_event_exists(po):
        problems.append(f"PO {po.po_number} has a po.in_transit event; a receipt after goods in transit "
                        "arrives in G-2b (catalogue G.5.5)")
    received = {line.line_no: line for line in receipt.lines.select_related("product")}
    billed = {line.line_no: line for line in invoice.lines.all()}
    if set(received) != set(billed):
        problems.append(f"{label}: invoice lines {sorted(billed)} do not match receipt lines {sorted(received)}")
    for line_no in sorted(set(received) & set(billed)):
        grn, inv = received[line_no], billed[line_no]
        uncredited = 0 if grn.damaged_credited else grn.qty_pieces_damaged
        if inv.qty_pieces_invoiced != grn.qty_pieces_good + uncredited:
            problems.append(f"{label} line {line_no}: invoiced {inv.qty_pieces_invoiced} pieces but received "
                            f"good {grn.qty_pieces_good} + damaged not credited {uncredited} = "
                            f"{grn.qty_pieces_good + uncredited}")
    if problems:
        return MatchOutcome(problems)
    try:
        values, payload = value_pair(receipt, invoice)
        plan(_candidate(receipt, payload))
    except (LandedCostError, PostingError) as exc:
        return MatchOutcome([f"{label}: {exc}"])
    return MatchOutcome([], values, payload)


def value_pair(receipt: GoodsReceipt, invoice: SupplierInvoice):
    """Landed values and the Addendum G payload for a receipt and its invoice (G.5.2-G.5.4)."""
    po = receipt.po
    received = {line.line_no: line for line in receipt.lines.select_related("product")}
    billed = {line.line_no: line for line in invoice.lines.all()}
    inputs = []
    for line_no, grn in sorted(received.items()):
        inv = billed[line_no]
        inputs.append(ReceiptLineInput(
            line_no=line_no, sku=grn.product_id,
            inventory_account="1233" if grn.product.product_type == "packaging" else "1231",
            qty_good=grn.qty_pieces_good,
            qty_damaged_uncredited=0 if grn.damaged_credited else grn.qty_pieces_damaged,
            line_amount=inv.line_amount_twd, setup=inv.setup_charge_twd))
    values = value_receipt(inputs, freight=invoice.freight_twd, tax=invoice.tax_twd,
                           tax_creditable=invoice.tax_creditable_twd)
    payload = receipt_payload(values, po_number=po.po_number, receipt_no=receipt.receipt_no,
                              invoice_no=invoice.invoice_no, gui_no=invoice.gui_no,
                              supplier_total=invoice.invoice_total_twd, tax=invoice.tax_twd,
                              tax_creditable=invoice.tax_creditable_twd)
    applied = deposit_application(receipt, invoice)
    payload["deposit_applied_twd"] = str(applied)
    payload["invoice_stated_deposit_twd"] = str(invoice.deposit_applied_twd)
    return values, payload


def deposit_application(receipt: GoodsReceipt, invoice: SupplierInvoice) -> Decimal:
    """Addendum H.2: deterministic value-pro-rata application, with an exact closing remainder."""
    from ops.payments import applied_for_po, payment_totals

    po = receipt.po
    deposits = payment_totals(po)["deposit"]
    if not deposits:
        return Decimal("0.0000")
    already = applied_for_po(po)
    po_value = sum((line.line_total_twd for line in po.lines.all()), Decimal(0))
    receipt_value = sum((line.line_amount_twd for line in invoice.lines.all()), Decimal(0))
    posted = set(LedgerEvent.objects.filter(event_type="po.received", dataset_kind=po.dataset_kind,
                                            payload__po_number=po.po_number,
                                            posted_entry_id__isnull=False)
                 .values_list("payload__receipt_no", flat=True))
    covered = set(GoodsReceiptLine.objects.filter(po_line__po=po,
                                                   receipt__receipt_no__in=posted | {receipt.receipt_no})
                  .values_list("po_line_id", flat=True))
    completes = not po.lines.exclude(pk__in=covered).exists()
    return pro_rata_deposit(deposits, receipt_value, po_value, already=already, completes=completes)


def pro_rata_deposit(deposits: Decimal, receipt_value: Decimal, po_value: Decimal, *,
                     already: Decimal = Decimal(0), completes: bool = False) -> Decimal:
    """Pure H.2 allocator used by receipt matching and the rounding/remainder regression tests."""
    remaining = max(Decimal(0), deposits - already)
    if completes:
        return remaining.quantize(FOUR_DP)
    share = (deposits * receipt_value / po_value).quantize(FOUR_DP, rounding=ROUND_HALF_UP)
    return min(share, remaining).quantize(FOUR_DP)


def _candidate(receipt: GoodsReceipt, payload: dict) -> LedgerEvent:
    return LedgerEvent(event_type="po.received", entity_table="ops.goodsreceipt", entity_id=receipt.pk,
                       occurred_at=_occurred(receipt.received_on), currency="TWD", payload=payload,
                       idempotency_key=event_key(receipt), source_filename=receipt.source_filename,
                       dataset_kind=receipt.dataset_kind)


def _match(receipt: GoodsReceipt, result: ReceivingResult) -> None:
    """Post one po.received for a matched (PO, receipt); list, never hold, anything else."""
    if LedgerEvent.objects.filter(idempotency_key=event_key(receipt)).exists():
        return
    invoice = invoice_for(receipt)
    if invoice is None:
        return  # received, not invoiced: listed by /reports/po-exceptions/
    outcome = evaluate_match(receipt, invoice)
    if outcome.problems:
        result.match_refusals.extend(outcome.problems)
        return
    candidate = _candidate(receipt, outcome.payload)
    result.inserted_events += emit_event(
        event_type="po.received", entity_table="ops.goodsreceipt", entity_id=receipt.pk,
        occurred_at=candidate.occurred_at, currency="TWD", payload=outcome.payload,
        idempotency_key=candidate.idempotency_key, source_filename=receipt.source_filename,
        dataset_kind=receipt.dataset_kind)
    post_event(LedgerEvent.objects.get(idempotency_key=candidate.idempotency_key))
    for value in outcome.values:
        # On-hand follows WAC: sellable good pieces only. Damage adds no quantity (R-3).
        if value.inventory_account != "1231" or not value.qty_good:
            continue
        InventoryMove.objects.create(
            product_id=value.sku, kind="received", qty_delta_pieces=value.qty_good,
            value_delta_twd=value.good_value, occurred_at=candidate.occurred_at,
            idempotency_key=f"received-move|{candidate.idempotency_key}|{value.line_no}",
            source_filename=receipt.source_filename, dataset_kind=receipt.dataset_kind)
        result.inserted_rows += 1
    result.inserted_rows += _close_po_if_received(receipt)


def _close_po_if_received(receipt: GoodsReceipt) -> int:
    po = PurchaseOrder.objects.select_for_update().get(pk=receipt.po_id)
    posted = set(LedgerEvent.objects.filter(event_type="po.received", dataset_kind=po.dataset_kind,
                                            payload__po_number=po.po_number,
                                            posted_entry_id__isnull=False)
                 .values_list("payload__receipt_no", flat=True))
    lines = list(po.lines.all())
    receipt_lines = {line.po_line_id: line for line in GoodsReceiptLine.objects.filter(
        po_line__po=po).select_related("receipt")}
    if any(line.pk not in receipt_lines or receipt_lines[line.pk].receipt.receipt_no not in posted
           for line in lines):
        return 0
    status = "short_closed" if any(line.short_close for line in receipt_lines.values()) else "received"
    # History first: the database trigger refuses a status with no history row.
    PurchaseOrderStatus.objects.create(po_number=po.po_number, status=status, effective_on=receipt.received_on,
                                       source_filename=receipt.source_filename, dataset_kind=po.dataset_kind)
    po.status = status
    po.save()
    return 2
