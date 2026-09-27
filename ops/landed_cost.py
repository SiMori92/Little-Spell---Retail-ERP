"""Landed cost of one matched receipt: catalogue Addendum G.3 as amended by G.5.

Exact decimal, 4 dp, half-up. Every share is computed by value; the remainder of each
allocation goes to the HIGHEST PO line number on the receipt (G.5.4) and the sum is
asserted. Posted amounts are line values, never qty x rounded per-piece (G.5.3).
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

Q = Decimal("0.0001")


def q(value) -> Decimal:
    return Decimal(value).quantize(Q, rounding=ROUND_HALF_UP)


class LandedCostError(ValueError):
    pass


@dataclass(frozen=True)
class ReceiptLineInput:
    line_no: int
    sku: str
    inventory_account: str  # 1231 sellable, 1233 packaging
    qty_good: int
    qty_damaged_uncredited: int
    line_amount: Decimal  # invoiced pieces x unit price + setup (R-1.1)
    setup: Decimal
    stated_tax: Decimal | None = None  # per-line tax stated on the invoice, if any


@dataclass(frozen=True)
class ReceiptLineValue:
    line_no: int
    sku: str
    inventory_account: str
    qty_good: int
    qty_damaged: int
    line_amount: Decimal
    setup: Decimal
    freight_share: Decimal
    tax_share: Decimal
    landed: Decimal
    damaged_value: Decimal
    good_value: Decimal

    @property
    def pieces(self) -> int:
        return self.qty_good + self.qty_damaged

    @property
    def per_piece(self) -> Decimal:
        """Derived for display only; never multiplied back (R-1.6)."""
        return q(self.landed / self.pieces)


def allocate(total: Decimal, weights: dict[int, Decimal]) -> dict[int, Decimal]:
    """Split `total` over line numbers by weight; the remainder goes to the highest line number."""
    total = q(total)
    if not weights:
        raise LandedCostError("nothing to allocate over")
    basis = sum(weights.values(), Decimal(0))
    if basis <= 0:
        if total:
            raise LandedCostError("a charge cannot be allocated over lines of zero value")
        return {line: Decimal(0).quantize(Q) for line in weights}
    last = max(weights)
    shares = {line: q(total * weight / basis) for line, weight in weights.items() if line != last}
    shares[last] = total - sum(shares.values(), Decimal(0))
    if sum(shares.values(), Decimal(0)) != total:
        raise LandedCostError("allocation does not sum to its total")
    return shares


def value_receipt(lines: list[ReceiptLineInput], *, freight: Decimal, tax: Decimal,
                  tax_creditable: Decimal) -> list[ReceiptLineValue]:
    """G.5.2: supplier-billed freight and non-creditable tax, each by line value.

    Where every line states its own tax, the stated tax wins: the non-creditable
    share then follows the stated tax, not the line value (contract §5.4 v1.2).
    """
    if not lines:
        raise LandedCostError("a receipt needs at least one line")
    if len({line.line_no for line in lines}) != len(lines):
        raise LandedCostError("line numbers repeat")
    tax, tax_creditable, freight = q(tax), q(tax_creditable), q(freight)
    if not Decimal(0) <= tax_creditable <= tax:
        raise LandedCostError("tax_creditable_twd must be between 0 and tax_twd")
    for line in lines:
        if line.qty_good < 0 or line.qty_damaged_uncredited < 0 or line.qty_good + line.qty_damaged_uncredited <= 0:
            raise LandedCostError(f"line {line.line_no} receives no pieces")
    by_value = {line.line_no: q(line.line_amount) for line in lines}
    freight_shares = allocate(freight, by_value)
    stated = [line.stated_tax for line in lines]
    if all(value is not None for value in stated):
        if q(sum(stated, Decimal(0))) != tax:
            raise LandedCostError("stated per-line tax does not sum to tax_twd")
        tax_weights = {line.line_no: q(line.stated_tax) for line in lines}
    elif any(value is not None for value in stated):
        raise LandedCostError("per-line tax is stated on some lines but not all")
    else:
        tax_weights = by_value
    tax_shares = allocate(tax - tax_creditable, tax_weights)
    result = []
    for line in sorted(lines, key=lambda item: item.line_no):
        landed = q(line.line_amount) + freight_shares[line.line_no] + tax_shares[line.line_no]
        received = line.qty_good + line.qty_damaged_uncredited
        damaged = q(landed * line.qty_damaged_uncredited / received)  # G.5.3
        result.append(ReceiptLineValue(
            line_no=line.line_no, sku=line.sku, inventory_account=line.inventory_account,
            qty_good=line.qty_good, qty_damaged=line.qty_damaged_uncredited,
            line_amount=q(line.line_amount), setup=q(line.setup),
            freight_share=freight_shares[line.line_no], tax_share=tax_shares[line.line_no],
            landed=landed, damaged_value=damaged, good_value=landed - damaged,
        ))
    return result


def receipt_payload(values: list[ReceiptLineValue], *, po_number: str, receipt_no: str, invoice_no: str,
                    gui_no: str, supplier_total: Decimal, tax: Decimal, tax_creditable: Decimal) -> dict:
    """The Addendum G.1 payload, with the G.5.1 identity asserted before anything is emitted."""
    receipts = [{"sku": value.sku, "qty_pieces": str(value.qty_good), "landed_cost_twd": str(value.good_value),
                 "inventory_account": value.inventory_account}
                for value in values if value.qty_good]
    damaged = [{"sku": value.sku, "qty_pieces": str(value.qty_damaged), "landed_cost_twd": str(value.damaged_value)}
               for value in values if value.qty_damaged]
    product = sum((value.good_value for value in values if value.qty_good and value.inventory_account == "1231"),
                  Decimal(0))
    packaging = sum((value.good_value for value in values if value.qty_good and value.inventory_account == "1233"),
                    Decimal(0))
    components = {"product": q(product), "packaging": q(packaging), "supplier": q(supplier_total),
                  "freight": q(0), "duty": q(0), "in_transit": q(0)}
    payload = {
        "po_number": po_number, "receipt_no": receipt_no, "invoice_no": invoice_no, "gui_no": gui_no,
        "sku_receipts": receipts, "damaged_on_arrival": damaged,
        "tax_twd": str(q(tax)), "tax_creditable_twd": str(q(tax_creditable)),
        "landed_components_twd": {key: str(value) for key, value in components.items()},
    }
    assert_identity(payload)
    return payload


def assert_identity(payload: dict) -> None:
    """G.5.1: product + packaging + sum(damaged) + tax_creditable = supplier + freight + duty + in_transit."""
    c = {key: q(value) for key, value in payload["landed_components_twd"].items()}
    damaged = sum((q(row["landed_cost_twd"]) for row in payload.get("damaged_on_arrival", [])), Decimal(0))
    left = c["product"] + c["packaging"] + damaged + q(payload["tax_creditable_twd"])
    right = c["supplier"] + c["freight"] + c["duty"] + c["in_transit"]
    if left != right:
        raise LandedCostError(
            f"po.received identity fails: product + packaging + damaged + tax_creditable = {left} but "
            f"supplier + freight + duty + in_transit = {right} (catalogue G.5.1; no plug, no rounding account)"
        )
