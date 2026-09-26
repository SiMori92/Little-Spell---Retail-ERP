"""Synthetic schedule checks. Failures assert IDs and counts, never customer rows."""

from datetime import datetime, timezone as dt_timezone

from django.test import TestCase

from acct.models import JournalLine, WacPosition
from acct.posting import PostingError, plan, post_event
from ops.models import LedgerEvent, Product


class OpeningScheduleTests(TestCase):
    def setUp(self):
        for sku in ("COUNT-A", "COUNT-Z"):
            Product.objects.create(sku=sku, name="Synthetic", uom="PK")
        self.payload = {
            "counted_at": "2025-03-27", "evidence_ref": "synthetic-photos",
            "lines": [
                {"sku": "COUNT-A", "qty_packs": "3", "agreed_unit_cost_twd": "12.5000",
                 "line_value_twd": "37.5000", "condition": "sellable"},
                {"sku": "COUNT-Z", "qty_packs": "0", "agreed_unit_cost_twd": "5.0000",
                 "line_value_twd": "0.0000", "condition": "damaged_unsellable"},
            ],
            "total_value_twd": "37.5000",
        }

    def event(self, key="opening-count|SAMPLE"):
        return LedgerEvent.objects.create(
            event_type="inventory.opening_counted", entity_table="ops.stockcount", entity_id=1,
            occurred_at=datetime(2025, 3, 27, 12, tzinfo=dt_timezone.utc), payload=self.payload,
            idempotency_key=key, source_filename="SAMPLE_count.csv", dataset_kind="SAMPLE",
        )

    def test_multi_sku_posts_one_entry_with_zero_pair_and_wac(self):
        event = self.event()
        entry_id = post_event(event)
        lines = list(JournalLine.objects.filter(entry_id=entry_id).order_by("id"))
        self.assertEqual(len(lines), 4)
        self.assertEqual([line.sku for line in lines], ["COUNT-A", None, "COUNT-Z", "COUNT-Z"])
        self.assertEqual([line.qty_delta_packs for line in lines], [3, None, 0, None])
        self.assertEqual([line.debit for line in lines], [37.5, 0, 0, 0])
        self.assertEqual(WacPosition.objects.get(pk="COUNT-Z").qty_packs, 0)

    def test_mismatched_schedule_total_is_refused(self):
        self.payload["total_value_twd"] = "38.0000"
        with self.assertRaisesRegex(PostingError, "total_value_twd disagrees"):
            plan(self.event())

    def test_second_opening_event_is_refused_for_dataset(self):
        self.event()
        with self.assertRaisesRegex(PostingError, "once per dataset"):
            plan(self.event("opening-count|SAMPLE|second"))
