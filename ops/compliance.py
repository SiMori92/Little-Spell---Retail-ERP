"""Compliance gates shared by later purchasing slices."""

from ops.models import Product

COMPLIANCE_PREFIX = "compliance/suppliers/"


class PoBlocked(ValueError):
    """One or more requested products are not eligible for a purchase order."""


def assert_po_eligible(skus) -> None:
    requested = sorted(set(skus))
    products = Product.objects.select_related("supplier").in_bulk(requested)
    blocked = []
    for sku in requested:
        product = products.get(sku)
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
