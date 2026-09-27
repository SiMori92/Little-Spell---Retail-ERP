"""Compliance gates shared by later purchasing slices."""

from ops.models import NOT_APPLICABLE, Product

COMPLIANCE_PREFIX = "compliance/suppliers/"


def _is_packaging(product) -> bool:
    # The DB CHECK makes NOT_APPLICABLE mean packaging and nothing else. Testing it
    # first keeps product_type unread for every sellable SKU, so this guard still
    # runs against the pre-G-1 historical schemas the G-0.1 test migrates through.
    return product.ingredient_ref == NOT_APPLICABLE and product.product_type == "packaging"


class PoBlocked(ValueError):
    """One or more requested products are not eligible for a purchase order."""


def assert_po_eligible(skus) -> None:
    requested = sorted(set(skus))
    # This guard is exercised against historical migration states. Select only
    # the stable compliance columns it actually uses; unit fields are irrelevant
    # to PO eligibility and may not exist yet during a forward-migration test.
    products = Product.objects.select_related("supplier").only(
        "sku", "ingredient_ref", "supplier_id", "supplier__declaration_ref"
    ).in_bulk(requested)
    blocked = []
    for sku in requested:
        product = products.get(sku)
        if product is not None and _is_packaging(product):
            # G-1 I-5: packaging needs only a product and a supplier; no ink declaration.
            if product.supplier_id is None:
                blocked.append(sku)
            continue
        ingredient_ok = (product is not None and
                         product.ingredient_ref.startswith(COMPLIANCE_PREFIX) and
                         len(product.ingredient_ref) > len(COMPLIANCE_PREFIX))
        supplier_ok = (product is not None and product.supplier_id is not None and
                       product.supplier.declaration_ref.startswith(COMPLIANCE_PREFIX) and
                       len(product.supplier.declaration_ref) > len(COMPLIANCE_PREFIX))
        if not ingredient_ok or not supplier_ok:
            blocked.append(sku)
    if blocked:
        raise PoBlocked(f"PO blocked for SKU(s): {', '.join(blocked)}")
