"""Slice G-3 supplier-payment intake and deterministic payable/deposit balances."""

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from django.db import transaction

from acct.posting import PostingError, plan, post_event
from core.models import DatasetSettings
from ops.etsy_import import emit_event
from ops.file_intake import IntakeResult, _date, _money, _occurred, _required, load_schema, register_manifest
from ops.intake import ImportRefused, IntakeManifest, prepare_source
from ops.models import (GoodsReceipt, LedgerEvent, PAYMENT_KINDS, PurchaseOrder, PurchaseOrderStatus,
                        SupplierInvoice, SupplierPayment)
from ops.pii import refuse_pii

PAYMENT_REF = r"[A-Z0-9][A-Z0-9-]{0,31}"
PAYMENT_REF_PATTERN = re.compile(rf"{PAYMENT_REF}\Z")
PAY_HEADER = ("payment_ref", "paid_on", "supplier_ref", "po_number", "invoice_no", "payment_kind",
              "amount_twd", "bank_account", "bank_ref", "evidence_ref")
Q = Decimal("0.0001")


def _payment_manifest() -> IntakeManifest:
    fixture = load_schema("pay")
    if fixture["source"] != "authored":
        raise ImportRefused("pay schema fixture must have source authored")
    return IntakeManifest(
        kind="pay", header=tuple(fixture["header"]), optional_columns=(), verified=fixture["verified"],
        actual_filename=re.compile(rf"pay_{PAYMENT_REF}\.csv\Z"),
        sample_filename=re.compile(rf"SAMPLE_pay_{PAYMENT_REF}\.csv\Z"),
        target_models=("SupplierPayment",), events=("po.paid",),
        natural_key="dataset + payment_ref", version=1,
    )


register_manifest("pay", _payment_manifest)


def payment_totals(po: PurchaseOrder) -> dict[str, Decimal]:
    totals = {kind: Decimal(0) for kind in PAYMENT_KINDS}
    for payment in po.payments.all():
        totals[payment.payment_kind] += payment.amount_twd
    return totals


def applied_for_po(po: PurchaseOrder) -> Decimal:
    total = Decimal(0)
    events = LedgerEvent.objects.filter(event_type="po.received", dataset_kind=po.dataset_kind,
                                        payload__po_number=po.po_number,
                                        posted_entry_id__isnull=False, posting_error__isnull=True)
    for event in events:
        total += Decimal(str(event.payload.get("deposit_applied_twd", "0")))
    return total


def deposit_open(po: PurchaseOrder) -> Decimal:
    totals = payment_totals(po)
    return (totals["deposit"] - totals["deposit_refund"] - totals["deposit_forfeit"] -
            applied_for_po(po)).quantize(Q)


def computed_deposit_for_invoice(invoice: SupplierInvoice) -> Decimal:
    event = LedgerEvent.objects.filter(event_type="po.received", dataset_kind=invoice.dataset_kind,
                                       payload__invoice_no=invoice.invoice_no,
                                       posted_entry_id__isnull=False,
                                       posting_error__isnull=True).first()
    return Decimal(str(event.payload.get("deposit_applied_twd", "0"))).quantize(Q) if event else Decimal(0)


def balance_paid(invoice: SupplierInvoice) -> Decimal:
    return sum((payment.amount_twd for payment in invoice.payments.filter(payment_kind="balance")),
               Decimal(0)).quantize(Q)


def invoice_open(invoice: SupplierInvoice) -> Decimal:
    return (invoice.invoice_total_twd - computed_deposit_for_invoice(invoice) -
            balance_paid(invoice)).quantize(Q)


def close_po_if_settled(po: PurchaseOrder, paid_on, source_filename: str) -> int:
    po.refresh_from_db()
    if po.status not in {"received", "short_closed"} or deposit_open(po) != 0:
        return 0
    invoices = list(po.invoices.all())
    if not invoices or any(invoice_open(invoice) != 0 for invoice in invoices):
        return 0
    PurchaseOrderStatus.objects.create(po_number=po.po_number, status="closed", effective_on=paid_on,
                                       source_filename=source_filename, dataset_kind=po.dataset_kind)
    po.status = "closed"
    po.source_filename = source_filename
    po.save()
    return 2


def _parse(row: dict, columns) -> dict:
    refuse_pii(row, columns)
    payment_ref = _required(row, "payment_ref")
    if not PAYMENT_REF_PATTERN.fullmatch(payment_ref):
        raise ImportRefused(f"payment_ref must match ^{PAYMENT_REF}$: {payment_ref}")
    kind = row["payment_kind"].strip()
    if not kind:
        raise ImportRefused("payment_kind is required; it never defaults (catalogue H.1)")
    if kind not in PAYMENT_KINDS:
        raise ImportRefused(f"unknown payment_kind {kind}; expected deposit, balance, deposit_refund or "
                            "deposit_forfeit (catalogue H.1)")
    amount = _money(_required(row, "amount_twd"), "amount_twd")
    if amount <= 0:
        raise ImportRefused("amount_twd must be positive")
    bank_account = _required(row, "bank_account")
    if bank_account != "1121":
        raise ImportRefused(f"bank_account {bank_account} is refused; supplier payments are TWD through 1121 "
                            "only (R-2.6, IFRIC 22)")
    invoice_no = row["invoice_no"].strip()
    bank_ref = row["bank_ref"].strip()
    evidence_ref = _required(row, "evidence_ref")
    if kind == "balance" and not invoice_no:
        raise ImportRefused("balance payment requires invoice_no")
    if kind != "balance" and invoice_no:
        raise ImportRefused(f"{kind} payment requires invoice_no to be blank")
    if kind == "deposit_forfeit" and bank_ref:
        raise ImportRefused("deposit_forfeit has no bank_ref")
    if kind != "deposit_forfeit" and not bank_ref:
        raise ImportRefused(f"{kind} payment requires bank_ref")
    return {"payment_ref": payment_ref, "paid_on": _date(_required(row, "paid_on"), "paid_on"),
            "supplier_ref": _required(row, "supplier_ref"), "po_number": _required(row, "po_number"),
            "invoice_no": invoice_no, "payment_kind": kind, "amount_twd": amount,
            "bank_account": bank_account, "bank_ref": bank_ref, "evidence_ref": evidence_ref}


def _stored(payment: SupplierPayment) -> dict:
    return {"payment_ref": payment.payment_ref, "paid_on": payment.paid_on,
            "supplier_ref": payment.supplier.supplier_ref, "po_number": payment.po.po_number,
            "invoice_no": payment.invoice.invoice_no if payment.invoice_id else "",
            "payment_kind": payment.payment_kind, "amount_twd": payment.amount_twd,
            "bank_account": payment.bank_account, "bank_ref": payment.bank_ref,
            "evidence_ref": payment.evidence_ref}


def _payload(row: dict) -> dict:
    return {key: (str(value) if isinstance(value, Decimal) else value)
            for key, value in row.items() if key not in {"paid_on", "supplier_ref"}}


@transaction.atomic
def import_supplier_payment(path, *, commit: bool = False) -> IntakeResult:
    path = Path(path)
    settings = DatasetSettings.objects.select_for_update().get(pk=1)
    source = _payment_manifest()
    rows = prepare_source(path, settings.dataset_kind, source, commit=commit)
    if len(rows) != 1:
        raise ImportRefused(f"payment file {path.name} must contain exactly one row")
    row = _parse(rows[0], source.header)
    file_ref = path.name.removeprefix("SAMPLE_").removeprefix("pay_").removesuffix(".csv")
    if row["payment_ref"] != file_ref:
        raise ImportRefused(f"payment_ref {row['payment_ref']} does not match filename payment reference "
                            f"{file_ref}")
    result = IntakeResult(parsed_rows=1)
    prior = SupplierPayment.objects.filter(dataset_kind=settings.dataset_kind,
                                           payment_ref=row["payment_ref"]).select_related(
                                               "supplier", "po", "invoice").first()
    if prior:
        if _stored(prior) != row:
            raise ImportRefused(f"Previously imported supplier payment {row['payment_ref']} has changed; "
                                "supplier payments are append-only")
        return result
    po = PurchaseOrder.objects.select_for_update().filter(dataset_kind=settings.dataset_kind,
                                                          po_number=row["po_number"]).select_related(
                                                              "supplier").first()
    if po is None:
        raise ImportRefused(f"unknown PO: {row['po_number']}")
    if po.supplier.supplier_ref != row["supplier_ref"]:
        raise ImportRefused(f"payment supplier_ref {row['supplier_ref']} disagrees with PO {po.po_number} "
                            f"supplier {po.supplier.supplier_ref}")
    if po.currency != "TWD":
        raise ImportRefused(f"PO {po.po_number} currency {po.currency} is refused; supplier payments are TWD "
                            "through 1121 only (R-2.6, IFRIC 22)")
    invoice = None
    if row["payment_kind"] == "deposit":
        if po.status not in {"sent", "acknowledged"}:
            raise ImportRefused(f"deposit requires PO {po.po_number} at sent or acknowledged; it is {po.status}")
        if GoodsReceipt.objects.filter(po=po).exists():
            raise ImportRefused(f"deposit on PO {po.po_number} is refused after a receipt exists (catalogue H.3.1)")
        po_value = sum((line.line_total_twd for line in po.lines.all()), Decimal(0))
        if payment_totals(po)["deposit"] + row["amount_twd"] > po_value:
            raise ImportRefused(f"deposit would make cumulative deposits on PO {po.po_number} exceed PO value "
                                f"excluding tax {po_value}")
    elif row["payment_kind"] == "balance":
        invoice = SupplierInvoice.objects.filter(dataset_kind=settings.dataset_kind,
                                                 invoice_no=row["invoice_no"], po=po).first()
        if invoice is None:
            raise ImportRefused(f"balance payment requires posted supplier invoice {row['invoice_no']} on "
                                f"PO {po.po_number}")
        posted = LedgerEvent.objects.filter(event_type="po.received", dataset_kind=settings.dataset_kind,
                                            payload__invoice_no=invoice.invoice_no,
                                            posted_entry_id__isnull=False,
                                            posting_error__isnull=True).exists()
        if not posted:
            raise ImportRefused(f"balance payment requires posted supplier invoice {invoice.invoice_no}")
        open_amount = invoice_open(invoice)
        if row["amount_twd"] > open_amount:
            raise ImportRefused(f"balance payment {row['amount_twd']} overpays invoice {invoice.invoice_no}; "
                                f"open amount is {open_amount}; 2171 must never go debit for a supplier")
    else:
        if po.status != "cancelled":
            raise ImportRefused(f"{row['payment_kind']} requires cancelled PO {po.po_number}; it is {po.status}")
        open_amount = deposit_open(po)
        if row["amount_twd"] > open_amount:
            raise ImportRefused(f"{row['payment_kind']} {row['amount_twd']} exceeds open 1266 balance "
                                f"{open_amount} on PO {po.po_number}")
    result.would_write_rows = 2
    if not commit:
        return result
    payment = SupplierPayment.objects.create(
        payment_ref=row["payment_ref"], paid_on=row["paid_on"], supplier=po.supplier, po=po,
        invoice=invoice, payment_kind=row["payment_kind"], amount_twd=row["amount_twd"],
        bank_account=row["bank_account"], bank_ref=row["bank_ref"], evidence_ref=row["evidence_ref"],
        source_filename=path.name, dataset_kind=settings.dataset_kind)
    payload = _payload(row)
    candidate = LedgerEvent(event_type="po.paid", entity_table="ops.supplierpayment", entity_id=payment.pk,
                            occurred_at=_occurred(row["paid_on"]), currency="TWD", payload=payload,
                            idempotency_key=f"po.paid|{settings.dataset_kind}|{row['payment_ref']}",
                            source_filename=path.name, dataset_kind=settings.dataset_kind)
    try:
        plan(candidate)
    except PostingError as exc:
        raise ImportRefused(f"supplier payment posting rule refused: {exc}") from exc
    result.inserted_events += emit_event(
        event_type=candidate.event_type, entity_table=candidate.entity_table, entity_id=candidate.entity_id,
        occurred_at=candidate.occurred_at, currency="TWD", payload=payload,
        idempotency_key=candidate.idempotency_key, source_filename=path.name,
        dataset_kind=settings.dataset_kind)
    post_event(LedgerEvent.objects.get(idempotency_key=candidate.idempotency_key))
    result.inserted_rows = 2 + close_po_if_settled(po, row["paid_on"], path.name)
    return result
