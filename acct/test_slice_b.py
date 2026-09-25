"""Slice B tests assert on codes, IDs and counts; never render customer rows."""
from datetime import date, datetime, timezone as dt_timezone, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings

from acct.gates import assert_g1
from acct.models import Account, AcctManualEntry, FxRate, JournalEntry, JournalLine, Period, WacPosition
from acct.posting import OPS_RULES, MANUAL_RULES, PostingError, plan, post_event
from ops.models import Channel, InventoryMove, LedgerEvent, Order, OrderLine, Product, Shipment

NOW = datetime(2025, 3, 27, 12, tzinfo=dt_timezone.utc)


class PostingRulesTests(TestCase):
    def setUp(self):
        FxRate.objects.create(rate_date=date(2025,3,27), currency="USD", kind="public", rate="32.000000", rate_source="manual", evidence_ref="synthetic-rate")
        channel = Channel.objects.create(code="TEST", name="Test")
        product = Product.objects.create(sku="TESTSKU", name="Test", uom="PK")
        self.order = Order.objects.create(channel=channel, channel_order_id="TEST-1", order_date=date(2025,3,27), currency="USD", coupon_code="", discount_funded_by="seller", gross_minor=1000, discount_minor=100, buyer_paid_minor=900, shipping_minor=100, shipping_discount_minor=0, tax_remitted_by_platform_minor=0, dest_country="US", source_filename="synthetic", dataset_kind="SAMPLE")
        OrderLine.objects.create(order=self.order, product=product, platform_transaction_id="TEST-TXN", listing_id="TEST-LIST", line_index=1, qty_packs=1, unit_price_minor=900, line_discount_minor=100, item_total_minor=800, source_filename="synthetic", dataset_kind="SAMPLE")
        Shipment.objects.create(order=self.order, status="dispatched", ship_date=date(2025,3,27), source_filename="synthetic", dataset_kind="SAMPLE")
        InventoryMove.objects.create(product=product, kind="opening", qty_delta_packs=2, occurred_at=NOW, idempotency_key="TEST-STOCK", source_filename="synthetic", dataset_kind="SAMPLE")
        WacPosition.objects.create(sku="TESTSKU", qty_packs=Decimal(2), value_twd=Decimal(10))
        self.placed = LedgerEvent.objects.create(event_type="order.placed", entity_table="ops.order", entity_id=self.order.pk, occurred_at=NOW, amount_minor=900, currency="USD", payload={"discount_funded_by":"seller"}, idempotency_key="test-placed", source_filename="synthetic", dataset_kind="SAMPLE")

    def event(self, event_type, *, payload=None, amount=1000, currency="TWD", entity_table="ops.order"):
        return LedgerEvent(event_type=event_type, entity_table=entity_table, entity_id=self.order.pk, occurred_at=NOW, amount_minor=amount, currency=currency, payload=payload or {}, idempotency_key=f"synthetic-{event_type}", source_filename="synthetic", dataset_kind="SAMPLE")

    def test_every_postable_ops_rule_balances(self):
        cases = {
            "order.placed": self.placed,
            "order.fees_assessed": self.event("order.fees_assessed", payload={"fee_components":[{"code":"6111","amount":100}],"channel_applied_fx_rate":"31.000000"}, currency="USD"),
            "order.shipped": self.event("order.shipped"),
            "order.cogs_relieved": self.event("order.cogs_relieved"),
            "order.ship_cost_accrued": self.event("order.ship_cost_accrued", payload={"basis":"estimate","basis_note":"synthetic"}),
            "order.ship_cost_invoiced": self.event("order.ship_cost_invoiced", payload={"accrual_ref":"A","accrued_twd":"8"}),
            "order.duty_incurred": self.event("order.duty_incurred", payload={"duty_position":"DDP"}),
            "order.duty_invoiced": self.event("order.duty_invoiced", payload={"accrual_ref":"A","accrued_twd":"8"}),
            "order.reprint_issued": self.event("order.reprint_issued", payload={"decisions_ref":"D"}),
            "order.cancelled": self.event("order.cancelled", payload={"dispatch_phase":"pre"}),
            "order.refunded": self.event("order.refunded", payload={"fee_refunds":[{"original_account":"6112","amount_twd":"2"}]}),
            "settlement.received": self.event("settlement.received", amount=31000, payload={"channel_applied_fx_rate":"31.000000","rate_source":"stated","usd_settled":"10","rate_evidence_ref":"synthetic"}),
            "settlement.reversed": self.event("settlement.reversed", payload={"original_carrying_twd":"320","bank_reversal_twd":"325","reversal_fee_twd":"5"}),
            "po.in_transit": self.event("po.in_transit"),
            "po.received": self.event("po.received", payload={"landed_components_twd":{"product":"100","packaging":"10","supplier":"100","freight":"5","duty":"5","in_transit":"0"},"sku_receipts":[{"sku":"TESTSKU","qty_packs":"10","landed_cost_twd":"100"}]}),
            "po.landed_cost_adjusted": self.event("po.landed_cost_adjusted", payload={"onhand_ratio":"0.4","lot_ref":"L","sku":"TESTSKU"}),
            "po.paid": self.event("po.paid", payload={"bank_ref":"B"}),
            "inventory.adjusted": self.event("inventory.adjusted", payload={"evidence_ref":"COUNT","sku":"TESTSKU","qty":"2"}),
            "inventory.opening_counted": self.event("inventory.opening_counted", payload={"sku":"TESTSKU","qty":"2","agreed_unit_cost_twd":"5"}),
            "cost.recorded": self.event("cost.recorded", entity_table="ops.etsystatementrow", payload={"category":"platform_listing_fee","settled_via":"etsy_rail"}),
        }
        self.assertEqual(len(cases), 20)
        for name, event in cases.items():
            with self.subTest(event_type=name):
                lines = plan(event)
                self.assertGreaterEqual(len(lines), 2)
                self.assertEqual(sum(x.debit-x.credit for x in lines), 0)
                self.assertNotIn("7111", [line.account for line in lines], name)
        self.assertEqual(len(OPS_RULES), 22)

    def test_blocked_and_memo_paths_are_explicit(self):
        for name in ("payment.received", "payment.refunded"):
            with self.assertRaisesRegex(PostingError, "RESERVED"):
                plan(self.event(name))
        self.assertIsNone(plan(self.event("order.duty_incurred", payload={"duty_position":"DDU"})))
        with self.assertRaisesRegex(PostingError, "unhandled"):
            plan(self.event("unknown.event"))

    def test_settlement_requires_rate_and_spread_is_only_6116(self):
        with self.assertRaisesRegex(PostingError, "channel_applied_fx_rate"):
            plan(self.event("settlement.received"))
        e = self.event("settlement.received", amount=31000, payload={"channel_applied_fx_rate":"31.000000","rate_source":"derived","usd_settled":"10","rate_evidence_ref":"synthetic"})
        lines = plan(e)
        self.assertEqual([x.account for x in lines], ["1121", "1191", "6116"])
        self.assertNotIn("7111", [x.account for x in lines])
        rate = FxRate.objects.get(kind="channel")
        self.assertEqual(rate.rate_source, "derived")
        another = self.event("settlement.received", amount=31000, payload={"channel_applied_fx_rate":"31.000000","rate_source":"stated","usd_settled":"10","rate_evidence_ref":"synthetic-stated"})
        another.idempotency_key = "synthetic-stated-rate"
        plan(another)
        self.assertEqual(set(FxRate.objects.filter(kind="channel").values_list("rate_source", flat=True)), {"derived", "stated"})
        e.payload["rate_source"] = "stated"
        with self.assertRaisesRegex(PostingError, "conflicts"):
            plan(e)

    def test_addendum_d_negative_spread_credits_6116_and_large_spread_escalates(self):
        favourable = self.event("settlement.received", amount=33000, payload={"channel_applied_fx_rate":"33.000000", "rate_source":"stated", "usd_settled":"10", "rate_evidence_ref":"synthetic-favourable"})
        favourable.idempotency_key = "synthetic-favourable"
        lines = plan(favourable)
        self.assertEqual([(line.account, line.credit) for line in lines if line.account == "6116"], [("6116", Decimal("10.0000"))])
        self.assertNotIn("7111", [line.account for line in lines])
        excessive = self.event("settlement.received", amount=10000, payload={"channel_applied_fx_rate":"10.000000", "rate_source":"stated", "usd_settled":"10", "rate_evidence_ref":"synthetic-excessive"})
        excessive.idempotency_key = "synthetic-excessive"
        with self.assertRaisesRegex(PostingError, "provisional tolerance"):
            plan(excessive)
        with override_settings(SETTLEMENT_SPREAD_TOLERANCE_FRACTION=Decimal("0.01")):
            with self.assertRaisesRegex(PostingError, "provisional tolerance"):
                plan(favourable)

    def test_addendum_d_reversal_rate_delta_never_uses_7111(self):
        for bank in ("330", "310"):
            with self.subTest(bank=bank):
                event = self.event("settlement.reversed", payload={"original_carrying_twd":"320", "bank_reversal_twd":bank, "reversal_fee_twd":"0"})
                lines = plan(event)
                self.assertIn("6116", [line.account for line in lines])
                self.assertNotIn("7111", [line.account for line in lines])
                self.assertEqual(sum(line.debit-line.credit for line in lines), 0)

    def test_listing_fee_and_advertising_guard(self):
        listing = self.event("cost.recorded", entity_table="ops.etsystatementrow", payload={"category":"platform_listing_fee","settled_via":"etsy_rail"})
        self.assertEqual([x.account for x in plan(listing)], ["1191", "6115"])
        with self.assertRaisesRegex(PostingError, "channel_attribution"):
            plan(self.event("cost.recorded", payload={"category":"advertising","settled_via":"bank"}))

    def test_seed_refuses_unspecified_amount(self):
        with self.assertRaises(CommandError):
            call_command("seed_sample_cash", entry_date=date(2025,3,27))

    def test_all_six_manual_rules_balance(self):
        original_entry = JournalEntry.objects.create(occurred_at=NOW, period="2025-03", dataset_kind="SAMPLE", source_kind="manual", source_ref="synthetic-accrual")
        JournalLine.objects.create(entry=original_entry, account=Account.objects.get(pk="6131"), debit=Decimal(10))
        JournalLine.objects.create(entry=original_entry, account=Account.objects.get(pk="2191"), credit=Decimal(10))
        original = AcctManualEntry.objects.create(event_type="period.accrued", occurred_at=NOW, period="2025-03", amount=Decimal(10), currency="TWD", payload={"expense_account":"6131","accrual_account":"2191","basis_note":"synthetic"}, basis="estimate", idempotency_key="synthetic-accrual", posted_entry=original_entry)
        cases = {
            "period.revalued": {"payload":{"revalued_account":"1191","rate_source":"synthetic","direction":"loss"}},
            "period.accrued": {"payload":{"expense_account":"6131","accrual_account":"2191","basis_note":"synthetic"}, "basis":"estimate"},
            "period.accrual_reversed": {"reverses":original},
            "tax.assessed": {"evidence_ref":"synthetic-voucher","needs_prof_conf":True},
            "tax.paid": {"evidence_ref":"synthetic-voucher"},
            "owner.funds_moved": {"payload":{"funds_type":"capital"}},
        }
        self.assertEqual(len(cases), len(MANUAL_RULES))
        for name, kwargs in cases.items():
            with self.subTest(event_type=name):
                event = AcctManualEntry(event_type=name, occurred_at=NOW, period="2025-03", amount=Decimal(10), currency="TWD", idempotency_key=f"synthetic-{name}", **kwargs)
                lines = plan(event)
                self.assertEqual(sum(x.debit-x.credit for x in lines), 0)

    def test_manual_event_posts_without_writing_ops_event(self):
        before = LedgerEvent.objects.count()
        event = AcctManualEntry.objects.create(event_type="tax.paid", occurred_at=NOW, period="2025-03", amount=Decimal(10), currency="TWD", evidence_ref="synthetic-voucher", idempotency_key="manual-post")
        entry_id = post_event(event)
        self.assertEqual(AcctManualEntry.objects.get(pk=event.pk).posted_entry_id, entry_id)
        self.assertEqual(LedgerEvent.objects.count(), before)
        with connection.cursor() as c:
            c.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_g1_covers_both_event_tables(self):
        cutoff = NOW + timedelta(days=1)
        with self.assertRaisesRegex(ValueError, "ops=1"):
            assert_g1(cutoff)
        self.placed.delete()
        manual = AcctManualEntry.objects.create(event_type="tax.paid", occurred_at=NOW, period="2025-03", amount=Decimal(1), currency="TWD", evidence_ref="synthetic", payload={}, idempotency_key="manual-g1")
        with self.assertRaisesRegex(ValueError, "manual=1"):
            assert_g1(cutoff)

    def test_order_placed_posts_deferred_revenue_not_sales(self):
        entry_id = post_event(self.placed)
        self.assertEqual(self.placed.pk, LedgerEvent.objects.get(pk=self.placed.pk).pk)
        self.assertEqual(LedgerEvent.objects.get(pk=self.placed.pk).posted_entry_id, entry_id)
        lines = JournalLine.objects.filter(entry_id=entry_id)
        self.assertEqual(set(lines.values_list("account_id", flat=True)), {"1191", "2211"})
        self.assertEqual(sum(line.debit-line.credit for line in lines), 0)
        with connection.cursor() as c:
            c.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_seller_discount_conflicting_with_gross_rail_is_refused(self):
        self.placed.amount_minor = 1000
        with self.assertRaisesRegex(PostingError, "contradicts discount funder"):
            plan(self.placed)

    def test_dispatch_revenue_waits_for_posted_deposit(self):
        shipped = LedgerEvent.objects.create(event_type="order.shipped", entity_table="ops.order", entity_id=self.order.pk, occurred_at=NOW, amount_minor=900, currency="USD", payload={}, idempotency_key="synthetic-shipped", source_filename="synthetic", dataset_kind="SAMPLE")
        with self.assertRaisesRegex(PostingError, "deposit to be posted first"):
            post_event(shipped)
        post_event(self.placed)
        entry_id = post_event(shipped)
        self.assertEqual(set(JournalLine.objects.filter(entry_id=entry_id).values_list("account_id", flat=True)), {"2211", "4111", "4181", "4191"})
        with connection.cursor() as c:
            c.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_cogs_uses_running_weighted_average_per_sku(self):
        receipt = LedgerEvent.objects.create(event_type="po.received", entity_table="ops.order", entity_id=self.order.pk, occurred_at=NOW, amount_minor=None, currency="TWD", payload={"landed_components_twd":{"product":"30","packaging":"0","supplier":"30","freight":"0","duty":"0","in_transit":"0"},"sku_receipts":[{"sku":"TESTSKU","qty_packs":"3","landed_cost_twd":"30"}]}, idempotency_key="synthetic-receipt", source_filename="synthetic", dataset_kind="SAMPLE")
        post_event(receipt)
        cogs_event = LedgerEvent.objects.create(event_type="order.cogs_relieved", entity_table="ops.order", entity_id=self.order.pk, occurred_at=NOW, amount_minor=None, currency="TWD", payload={}, idempotency_key="synthetic-cogs", source_filename="synthetic", dataset_kind="SAMPLE")
        entry_id = post_event(cogs_event)
        self.assertEqual(JournalLine.objects.get(entry_id=entry_id, account_id="5111").debit, Decimal("8.0000"))
        position = WacPosition.objects.get(pk="TESTSKU")
        self.assertEqual(position.qty_packs, 4)
        self.assertEqual(position.value_twd, Decimal("32.0000"))
        with connection.cursor() as c:
            c.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_ddu_is_acknowledged_without_financial_lines(self):
        event = LedgerEvent.objects.create(event_type="order.duty_incurred", entity_table="ops.order", entity_id=self.order.pk, occurred_at=NOW, amount_minor=1000, currency="TWD", payload={"duty_position":"DDU"}, idempotency_key="synthetic-ddu", source_filename="synthetic", dataset_kind="SAMPLE")
        entry_id = post_event(event)
        self.assertTrue(JournalEntry.objects.get(pk=entry_id).memo_only)
        self.assertEqual(JournalLine.objects.filter(entry_id=entry_id).count(), 0)
        with connection.cursor() as c:
            c.execute("SET CONSTRAINTS ALL IMMEDIATE")


class JournalDatabaseTests(TransactionTestCase):
    def setUp(self):
        # TransactionTestCase flushes data-migration rows between tests.
        for code in ("1121", "3111", "1191", "2211"):
            Account.objects.get_or_create(code=code, defaults={"name_en":code, "name_zh":code, "type":"asset", "statement":"BS", "normal_balance":"debit"})

    def make_entry(self, period="2025-03"):
        at = NOW if period == "2025-03" else datetime(2025,4,1,tzinfo=dt_timezone.utc)
        with transaction.atomic():
            entry = JournalEntry.objects.create(occurred_at=at, period=period, dataset_kind="SAMPLE", source_kind="seed", source_ref=f"test-{period}")
            a = JournalLine.objects.create(entry=entry, account=Account.objects.get(pk="1121"), debit=Decimal(10))
            JournalLine.objects.create(entry=entry, account=Account.objects.get(pk="3111"), credit=Decimal(10))
        return entry, a

    def test_update_delete_refused_as_each_role(self):
        entry, line = self.make_entry()
        for role in ("ops_writer", "acct_writer", "reporter"):
            for action in ("UPDATE", "DELETE"):
                with self.subTest(role=role, action=action):
                    with self.assertRaises(DatabaseError):
                        with transaction.atomic():
                            with connection.cursor() as c:
                                c.execute(f"SET LOCAL ROLE {role}")
                                if action == "UPDATE":
                                    c.execute("UPDATE acct_journalline SET debit=20 WHERE id=%s", [line.pk])
                                else:
                                    c.execute("DELETE FROM acct_journalline WHERE id=%s", [line.pk])

    def test_acct_writer_cannot_insert_ops_event(self):
        with connection.cursor() as c:
            c.execute("SELECT has_table_privilege('acct_writer', 'ops_ledgerevent', 'INSERT')")
            self.assertFalse(c.fetchone()[0])

    def test_manual_event_facts_are_immutable(self):
        event = AcctManualEntry.objects.create(event_type="tax.paid", occurred_at=NOW, period="2025-03", amount=Decimal(1), currency="TWD", evidence_ref="synthetic", idempotency_key="manual-immutable")
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                AcctManualEntry.objects.filter(pk=event.pk).update(amount=Decimal(2))
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                AcctManualEntry.objects.filter(pk=event.pk).delete()

    def test_owner_is_still_blocked_by_append_only_trigger(self):
        entry, line = self.make_entry()
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                JournalLine.objects.filter(pk=line.pk).update(debit=Decimal(20))

    def test_closed_period_rejects_entry_and_line(self):
        entry, _ = self.make_entry()
        Period.objects.create(period="2025-03", status="CLOSED")
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                JournalEntry.objects.create(occurred_at=NOW, period="2025-03", dataset_kind="SAMPLE", source_kind="ops", source_ref="closed")
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                JournalLine.objects.create(entry=entry, account=Account.objects.get(pk="1121"), debit=Decimal(1))

    def test_fx_entry_balances_twd_not_per_currency(self):
        rate = FxRate.objects.create(rate_date=date(2025,3,27), currency="USD", kind="public", rate="32", rate_source="manual", evidence_ref="synthetic")
        with transaction.atomic():
            entry = JournalEntry.objects.create(occurred_at=NOW, period="2025-03", dataset_kind="SAMPLE", source_kind="ops", source_ref="fx-mixed")
            JournalLine.objects.create(entry=entry, account=Account.objects.get(pk="1191"), debit=Decimal(320), txn_amount=Decimal(10), txn_currency="USD", fx_rate=rate)
            JournalLine.objects.create(entry=entry, account=Account.objects.get(pk="2211"), credit=Decimal(320))
        self.assertEqual(sum(x.debit-x.credit for x in entry.lines.all()), 0)
        usd_net = sum(x.debit-x.credit for x in entry.lines.filter(txn_currency="USD"))
        self.assertNotEqual(usd_net, 0)
