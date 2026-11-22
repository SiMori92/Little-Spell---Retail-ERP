"""Presentation checks with synthetic figures; never connect to the ledger DB."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse

from acct.reporting import Column, Figure, Report, ReportSection
from acct.views import REPORT_GROUPS, report_detail, report_index

@override_settings(
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
    SECURE_SSL_REDIRECT=False,
)
class UITestBase(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        # Patch the settings read, not the processor: the template engine caches processor functions.
        patcher = patch("core.context_processors.DatasetSettings.load",
                        return_value=SimpleNamespace(dataset_kind="SAMPLE"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, path, authenticated=True):
        request = self.factory.get(path)
        request.resolver_match = resolve(request.path)
        request.user = SimpleNamespace(
            is_authenticated=authenticated, is_staff=False,
            get_username=lambda: "Synthetic reviewer",
        )
        return request



@override_settings(
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
    SECURE_SSL_REDIRECT=False,
)
class HandbookUITests(UITestBase):
    def test_public_and_signed_in_overview_keep_one_heading_and_quarantine(self):
        for authenticated in [False, True]:
            with self.subTest(authenticated=authenticated):
                html = render_to_string("home.html", {
                    "period": "2025-03", "recorded_orders": 0,
                    "operational_events": 0, "inventory_moves": 0,
                    "journal_entries": 0, "latest_close": None,
                }, request=self.request("/", authenticated))
                self.assertEqual(html.count("<h1>"), 1)
                self.assertIn('id="dataset-banner"', html)
                self.assertIn("SAMPLE DATA — NOT ACTUALS", html)
                self.assertIn('data-artwork-header', html)
                self.assertIn('aria-label="Reports"', html)
                if authenticated:
                    self.assertIn("Record counts, not business totals", html)
                    self.assertIn("No close attempt recorded", html)
                else:
                    self.assertIn("Sign in to workspace", html)
                    self.assertNotIn("Journal entries", html)

    def test_report_library_keeps_every_link_and_period(self):
        response = report_index(self.request("/reports/?period=2025-03"))
        self.assertEqual(response.status_code, 200)
        for group in REPORT_GROUPS:
            for slug, title, description in group["items"]:
                self.assertContains(response, f"/reports/{slug}/?period=2025-03")
        self.assertContains(response, 'data-library-search hidden')
        self.assertContains(response, 'aria-live="polite"')

    def test_detail_keeps_missing_provisional_zero_and_export_provenance(self):
        report = Report("synthetic-ui", "Synthetic UI report", "2025-03", "SAMPLE",
            (Column("reference", "Reference", False), Column("amount", "Amount")), [
                {"reference": "Missing cost", "amount": Figure(None, "SAMPLE", "absent", "2025-03", "Invoice not recorded")},
                {"reference": "Estimated cost", "amount": Figure(Decimal("12"), "SAMPLE", "provisional", "2025-03", "Estimate from quote", True)},
                {"reference": "Counted zero", "amount": Figure(Decimal("0"), "SAMPLE", "actual", "2025-03")},
            ])
        with patch.dict("acct.views.ALL_REPORT_BUILDERS", {"synthetic-ui": lambda period: report}):
            response = report_detail(self.request("/reports/synthetic-ui/?period=2025-03"), "synthetic-ui")
            self.assertContains(response, "ABSENT")
            self.assertContains(response, "Invoice not recorded")
            self.assertContains(response, "PROVISIONAL COST BASIS — NOT ACTUAL [ESTIMATE]")
            self.assertContains(response, "NT$0.00")
            self.assertContains(response, 'data-source-period="2025-03"')
            self.assertContains(response, 'data-dataset-kind="SAMPLE"')
            self.assertContains(response, '?period=2025-03&amp;format=csv')
            self.assertContains(response, 'page-heading-compact')
            self.assertNotContains(response, 'data-artwork-header')  # no hidden art advancing the bag
            csv_response = report_detail(self.request("/reports/synthetic-ui/?period=2025-03&format=csv"), "synthetic-ui")
            self.assertEqual(csv_response["Content-Type"], "text/csv; charset=utf-8")
            self.assertIn("SAMPLE_synthetic-ui", csv_response["Content-Disposition"])
            self.assertContains(csv_response, "Invoice not recorded")

    def test_empty_report_has_an_explicit_nonzero_claim(self):
        report = Report("synthetic-ui", "Empty report", "2025-03", "SAMPLE", (), [])
        with patch.dict("acct.views.ALL_REPORT_BUILDERS", {"synthetic-ui": lambda period: report}):
            response = report_detail(self.request("/reports/synthetic-ui/?period=2025-03"), "synthetic-ui")
        self.assertContains(response, 'data-empty-row')
        self.assertContains(response, "This does not establish a zero balance.")

    def test_every_painting_has_local_image_and_attribution(self):
        html = render_to_string("includes/artwork.html")
        for image in (settings.BASE_DIR / "static/art").glob("*.jpg"):
            self.assertIn(image.name, html)
            self.assertEqual(image.read_bytes()[:3], b"\xff\xd8\xff")
        self.assertEqual(len(list((settings.BASE_DIR / "static/art").glob("*.jpg"))), 4)
        self.assertEqual(html.count('data-source="https://artsandculture.google.com/asset/'), 4)
        self.assertTrue(Path(settings.BASE_DIR / "static/art/README.md").exists())


@override_settings(
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
    SECURE_SSL_REDIRECT=False,
)
class SharedComponentTests(UITestBase):
    """Phase 2: one implementation per component, with distinct labelled states."""

    def render(self, template, **context):
        return render_to_string(template, context)

    def test_status_badge_tones_follow_meaning_and_always_carry_text(self):
        cases = {"CLOSED": "status-good", "PASS": "status-good", "BLOCKED": "status-danger",
                 "FAIL": "status-danger", "NOT_RUNNABLE": "status-warn", "RUNNING": "status-neutral"}
        for status, tone in cases.items():
            with self.subTest(status=status):
                html = self.render("includes/status_badge.html", status=status)
                self.assertIn(tone, html)
                self.assertIn(f">{status}<", html)
        self.assertIn("status-warn", self.render("includes/status_badge.html", status="X", tone="warn", label="Review"))

    def test_notice_tones_and_danger_is_announced(self):
        for tone in ["info", "success", "warning", "danger"]:
            with self.subTest(tone=tone):
                html = self.render("includes/notice.html", tone=tone, title="T", body="B")
                self.assertIn(f"notice-{tone}", html)
                self.assertIn('role="alert"' if tone == "danger" else 'role="note"', html)
        self.assertIn("notice-info", self.render("includes/notice.html", title="Default"))

    def test_blocked_close_is_a_danger_badge_on_overview(self):
        html = render_to_string("home.html", {
            "period": "2025-03", "recorded_orders": 1, "operational_events": 1,
            "inventory_moves": 0, "journal_entries": 1,
            "latest_close": SimpleNamespace(status="BLOCKED", period="2025-02", runner="r", elapsed_seconds=1),
            "close_summary": None,
        }, request=self.request("/"))
        self.assertIn('status-danger">BLOCKED<', html)

    def test_absent_label_is_not_repeated_and_sections_share_the_table(self):
        absent = Figure(None, "SAMPLE", "absent", "2025-03", "Invoice not recorded")
        report = Report("synthetic-ui", "Sectioned", "2025-03", "SAMPLE", (), [], sections=(
            ReportSection("First", (Column("ref", "Ref", False), Column("amt", "Amount")), [{"ref": "A", "amt": absent}]),
            ReportSection("Second", (Column("ref", "Ref", False), Column("amt", "Amount")), []),
        ))
        with patch.dict("acct.views.ALL_REPORT_BUILDERS", {"synthetic-ui": lambda period: report}):
            html = report_detail(self.request("/reports/synthetic-ui/?period=2025-03"), "synthetic-ui").content.decode()
        self.assertNotIn('<span class="cell-basis">ABSENT</span>', html)
        self.assertIn('<span class="figure-value">ABSENT</span>', html)
        self.assertIn("Invoice not recorded", html)
        self.assertEqual(html.count("data-report-body"), 2)
        self.assertIn("data-table-search", html)
        self.assertIn("This does not establish a zero balance.", html)

    def test_invalid_period_is_a_400_page_with_reason_and_recovery(self):
        for view, args in [(report_index, ()), (report_detail, ("contribution-orders",))]:
            with self.subTest(view=view.__name__):
                path = "/reports/" + (f"{args[0]}/" if args else "") + "?period=2025-13"
                response = view(self.request(path), *args)
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, "month must be 01–12", status_code=400)
                self.assertContains(response, "Choose another month", status_code=400)
                self.assertContains(response, 'id="dataset-banner"', status_code=400)

    def test_error_pages_render_without_database(self):
        html404 = render_to_string("404.html", request=self.request("/"))
        self.assertIn("This page does not exist", html404)
        self.assertIn('id="dataset-banner"', html404)
        html500 = render_to_string("500.html")
        self.assertIn("Do not assume any figure", html500)
        self.assertNotIn("{%", html500)


def _run(status, results, period="2025-11"):
    from datetime import datetime, timezone as tz
    return SimpleNamespace(period=period, status=status, gate_results=results, runner="agent-2",
                           finished_at=datetime(2025, 12, 4, 2, 0, tzinfo=tz.utc), elapsed_seconds=Decimal("0.0096"))


PASS = lambda code: {"gate": code, "status": "PASS", "reason": f"{code} ok", "details": {}}


@override_settings(
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
    SECURE_SSL_REDIRECT=False,
)
class CloseCardTests(UITestBase):
    """Phase 3: the overview shows every gate, the blocker and the next valid step."""

    def home(self, run, reopened=False):
        from core.close_summary import summarize
        return render_to_string("home.html", {
            "period": "2025-12", "recorded_orders": 1, "operational_events": 1, "inventory_moves": 0,
            "journal_entries": 1, "latest_close": run, "close_summary": summarize(run),
            "close_reopened": reopened,
        }, request=self.request("/"))

    def test_gate1_precheck_blocks_and_names_the_signoff_command(self):
        run = _run("BLOCKED", [{"gate": "Gate 1", "status": "NOT_RUNNABLE",
                                "reason": "WD+1 pre-close review has no recorded signoff", "details": {}}])
        html = self.home(run)
        self.assertIn("Period stays open — stopped at Gate 1", html)
        self.assertIn("close_period gate1 2025-11 --actor &lt;name&gt; --evidence-ref &lt;reference&gt;", html)
        self.assertEqual(html.count('status-neutral">NOT RUN<'), 5)
        self.assertIn("<strong>0 of 5</strong> gates passed", html)
        self.assertIn("NOT RUN is not a pass.", html)
        self.assertIn('status-danger">BLOCKED<', html)

    def test_failed_gate_links_investigation_reports_for_its_period(self):
        run = _run("BLOCKED", [PASS("G-1"), PASS("G-2"), {"gate": "G-3", "status": "FAIL",
                   "reason": "quantity or value differs from GL with zero tolerance", "details": {"rows": ["secret"]}}])
        html = self.home(run)
        self.assertIn("stopped at G-3", html)
        self.assertIn("/reports/inventory/?period=2025-11", html)
        self.assertIn("close_period close 2025-11 --actor &lt;name&gt;", html)
        self.assertIn("<strong>2 of 5</strong> gates passed", html)
        self.assertEqual(html.count('status-neutral">NOT RUN<'), 2)
        self.assertNotIn("secret", html)  # gate details are never dumped onto the overview

    def test_not_runnable_gate_is_amber_not_red_and_still_blocks(self):
        run = _run("BLOCKED", [PASS("G-1"), {"gate": "G-2", "status": "NOT_RUNNABLE", "reason": "Q-1 OPEN", "details": {}}])
        html = self.home(run)
        self.assertIn('status-warn">NOT RUNNABLE<', html)
        self.assertIn("stopped at G-2", html)

    def test_clean_close_and_later_reopen_are_distinct(self):
        run = _run("CLOSED", [PASS(f"G-{i}") for i in range(1, 6)])
        closed = self.home(run)
        self.assertIn("Period closed", closed)
        self.assertIn("<strong>5 of 5</strong>", closed)
        self.assertNotIn("Period stays open", closed)
        reopened = self.home(run, reopened=True)
        self.assertIn('status-warn">REOPENED<', reopened)
        self.assertIn("Reopened after this close", reopened)
        self.assertNotIn("Period closed", reopened)

    def test_no_run_keeps_the_empty_state(self):
        self.assertIn("No close attempt recorded", self.home(None))


class AdminComponentTests(TestCase):
    """Phase 4: the read-only ops console uses the same labelled badges and honest empty states."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from acct.models import Period
        cls.user = get_user_model().objects.create_superuser("ui-admin", "ui-admin@" + "example.invalid", "synthetic-pw")
        Period.objects.create(period="2025-11", status="CLOSED")
        Period.objects.create(period="2025-12", status="OPEN")

    def setUp(self):
        self.client.force_login(self.user)

    def test_status_column_is_a_labelled_badge(self):
        response = self.client.get(reverse("admin:acct_period_changelist"))
        self.assertContains(response, '<span class="status-badge status-good">CLOSED</span>', html=True)
        self.assertContains(response, '<span class="status-badge status-active">OPEN</span>', html=True)
        self.assertContains(response, 'id="dataset-banner"')

    def test_empty_changelist_does_not_claim_nothing_happened(self):
        response = self.client.get(reverse("admin:acct_closerun_changelist"))
        self.assertContains(response, "recorded in this dataset")
        self.assertContains(response, "does not prove the business had none")

    def test_read_only_record_says_so_but_editable_forms_do_not(self):
        response = self.client.get(reverse("admin:acct_period_change", args=["2025-11"]))
        self.assertContains(response, "Read-only record")
        response = self.client.get(reverse("admin:auth_user_change", args=[self.user.pk]))
        self.assertNotContains(response, "Read-only record")

    def test_badge_tones_never_promote_a_pipeline_stage_to_success(self):
        from core.admin_ui import ORDER_TONES, badge
        from ops.admin import IgDealAdmin
        self.assertIn("status-neutral", badge("paid", IgDealAdmin.status_tones))
        self.assertIn("status-active", badge("shipped", ORDER_TONES))
        self.assertIsNone(badge("", ORDER_TONES))
