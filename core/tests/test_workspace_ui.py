"""Workspace smoke tests use synthetic IDs and never print customer rows."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from acct.views import ALL_REPORT_BUILDERS


class WorkspaceUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="ui-reviewer", password="synthetic-test-password"
        )

    def test_public_overview_is_an_entry_point_without_internal_metrics(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in to workspace")
        self.assertNotContains(response, "Journal entries")

    def test_signed_in_overview_shows_scoped_counts_and_close_state(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Recorded activity")
        self.assertContains(response, "No close attempt recorded")
        self.assertContains(response, "SAMPLE DATA — NOT ACTUALS")

    def test_report_library_links_every_report_for_selected_period(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("report-index"), {"period": "2025-03"})
        self.assertEqual(response.status_code, 200)
        for slug in ALL_REPORT_BUILDERS:
            with self.subTest(slug=slug):
                self.assertContains(response, f"/reports/{slug}/?period=2025-03")

    def test_report_keeps_absent_reason_and_source_period_visible(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("report-detail", args=["contribution-orders"]),
            {"period": "2025-03"},
        )
        self.assertContains(response, "ABSENT")
        self.assertContains(response, 'data-source-period="2025-03"')
        self.assertContains(response, "Download CSV")
