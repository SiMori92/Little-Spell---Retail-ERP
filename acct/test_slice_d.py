"""Synthetic IDs and amounts only. Never print customer rows on test failure."""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.db import DatabaseError, transaction
from django.contrib.auth import get_user_model

from acct.close import record_gate1, reopen_period, run_close, verify_close_signature
from acct.gates import GateResult, business_days, g1, g2, g3, g4, g5, settlement_aging
from acct.models import (Account, AcctManualEntry, ClearingCause, CloseAudit, JournalEntry,
                         JournalLine, Period)
from acct.reconciliation import carrier_reconciliation, settlement_aging_report
from acct.test_slice_c import SyntheticContributionTests, PERIOD, NOW
from ops.models import InventoryMove, LedgerEvent, OpsPeriod, Product


def entry(ref, when=NOW, period=PERIOD, legs=()):
    journal = JournalEntry.objects.create(source_kind="ops", source_ref=ref, occurred_at=when,
                                          period=period, dataset_kind="SAMPLE")
    created = []
    for account, debit, credit, sku, qty, memo, source in legs:
        created.append(JournalLine.objects.create(entry=journal, account=Account.objects.get(pk=account),
            debit=Decimal(str(debit)), credit=Decimal(str(credit)), sku=sku,
            qty_delta_packs=qty, memo=memo, source_ref=source))
    return journal, created


def leg(account, debit=0, credit=0, sku=None, qty=None, memo="", source="synthetic"):
    return account, debit, credit, sku, qty, memo, source


class G1Tests(TestCase):
    def test_positive_both_streams_empty(self):
        self.assertEqual(g1(PERIOD).status, "PASS")

    def test_ops_null_link_and_error_both_fail(self):
        event = LedgerEvent.objects.create(event_type="order.placed", entity_table="ops.order", entity_id=1,
            occurred_at=NOW, idempotency_key="g1-ops", source_filename="synthetic", dataset_kind="SAMPLE")
        self.assertEqual(g1(PERIOD).status, "FAIL")
        journal, _ = entry("g1-posted", legs=[leg("1121", debit=1), leg("3111", credit=1)])
        event.posted_entry_id = journal.pk
        event.posting_error = "synthetic unresolved"
        event.save(update_fields=["posted_entry_id", "posting_error"])
        self.assertEqual(g1(PERIOD).details["ops"], 1)

    def test_manual_null_link_and_error_both_fail(self):
        manual = AcctManualEntry.objects.create(event_type="period.accrued", occurred_at=NOW,
            period=PERIOD, currency="TWD", idempotency_key="g1-manual", basis="actual")
        self.assertEqual(g1(PERIOD).details["manual"], 1)
        journal, _ = entry("g1-manual-posted", legs=[leg("1121", debit=1), leg("3111", credit=1)])
        manual.posted_entry = journal
        manual.posting_error = "synthetic unresolved"
        manual.save(update_fields=["posted_entry", "posting_error"])
        self.assertEqual(g1(PERIOD).details["manual"], 1)


class G2Tests(TestCase):
    def setUp(self):
        self.old = datetime(2025, 3, 7, 12, tzinfo=dt_timezone.utc)
        self.assertEqual(business_days(self.old.date(), date(2025, 3, 31)), 16)
        _, lines = entry("g2-open", self.old, legs=[leg("1191", debit=100), leg("4111", credit=100)])
        self.open_line = lines[0]

    def add_settlement_source(self):
        journal, _ = entry("g2-settled", legs=[leg("1121", debit=50), leg("1191", credit=50)])
        LedgerEvent.objects.create(event_type="settlement.received", entity_table="ops.etsystatementrow",
            entity_id=1, occurred_at=NOW, idempotency_key="g2-source", posted_entry_id=journal.pk,
            source_filename="synthetic", dataset_kind="SAMPLE")

    def test_absent_source_is_not_runnable_even_when_aging_exists(self):
        result = g2(PERIOD)
        self.assertEqual(result.status, "NOT_RUNNABLE")
        self.assertEqual(result.details["aging"]["items"][0]["business_days"], 16)
        self.assertIn("NOT_RUNNABLE", settlement_aging_report(PERIOD).notes[0])

    def test_aged_unexplained_item_fails_and_named_cause_passes(self):
        self.add_settlement_source()
        self.assertEqual(g2(PERIOD).status, "FAIL")
        ClearingCause.objects.create(line=self.open_line, cause="settlement pending", evidence_ref="synthetic-evidence",
                                     recorded_by="tester")
        self.assertEqual(g2(PERIOD).status, "PASS")
        self.assertEqual(settlement_aging(PERIOD)["total_twd"], "50.0000")

    def test_one_twd_in_2205_fails_with_zero_tolerance(self):
        self.add_settlement_source()
        ClearingCause.objects.create(line=self.open_line, cause="settlement pending", evidence_ref="synthetic-evidence",
                                     recorded_by="tester")
        entry("g2-tax", legs=[leg("1121", debit=1), leg("2205", credit=1)])
        result = g2(PERIOD)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.details["account_2205_twd"], "1.0000")


class G3Tests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(sku="G3-SKU", name="Synthetic", uom="PK")
        opening_at = datetime(2025, 2, 28, 12, tzinfo=dt_timezone.utc)
        count, _ = entry("g3-count", opening_at, "2025-02", legs=[
            leg("1231", debit=50, sku="G3-SKU", qty=Decimal(5)), leg("3111", credit=50)])
        LedgerEvent.objects.create(event_type="inventory.opening_counted", entity_table="ops.product",
            entity_id=1, occurred_at=opening_at, payload={"counted_at":"2025-02-28","evidence_ref":"synthetic-count","lines":[{"sku":"G3-SKU","qty_packs":"5","agreed_unit_cost_twd":"10","line_value_twd":"50","condition":"sellable"}],"total_value_twd":"50"},
            idempotency_key="g3-count", posted_entry_id=count.pk,
            source_filename="synthetic", dataset_kind="SAMPLE")
        InventoryMove.objects.create(product=self.product, kind="opening", qty_delta_packs=5,
            value_delta_twd=Decimal(50), occurred_at=opening_at,
            idempotency_key="g3-open", source_filename="synthetic", dataset_kind="SAMPLE")
        receipt, _ = entry("g3-receipt", legs=[leg("1231", debit=30, sku="G3-SKU", qty=Decimal(3)),
                                             leg("2171", credit=30)])
        LedgerEvent.objects.create(event_type="po.received", entity_table="ops.product", entity_id=1,
            occurred_at=NOW, payload={"sku_receipts":[{"sku":"G3-SKU","qty_packs":3,"landed_cost_twd":"30"}]},
            idempotency_key="g3-receipt", posted_entry_id=receipt.pk,
            source_filename="synthetic", dataset_kind="SAMPLE")
        self.receipt_move = InventoryMove.objects.create(product=self.product, kind="received", qty_delta_packs=3,
            value_delta_twd=Decimal(30), occurred_at=NOW,
            idempotency_key="g3-received", source_filename="synthetic", dataset_kind="SAMPLE")
        entry("g3-sold", legs=[leg("5111", debit=10, sku="G3-SKU"),
                               leg("1231", credit=10, sku="G3-SKU", qty=Decimal(-1))])
        self.sale_move = InventoryMove.objects.create(product=self.product, kind="sold", qty_delta_packs=-1,
            value_delta_twd=Decimal(-10), occurred_at=NOW,
            idempotency_key="g3-sold", source_filename="synthetic", dataset_kind="SAMPLE")

    def test_positive_and_quantity_negative(self):
        self.assertEqual(g3(PERIOD).status, "PASS")
        self.sale_move.qty_delta_packs = -2
        self.sale_move.save(update_fields=["qty_delta_packs"])
        result = g3(PERIOD)
        self.assertEqual(result.status, "FAIL")
        self.assertNotEqual(result.details["rows"][0]["ops_packs"], result.details["rows"][0]["gl_packs"])

    def test_receipt_landed_cost_drift_fails_value_while_quantity_ties(self):
        self.receipt_move.value_delta_twd = Decimal(31)
        self.receipt_move.save(update_fields=["value_delta_twd"])
        result = g3(PERIOD)
        self.assertEqual(result.status, "FAIL")
        row = result.details["rows"][0]
        self.assertEqual(Decimal(row["ops_packs"]), Decimal(row["gl_packs"]))
        self.assertNotEqual(row["ops_twd"], row["gl_twd"])

    def test_without_opening_count_is_not_runnable(self):
        LedgerEvent.objects.filter(event_type="inventory.opening_counted").update(posted_entry_id=None)
        self.assertEqual(g3(PERIOD).status, "NOT_RUNNABLE")


class G4Tests(TestCase):
    entry = SyntheticContributionTests.entry

    def setUp(self):
        SyntheticContributionTests.setUp(self)

    def test_positive_and_header_double_count(self):
        self.assertEqual(g4(PERIOD).status, "PASS")
        from acct.reporting import contribution_skus, known
        actual_report = contribution_skus(PERIOD)
        row = actual_report.rows[0]
        row["contribution"] = known(row["contribution"].amount - Decimal(15), PERIOD, "SAMPLE")
        with patch("acct.gates.contribution_skus", return_value=actual_report):
            self.assertEqual(g4(PERIOD).status, "FAIL")

    def test_unit_count_allocation_fails_gross_share_check(self):
        from acct import reporting
        original = reporting._allocate

        def wrong_allocate(total, weighted_ids):
            return original(total, [(key, 1) for key, _ in weighted_ids])

        with patch("acct.reporting._allocate", side_effect=wrong_allocate):
            self.assertEqual(g4(PERIOD).status, "FAIL")


class G5Tests(TestCase):
    def test_positive_no_plugs(self):
        self.assertEqual(g5(PERIOD).status, "PASS")

    def test_suspense_account_fails(self):
        Account.objects.create(code="9998", name_en="Suspense", name_zh="測試", type="expense",
                               statement="PL", normal_balance="debit")
        self.assertEqual(g5(PERIOD).status, "FAIL")

    def test_rounding_difference_account_fails(self):
        Account.objects.create(code="9997", name_en="Rounding difference", name_zh="測試", type="expense",
                               statement="PL", normal_balance="debit")
        self.assertEqual(g5(PERIOD).status, "FAIL")

    def test_unreferenced_adjustment_line_fails(self):
        entry("g5-adjust", legs=[leg("1121", debit=1, memo="adjustment to balance", source=None),
                                  leg("3111", credit=1)])
        self.assertEqual(g5(PERIOD).status, "FAIL")

    def test_estimate_without_basis_fails(self):
        entry("g5-estimate", legs=[leg("6131", debit=1, memo="[ESTIMATE] freight"),
                                    leg("2191", credit=1)])
        self.assertEqual(g5(PERIOD).status, "FAIL")

    def test_open_freight_accrual_without_basis_fails(self):
        journal, _ = entry("g5-open-freight", legs=[leg("6131", debit=1), leg("2191", credit=1)])
        LedgerEvent.objects.create(event_type="order.ship_cost_accrued", entity_table="ops.order",
            entity_id=1, occurred_at=NOW, idempotency_key="g5-open-freight", posted_entry_id=journal.pk,
            source_filename="synthetic", dataset_kind="SAMPLE")
        self.assertEqual(g5(PERIOD).status, "FAIL")


class CloseAndReconciliationTests(TestCase):
    def test_reconciliation_reports_require_auth_and_export_sample_provenance(self):
        self.assertEqual(self.client.get(f"/reports/settlement-aging/?period={PERIOD}").status_code, 302)
        user = get_user_model().objects.create_user(username="synthetic-d-reporter", password="synthetic-pass")
        self.client.force_login(user)
        for slug in ("settlement-aging", "carrier-reconciliation"):
            with self.subTest(slug=slug):
                response = self.client.get(f"/reports/{slug}/?period={PERIOD}&format=csv")
                self.assertEqual(response.status_code, 200)
                self.assertIn("SAMPLE_", response["Content-Disposition"])
                self.assertTrue(response.content.decode().startswith("dataset_kind,SAMPLE,cost_basis,"))
                self.assertNotIn("Address", response.content.decode())

    def test_not_runnable_stops_close_and_period_stays_open(self):
        record_gate1(PERIOD, "synthetic-actor", "synthetic-input-review")
        run = run_close(PERIOD, "synthetic-actor")
        self.assertEqual(run.status, "BLOCKED")
        self.assertEqual([row["gate"] for row in run.gate_results], ["G-1", "G-2"])
        self.assertEqual(run.gate_results[-1]["status"], "NOT_RUNNABLE")
        self.assertEqual(Period.objects.get(pk=PERIOD).status, "OPEN")
        self.assertEqual(OpsPeriod.objects.get(pk=PERIOD).status, "OPEN")
        self.assertGreaterEqual(run.elapsed_seconds, 0)
        self.assertEqual(len(run.signature), 64)
        self.assertTrue(verify_close_signature(run))
        with self.assertRaises(DatabaseError), transaction.atomic():
            type(run).objects.filter(pk=run.pk).update(status="CLOSED")

    def test_failed_gate_stops_close(self):
        record_gate1(PERIOD, "synthetic-actor", "synthetic-input-review")
        LedgerEvent.objects.create(event_type="order.placed", entity_table="ops.order", entity_id=1,
            occurred_at=NOW, idempotency_key="close-unposted", source_filename="synthetic", dataset_kind="SAMPLE")
        run = run_close(PERIOD, "synthetic-actor")
        self.assertEqual(run.gate_results[0]["status"], "FAIL")
        self.assertEqual(len(run.gate_results), 1)
        self.assertEqual(Period.objects.get(pk=PERIOD).status, "OPEN")

    def test_passing_close_and_reopen_are_audited(self):
        record_gate1(PERIOD, "synthetic-actor", "synthetic-input-review")
        passes = tuple((lambda p, n=n: GateResult(f"G-{n}", "PASS", "synthetic pass", {})) for n in range(1, 6))
        with patch("acct.close.GATES", passes):
            run = run_close(PERIOD, "synthetic-actor")
        self.assertEqual(run.status, "CLOSED")
        self.assertEqual(Period.objects.get(pk=PERIOD).status, "CLOSED")
        audit = reopen_period(PERIOD, "synthetic-actor", "synthetic correction")
        self.assertEqual(audit.action, "REOPEN")
        self.assertEqual(audit.close_run_id, run.pk)
        self.assertEqual(Period.objects.get(pk=PERIOD).status, "OPEN")
        self.assertEqual(OpsPeriod.objects.get(pk=PERIOD).status, "OPEN")

    def test_carrier_open_accrual_is_estimate_with_basis(self):
        from ops.models import Channel, Order
        channel = Channel.objects.create(code="etsy", name="Etsy")
        order = Order.objects.create(channel=channel, channel_order_id="SYN-CARRIER",
            order_date=date(2025,3,1), currency="TWD", discount_funded_by="none",
            gross_minor=0, discount_minor=0, buyer_paid_minor=0, shipping_minor=0,
            shipping_discount_minor=0, dest_country="US", source_filename="synthetic", dataset_kind="SAMPLE")
        journal, _ = entry("carrier-accrual", legs=[leg("6131", debit=12,
            memo="[ESTIMATE] basis: carrier quote"), leg("2191", credit=12,
            memo="[ESTIMATE] basis: carrier quote")])
        LedgerEvent.objects.create(event_type="order.ship_cost_accrued", entity_table="ops.order",
            entity_id=order.pk, occurred_at=NOW, payload={"basis":"estimate","basis_note":"carrier quote"},
            idempotency_key="carrier-accrual", posted_entry_id=journal.pk,
            source_filename="synthetic", dataset_kind="SAMPLE")
        row = carrier_reconciliation(PERIOD).rows[0]
        self.assertIn("[ESTIMATE]", row["status"])
        self.assertIn("carrier quote", row["accrued"].display())
        self.assertEqual(g5(PERIOD).status, "PASS")
        invoice, _ = entry("carrier-invoice", legs=[leg("2191", debit=12), leg("2172", credit=12)])
        LedgerEvent.objects.create(event_type="order.ship_cost_invoiced", entity_table="ops.order",
            entity_id=order.pk, occurred_at=NOW, payload={"accrual_ref":"carrier-accrual"},
            idempotency_key="carrier-invoice", posted_entry_id=invoice.pk,
            source_filename="synthetic", dataset_kind="SAMPLE")
        report = carrier_reconciliation(PERIOD)
        row = report.rows[0]
        self.assertEqual(row["invoiced"].amount, Decimal(12))
        self.assertEqual(row["variance"].amount, Decimal(0))
        self.assertEqual(row["open"].amount, Decimal(0))
        self.assertEqual(report.rows[-1]["order"], "TOTAL")
