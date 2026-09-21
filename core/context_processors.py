"""Seed quarantine — DATA_REVIEW addendum §A1.3.

Every rendered page gets `dataset_is_sample` and `dataset_banner_text`. The base
templates render the banner from them. A number without that banner is a number
someone will act on.

If the settings row cannot be read for any reason, this FAILS SAFE: it reports
SAMPLE. Showing the banner wrongly costs nothing; hiding it wrongly is the whole
risk this control exists to remove.
"""

from django.db import DatabaseError

from core.models import DatasetKind, DatasetSettings

BANNER_TEXT = "SAMPLE DATA — NOT ACTUALS"


def dataset_banner(request):
    try:
        kind = DatasetSettings.load().dataset_kind
    except DatabaseError:
        kind = DatasetKind.SAMPLE
    is_sample = kind == DatasetKind.SAMPLE
    return {
        "dataset_kind": kind,
        "dataset_is_sample": is_sample,
        "dataset_banner_text": BANNER_TEXT if is_sample else "",
    }
