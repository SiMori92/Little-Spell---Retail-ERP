"""Compliance gates shared by later purchasing slices."""

from ops.models import Product


class PoBlocked(ValueError):
    """One or more requested products are not eligible for a purchase order."""


def assert_po_eligible(skus) -> None:
    requested = sorted(set(skus))
    products = Product.objects.select_related("supplier").in_bulk(requested)
    blocked = []
    for sku in requested:
        product = products.get(sku)
        if (product is None or product.ingredient_ref == "UNKNOWN" or
                product.supplier_id is None or not product.supplier.declaration_ref):
            blocked.append(sku)
    if blocked:
        raise PoBlocked(f"PO blocked for SKU(s): {', '.join(blocked)}")
