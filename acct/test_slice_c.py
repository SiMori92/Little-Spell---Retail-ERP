"""Slice C tests use synthetic codes and IDs only; failures must not print customer rows."""
import csv
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.test import TestCase

from acct.models import Account, JournalEntry, JournalLine
from acct.reporting import (Figure, REPORT_BUILDERS, balance_sheet, cac_report,
                            contribution_channels, contribution_orders, contribution_skus,
                            inventory_roll_forward, profit_loss)
from ops.models import Channel, InventoryMove, LedgerEvent, Order, OrderLine, Product, Shipment

PERIOD = "2025-03"
NOW = datetime(2025, 3, 15, 12, tzinfo=dt_timezone.utc)


class EmptySourceReportTests(TestCase):
    def test_missing_inputs_are_absent_and_inventory_unprovable(self):
        orders = contribution_orders(PERIOD)
        self.assertIsNone(orders.rows[0]["contribution"].amount)
        self.assertIn("ABSENT", orders.rows[0]["contribution"].display())
        self.assertEqual(inventory_roll_forward(PERIOD).notes[0], "G-3 reporting identity: UNPROVABLE.")
        self.assertIsNone(cac_report(PERIOD).rows[-1]["cac"].amount)
        self.assertIsNone(profit_loss(PERIOD).rows[0]["balance"].amount)
        self.assertIsNone(balance_sheet(PERIOD).rows[0]["balance"].amount)

    def test_provisional_figure_cannot_render_bare(self):
        figure = Figure(Decimal("123.45"), "SAMPLE", "provisional", PERIOD, "landed cost missing")
        self.assertIn("PROVISIONAL COST BASIS", figure.display())
        self.assertIn("landed cost missing", figure.display())

    def test_sample_csv_has_both_markers_and_no_private_fields(self):
        user = get_user_model().objects.create_user(username="reporter-test", password="synthetic-pass")
        self.client.force_login(user)
        response = self.client.get("/reports/contribution-orders/?period=2025-03&format=csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("SAMPLE_contribution-orders_2025-03.csv", response["Content-Disposition"])
        rows = list(csv.reader(StringIO(response.content.decode())))
        self.assertEqual(rows[0][0:4], ["dataset_kind", "SAMPLE", "cost_basis", "absent"])
        self.assertEqual(rows[0][4], "generated_at")
        self.assertTrue(rows[0][5])
        self.assertEqual(rows[1][0], "Order")
        self.assertNotIn("Buyer", ",".join(rows[1]))
        self.assertNotIn("Address", ",".join(rows[1]))
        self.assertEqual(rows[2][2], "ABSENT")

    def test_reports_require_login_and_bad_period_is_rejected(self):
        response = self.client.get("/reports/contribution-skus/?period=2025-03")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])
        user = get_user_model().objects.create_user(username="reporter-test", password="synthetic-pass")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/reports/cac/?period=2025-13").status_code, 400)

    def test_every_empty_report_renders_html_and_csv(self):
        user = get_user_model().objects.create_user(username="reporter-test", password="synthetic-pass")
        self.client.force_login(user)
        for slug in REPORT_BUILDERS:
            with self.subTest(slug=slug):
                url = f"/reports/{slug}/?period={PERIOD}"
                self.assertEqual(self.client.get(url).status_code, 200)
                response = self.client.get(url + "&format=csv")
                self.assertEqual(response.status_code, 200)
                self.assertIn("SAMPLE_", response["Content-Disposition"])


class SyntheticContributionTests(TestCase):
    def setUp(self):
        self.channel = Channel.objects.create(code="etsy", name="Etsy")
        self.a = Product.objects.create(sku="SKU-A", name="A", uom="PK")
        self.b = Product.objects.create(sku="SKU-B", name="B", uom="PK")
        self.order = Order.objects.create(channel=self.channel, channel_order_id="SYN-1",
            order_date=date(2025, 3, 15), currency="TWD", discount_funded_by="seller",
            gross_minor=30000, discount_minor=2000, buyer_paid_minor=28000,
            shipping_minor=5000, shipping_discount_minor=0, tax_remitted_by_platform_minor=0,
            dest_country="US", source_filename="synthetic", dataset_kind="SAMPLE")
        OrderLine.objects.create(order=self.order, product=self.a, platform_transaction_id="SYN-A",
            line_index=1, qty_packs=1, unit_price_minor=15000, line_discount_minor=1200,
            item_total_minor=13800, source_filename="synthetic", dataset_kind="SAMPLE")
        OrderLine.objects.create(order=self.order, product=self.b, platform_transaction_id="SYN-B",
            line_index=2, qty_packs=1, unit_price_minor=10000, line_discount_minor=800,
            item_total_minor=9200, source_filename="synthetic", dataset_kind="SAMPLE")
        Shipment.objects.create(order=self.order, status="dispatched", ship_date=date(2025,3,15),
                                source_filename="synthetic", dataset_kind="SAMPLE")
        self.entry("order.shipped", [("2211",280,0,None), ("4191",20,0,None),
                                     ("4111",0,250,None), ("4181",0,50,None)])
        self.entry("order.fees_assessed", [("6111",10,0,None), ("6112",5,0,None),
                                           ("1191",0,15,None)])
        self.cogs = self.entry("order.cogs_relieved", [("5111",40,0,"SKU-A"), ("1231",0,40,"SKU-A"),
                                                       ("5111",30,0,"SKU-B"), ("1231",0,30,"SKU-B"),
                                                       ("5114",5,0,None), ("1233",0,5,None)],
                               payload={"cost_basis":"actual"})
        self.entry("order.ship_cost_accrued", [("6131",10,0,None), ("2191",0,10,None)])
        self.entry("order.ship_cost_invoiced", [("2191",10,0,None), ("6131",2,0,None),
                                                ("2172",0,12,None)])
        self.entry("order.duty_incurred", [("6132",2,0,None), ("2192",0,2,None)],
                   payload={"duty_position":"DDP"})
        self.entry("order.duty_invoiced", [("2192",2,0,None), ("6132",1,0,None),
                                           ("2172",0,3,None)])
        self.entry("settlement.received", [("1121",100,0,None), ("6116",2,0,None),
                                            ("1191",0,102,None)], entity_table="ops.etsystatementrow",
                   payload={"covers_order_ids":["SYN-1"]})
        self.entry("cost.recorded", [("6115",20,0,None), ("1191",0,20,None)],
                   entity_table="ops.etsystatementrow", payload={"category":"platform_listing_fee"})
        self.entry("cost.recorded", [("6141",24,0,None), ("1121",0,24,None)],
                   entity_table="ops.etsystatementrow", payload={"category":"advertising","channel_attribution":"etsy"})

    def entry(self, event_type, lines, *, entity_table="ops.order", payload=None):
        seq = JournalEntry.objects.count() + 1
        entry = JournalEntry.objects.create(occurred_at=NOW, period=PERIOD, dataset_kind="SAMPLE",
                                            source_kind="ops", source_ref=f"synthetic-report-{seq}")
        for code, debit, credit, sku in lines:
            JournalLine.objects.create(entry=entry, account=Account.objects.get(pk=code),
                                       debit=Decimal(debit), credit=Decimal(credit), sku=sku)
        return LedgerEvent.objects.create(event_type=event_type, entity_table=entity_table,
            entity_id=self.order.pk, occurred_at=NOW, amount_minor=None, currency="TWD",
            payload=payload or {}, idempotency_key=f"report-event-{seq}",
            posted_entry_id=entry.pk, source_filename="synthetic", dataset_kind="SAMPLE")

    def test_hand_computed_order_contribution_and_listing_fee_exclusion(self):
        report = contribution_orders(PERIOD)
        row = report.rows[0]
        self.assertEqual(row["contribution"].amount, Decimal("173.0000"))
        self.assertEqual(row["gap"].amount, Decimal("-27.0000"))
        self.assertEqual(row["after"].amount, Decimal("149.0000"))
        self.assertEqual(row["contribution"].cost_basis, "actual")
        self.assertIn("TIES", report.notes[2])
        self.entry("cost.recorded", [("6115",10,0,None), ("1191",0,10,None)],
                   entity_table="ops.etsystatementrow", payload={"category":"platform_listing_fee"})
        self.assertEqual(contribution_orders(PERIOD).rows[0]["contribution"].amount, Decimal("173.0000"))
        self.assertIn("TIES", contribution_orders(PERIOD).notes[2])

    def test_period_ledger_mismatch_is_disclosed(self):
        self.entry("cost.recorded", [("6116",1,0,None), ("1191",0,1,None)],
                   entity_table="ops.etsystatementrow")
        self.assertIn("MISMATCH", contribution_orders(PERIOD).notes[2])

    def test_unposted_accrual_does_not_become_actual_from_invoice(self):
        freight = LedgerEvent.objects.get(event_type="order.ship_cost_accrued")
        LedgerEvent.objects.filter(pk=freight.pk).update(posted_entry_id=None)
        row = contribution_orders(PERIOD).rows[0]
        self.assertIsNone(row["freight"].amount)
        self.assertIsNone(row["contribution"].amount)
        LedgerEvent.objects.filter(pk=freight.pk).update(posted_entry_id=freight.posted_entry_id)
        duty = LedgerEvent.objects.get(event_type="order.duty_incurred")
        LedgerEvent.objects.filter(pk=duty.pk).update(posted_entry_id=None)
        row = contribution_orders(PERIOD).rows[0]
        self.assertIsNone(row["duty"].amount)

    def test_sku_and_channel_reconcile_to_order_total(self):
        order_total = contribution_orders(PERIOD).rows[0]["contribution"].amount
        sku = contribution_skus(PERIOD)
        self.assertEqual(sum(row["contribution"].amount for row in sku.rows), order_total)
        self.assertEqual(sku.rows[0]["sku"], "SKU-A")
        self.assertEqual(sku.rows[0]["contribution"].amount, Decimal("105.8000"))
        channel = contribution_channels(PERIOD)
        self.assertEqual(channel.rows[0]["contribution"].amount, order_total)
        self.assertEqual(channel.rows[0]["gap"].amount, Decimal("-27.0000"))

    def test_sku_winner_is_absent_when_cogs_tagging_is_incomplete(self):
        entry = JournalEntry.objects.create(occurred_at=NOW, period=PERIOD, dataset_kind="SAMPLE",
                                            source_kind="ops", source_ref="synthetic-untagged-cogs")
        JournalLine.objects.create(entry=entry, account=Account.objects.get(pk="5111"),
                                   debit=Decimal(70))
        JournalLine.objects.create(entry=entry, account=Account.objects.get(pk="1231"),
                                   credit=Decimal(70))
        JournalLine.objects.create(entry=entry, account=Account.objects.get(pk="5114"),
                                   debit=Decimal(5))
        JournalLine.objects.create(entry=entry, account=Account.objects.get(pk="1233"),
                                   credit=Decimal(5))
        LedgerEvent.objects.filter(pk=self.cogs.pk).update(posted_entry_id=entry.pk)
        report = contribution_skus(PERIOD)
        self.assertTrue(all(row["contribution"].amount is None for row in report.rows))
        self.assertIn("ABSENT", report.notes[0])

    def test_missing_cogs_makes_contribution_absent_and_provisional_banners_show(self):
        self.cogs.payload = {"cost_basis":"provisional"}
        self.cogs.save(update_fields=["payload"])
        row = contribution_orders(PERIOD).rows[0]
        self.assertEqual(row["contribution"].cost_basis, "provisional")
        self.assertIn("PROVISIONAL COST BASIS", row["contribution"].display())
        LedgerEvent.objects.filter(pk=self.cogs.pk).update(posted_entry_id=None)
        row = contribution_orders(PERIOD).rows[0]
        self.assertIsNone(row["contribution"].amount)
        self.assertIn("ABSENT", row["contribution"].display())

    def test_pnl_balance_sheet_and_cac_use_only_posted_lines(self):
        pnl = profit_loss(PERIOD)
        labels = [row["account"] for row in pnl.rows]
        self.assertTrue(any(label.startswith("6115") for label in labels))
        self.assertEqual(cac_report(PERIOD).rows[-1]["cac"].amount, Decimal("24.0000"))
        self.assertTrue(any(row["account"].startswith("1121") for row in balance_sheet(PERIOD).rows))

    def test_estimated_ad_spend_marks_cac_and_pnl(self):
        advertising = LedgerEvent.objects.get(event_type="cost.recorded", payload__category="advertising")
        advertising.payload = {**advertising.payload, "basis": "estimate"}
        advertising.save(update_fields=["payload"])
        blended = cac_report(PERIOD).rows[-1]
        self.assertEqual(blended["cac"].cost_basis, "provisional")
        self.assertIn("[ESTIMATE]", blended["cac"].display())
        ad_pnl = next(row for row in profit_loss(PERIOD).rows if row["account"].startswith("6141"))
        self.assertIn("[ESTIMATE]", ad_pnl["balance"].display())

    def test_inventory_does_not_invent_opening_count(self):
        report = inventory_roll_forward(PERIOD)
        self.assertEqual(report.notes[0], "G-3 reporting identity: UNPROVABLE.")
        self.assertTrue(all(row["opening"].amount is None for row in report.rows))
        self.assertTrue(all(row["identity"].startswith("UNPROVABLE") for row in report.rows))

    def test_html_and_csv_keep_provenance(self):
        user = get_user_model().objects.create_user(username="reporter-test", password="synthetic-pass")
        self.client.force_login(user)
        response = self.client.get("/reports/contribution-orders/?period=2025-03")
        self.assertContains(response, "SAMPLE DATA — NOT ACTUALS")
        self.assertContains(response, "data-cost-basis=\"actual\"")
        csv_response = self.client.get("/reports/contribution-orders/?period=2025-03&format=csv")
        rows = list(csv.reader(StringIO(csv_response.content.decode())))
        self.assertEqual(rows[0][1], "SAMPLE")
        self.assertEqual(rows[2][0], "SYN-1")
        self.assertEqual(rows[2][rows[1].index("contribution_cost_basis")], "actual")
        self.assertNotIn("Buyer", csv_response.content.decode())
        self.assertNotIn("Address", csv_response.content.decode())


class InventoryTieTests(TestCase):
    def test_independent_ops_value_and_gl_tie_or_mismatch(self):
        sku = Product.objects.create(sku="COUNTED", name="Counted", uom="PK")
        opening_at = datetime(2025,2,28,12,tzinfo=dt_timezone.utc)
        count_entry = JournalEntry.objects.create(occurred_at=opening_at, period="2025-02",
            dataset_kind="SAMPLE", source_kind="ops", source_ref="synthetic-count")
        JournalLine.objects.create(entry=count_entry, account=Account.objects.get(pk="1231"), debit=Decimal(50), sku="COUNTED")
        JournalLine.objects.create(entry=count_entry, account=Account.objects.get(pk="3111"), credit=Decimal(50))
        LedgerEvent.objects.create(event_type="inventory.opening_counted", entity_table="ops.product", entity_id=1,
            occurred_at=opening_at, payload={"sku":"COUNTED","qty":"5"},
            idempotency_key="synthetic-count", posted_entry_id=count_entry.pk,
            source_filename="synthetic", dataset_kind="SAMPLE")
        InventoryMove.objects.create(product=sku, kind="opening", qty_delta_packs=5,
            value_delta_twd=Decimal(50), occurred_at=opening_at, idempotency_key="synthetic-open",
            source_filename="synthetic", dataset_kind="SAMPLE")
        sold_entry = JournalEntry.objects.create(occurred_at=NOW, period=PERIOD,
            dataset_kind="SAMPLE", source_kind="ops", source_ref="synthetic-sold")
        JournalLine.objects.create(entry=sold_entry, account=Account.objects.get(pk="5111"), debit=Decimal(10), sku="COUNTED")
        JournalLine.objects.create(entry=sold_entry, account=Account.objects.get(pk="1231"), credit=Decimal(10), sku="COUNTED")
        move = InventoryMove.objects.create(product=sku, kind="sold", qty_delta_packs=-1,
            value_delta_twd=Decimal(-10), occurred_at=NOW, idempotency_key="synthetic-sold",
            source_filename="synthetic", dataset_kind="SAMPLE")
        report = inventory_roll_forward(PERIOD)
        self.assertEqual(report.rows[0]["identity"], "TIES")
        self.assertEqual(report.rows[0]["ops_value"].amount, Decimal("40.0000"))
        self.assertEqual(report.rows[0]["gl_value"].amount, Decimal("40.0000"))
        move.value_delta_twd = Decimal(-9)
        move.save(update_fields=["value_delta_twd"])
        report = inventory_roll_forward(PERIOD)
        self.assertTrue(report.rows[0]["identity"].startswith("MISMATCH"))
