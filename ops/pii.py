"""Shared PII refusal for file-backed operational intakes."""

import re

from ops.intake import ImportRefused

EMAIL = re.compile(r"\S+@\S+\.\S+")
HANDLE = re.compile(r"(^|\s)@\w")


def refuse_pii(row: dict, columns) -> None:
    """Refuse the row without echoing the sensitive value."""
    for column in columns:
        value = str(row.get(column, ""))
        if EMAIL.search(value) or HANDLE.search(value):
            raise ImportRefused(f"PII detected in {column}")
