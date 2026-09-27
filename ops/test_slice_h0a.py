"""Slice H-0a tests use opaque synthetic references and never print customer rows."""

import csv
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from acct.models import JournalLine
from core.models import DatasetSettings
from ops.file_intake import import_ig_deals, import_products, import_suppliers, load_schema
from ops.intake import ImportRefused
from ops.models import Channel, IgDeal, IgDealStatus, LedgerEvent, Order
from ops.reporting import ig_pipeline, repeat_rate

SAMPLES = Path(__file__).resolve().parents[1] / "docs" / "samples"
IG_SAMPLE = SAMPLES / "SAMPLE_ig_deals_2026-10.csv"


class InstagramDealTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        DatasetSettings.objects.get_or_create(pk=1, defaults={"dataset_kind": "SAMPLE"})
        import_suppliers(SAMPLES / "SAMPLE_suppliers_2026-09-27.csv", commit=True)
        import_products(SAMPLES / "SAMPLE_products_2026-09-27.csv", commit=True)

    def rows(self):
        with IG_SAMPLE.open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    def source(self, rows, filename="SAMPLE_ig_deals_2026-10.csv"):
        path = Path(self.temp.name) / filename
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=load_schema("ig_deals")["header"])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def one(self, status="quoted", **changes):
        row = {"deal_id": "IG-202610-101", "line_no": "1", "customer_ref": "C-0101",
               "status": status, "enquiry_at": "2026-10-01", "quoted_at": "2026-10-02",
               "quote_twd": "300.0000", "follow_up_on": "2026-10-10", "lost_reason": "",
               "sku": "", "qty_packs": "", "unit_price_twd": "",
               "shipping_charged_twd": "", "ship_country": "", "paid_at": "",
               "wallet_txn_id": "", "ship_date": "", "consent_marketing": "",
               "journey_sent": "none", "evidence_ref": "instagram/deals/evidence-one"}
        if status in {"paid", "shipped", "followed_up"}:
            row.update({"follow_up_on": "", "sku": "TS-FL-001-S", "qty_packs": "1",
                        "unit_price_twd": "300.0000", "shipping_charged_twd": "0.0000",
                        "ship_country": "TW", "paid_at": "2026-10-03", "wallet_txn_id": "88101"})
        if status in {"shipped", "followed_up"}:
            row["ship_date"] = "2026-10-04"
        if status == "enquiry":
            row.update({"quoted_at": "", "quote_twd": ""})
        if status == "lost":
            row.update({"follow_up_on": "", "lost_reason": "no_reply"})
        row.update(changes)
        return row

    def test_sample_reimport_is_idempotent_and_posts_nothing(self):
        accounting = (LedgerEvent.objects.count(), JournalLine.objects.count(), Order.objects.count())
        first = import_ig_deals(IG_SAMPLE, commit=True)
        counts = (IgDeal.objects.count(), IgDealStatus.objects.count())
        second = import_ig_deals(IG_SAMPLE, commit=True)
        self.assertEqual(counts, (13, 12))
        self.assertEqual((IgDeal.objects.count(), IgDealStatus.objects.count()), counts)
        self.assertEqual(second.inserted_rows, 0)
        self.assertEqual((LedgerEvent.objects.count(), JournalLine.objects.count(), Order.objects.count()), accounting)
        self.assertGreater(first.inserted_rows, 0)

    def test_forward_move_appends_exactly_one_status(self):
        import_ig_deals(self.source([self.one()]), commit=True)
        paid = self.one("paid")
        result = import_ig_deals(self.source([paid]), commit=True)
        self.assertEqual(result.inserted_rows, 1)
        self.assertEqual(IgDealStatus.objects.filter(deal_id="IG-202610-101").count(), 2)
        self.assertEqual(IgDeal.objects.get().status, "paid")

    def test_backward_and_out_of_lost_are_refused(self):
        for index, (initial, later) in enumerate(
                (("paid", "enquiry"), ("shipped", "quoted"), ("lost", "enquiry"))):
            with self.subTest(initial=initial, later=later):
                row = self.one(initial, deal_id=f"IG-202610-{110 + index:03d}",
                               customer_ref=f"C-{1100 + index}", wallet_txn_id=f"back-{index}")
                import_ig_deals(self.source([row]), commit=True)
                changed = self.one(later, deal_id=row["deal_id"], customer_ref=row["customer_ref"])
                with self.assertRaisesRegex(ImportRefused, "status cannot move backward"):
                    import_ig_deals(self.source([changed]), commit=True)

    def test_paid_fields_are_immutable(self):
        cases = {"quote_twd": "301.0000", "sku": "TS-GM-002-S", "qty_packs": "2",
                 "unit_price_twd": "301.0000", "wallet_txn_id": "88102"}
        for field, value in cases.items():
            with self.subTest(field=field):
                deal = f"IG-202610-{120 + list(cases).index(field):03d}"
                base = self.one("paid", deal_id=deal, wallet_txn_id=f"77{list(cases).index(field)}01")
                import_ig_deals(self.source([base]), commit=True)
                advanced = {**base, "status": "shipped", "ship_date": "2026-10-04", field: value}
                with self.assertRaisesRegex(ImportRefused, f"{field if field != 'sku' else 'sku'} cannot change"):
                    import_ig_deals(self.source([advanced]), commit=True)

    def test_open_next_action_wallet_collision_and_line_keys_refuse(self):
        with self.assertRaisesRegex(ImportRefused, "an open deal with no next action"):
            import_ig_deals(self.source([self.one(follow_up_on="")]))
        first = self.one("paid", deal_id="IG-202610-131", wallet_txn_id="same-wallet")
        second = self.one("paid", deal_id="IG-202610-132", customer_ref="C-0132", wallet_txn_id="same-wallet")
        with self.assertRaisesRegex(ImportRefused, "wallet_txn_id is used by two different deal_ids"):
            import_ig_deals(self.source([first, second]))
        duplicate = [self.one(), self.one()]
        with self.assertRaisesRegex(ImportRefused, r"repeats a \(deal_id, line_no\)"):
            import_ig_deals(self.source(duplicate))
        gap = [self.one(line_no="2")]
        with self.assertRaisesRegex(ImportRefused, "line_no gaps"):
            import_ig_deals(self.source(gap))

    def test_etsy_customer_collision_is_refused(self):
        channel = Channel.objects.create(code="etsy", name="Etsy")
        Order.objects.create(channel=channel, channel_order_id="C-0101", order_date="2026-10-01",
                             currency="TWD", discount_funded_by="none", gross_minor=0,
                             discount_minor=0, buyer_paid_minor=0, shipping_minor=0,
                             shipping_discount_minor=0, dest_country="TW", source_filename="synthetic",
                             dataset_kind="SAMPLE")
        with self.assertRaisesRegex(ImportRefused, "customer_ref appears on an Etsy order"):
            import_ig_deals(self.source([self.one()]))

    def test_pii_and_phone_in_evidence_are_refused(self):
        cases = (("person" + "@" + "example.test", "PII detected in evidence_ref"),
                 ("contact " + "@" + "handle", "PII detected in evidence_ref"),
                 ("call +886 912-345-678", "phone-shaped value detected in evidence_ref"))
        for value, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ImportRefused, message):
                import_ig_deals(self.source([self.one(evidence_ref=value)]))

    def test_actual_paid_waits_for_h0b(self):
        settings = DatasetSettings.load()
        settings.dataset_kind = "ACTUAL"
        settings.save(update_fields=["dataset_kind"])
        with self.assertRaisesRegex(ImportRefused, "paid Instagram deals cannot be committed as ACTUAL until H-0b"):
            import_ig_deals(self.source([self.one("paid")], "ig_deals_2026-10.csv"), commit=True)

    def test_reports_recompute_sample_counts_and_views_export(self):
        import_ig_deals(IG_SAMPLE, commit=True)
        pipeline = ig_pipeline("2026-11-15")
        follow, journey, conversion = pipeline.sections
        self.assertEqual(len(follow.rows), 3)
        self.assertEqual([row["step"] for row in journey.rows], ["d10", "d30"])
        self.assertTrue(all(row["customer_ref"] != "C-0006" for row in journey.rows))
        october = next(row for row in conversion.rows if row["month"] == "2026-10")
        self.assertEqual((october["enquiries"].amount, october["quoted"].amount,
                          october["paid"].amount, october["no_reply"].amount,
                          october["price"].amount), (12, 10, 6, 1, 1))
        self.assertEqual((october["quote_rate"].amount, october["paid_rate"].amount),
                         (Decimal("83.3333"), 50))
        november = next(row for row in conversion.rows if row["month"] == "2026-11")
        self.assertIsNone(november["quote_rate"].amount)
        repeat = repeat_rate("2026-10").rows[0]
        self.assertEqual((repeat["customers"].amount, repeat["repeat_customers"].amount,
                          repeat["rate"].amount), (4, 2, 50))

        user = get_user_model().objects.create_user(
            username="h0a-reviewer", password="synthetic-password")
        self.client.force_login(user)
        html = self.client.get(reverse("report-detail", args=["ig-pipeline"]), {"as_of": "2026-11-15"})
        self.assertContains(html, "Journey due")
        export = self.client.get(reverse("report-detail", args=["ig-pipeline"]),
                                 {"as_of": "2026-11-15", "format": "csv"})
        self.assertTrue(export["Content-Disposition"].startswith('attachment; filename="SAMPLE_'))
        self.assertTrue(export.content.decode().splitlines()[0].startswith("dataset_kind,SAMPLE,cost_basis,"))
