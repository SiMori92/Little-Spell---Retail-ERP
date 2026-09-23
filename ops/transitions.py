"""Explicit exception transitions for sources absent from the sample exports."""

from django.db import transaction

from ops.etsy_import import ImportRefused, emit_event
from ops.models import EtsyStatementRow, Order, Shipment


@transaction.atomic
def record_order_exception(*, order: Order, event_type: str, evidence_ref: str,
                           occurred_at, amount_minor: int, was_paid: bool | None = None) -> bool:
    """Record a synthetic/externally evidenced cancellation or refund; emit only."""
    if event_type not in {"order.cancelled", "order.refunded"}:
        raise ImportRefused(f"Unsupported order exception transition: {event_type}")
    if not evidence_ref or amount_minor < 0:
        raise ImportRefused(f"{event_type} needs evidence and a nonnegative amount")
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if event_type == "order.cancelled":
        if locked.status != "placed" or was_paid is None:
            raise ImportRefused("Cancellation needs placed status and explicit was_paid evidence")
        locked.status = "cancelled"
        payload = {"evidence_ref": evidence_ref, "was_paid": was_paid}
    else:
        if (locked.status != "shipped" or amount_minor > locked.gross_minor or
                not Shipment.objects.filter(order=locked, status="dispatched", ship_date__isnull=False).exists()):
            raise ImportRefused("Refund needs dispatched shipment and amount within original gross")
        locked.status = "refunded"
        payload = {"evidence_ref": evidence_ref, "original_order_id": locked.channel_order_id}
    created = emit_event(
        event_type=event_type, entity_table="ops.order", entity_id=locked.pk,
        occurred_at=occurred_at, amount_minor=amount_minor, currency=locked.currency,
        payload=payload, idempotency_key=f"{event_type}|{locked.channel_id}|{locked.channel_order_id}|{evidence_ref}",
        source_filename=locked.source_filename, dataset_kind=locked.dataset_kind,
    )
    locked.save(update_fields=["status"])
    return created


@transaction.atomic
def record_settlement_reversal(*, original_deposit: EtsyStatementRow, evidence_ref: str,
                               occurred_at, amount_minor: int) -> bool:
    """A positive payout reversal needs explicit external evidence before emission."""
    if original_deposit.row_type != "Deposit" or original_deposit.net_minor >= 0:
        raise ImportRefused("Reversal must identify an original negative Deposit")
    if not evidence_ref or amount_minor <= 0:
        raise ImportRefused("Settlement reversal needs evidence and positive amount")
    return emit_event(
        event_type="settlement.reversed", entity_table="ops.etsystatementrow",
        entity_id=original_deposit.pk, occurred_at=occurred_at,
        amount_minor=amount_minor, currency=original_deposit.currency,
        payload={"evidence_ref": evidence_ref, "original_deposit_row_key": original_deposit.row_key},
        idempotency_key=f"settlement.reversed|{original_deposit.row_key}|{evidence_ref}",
        source_filename=original_deposit.source_filename,
        dataset_kind=original_deposit.dataset_kind,
    )
