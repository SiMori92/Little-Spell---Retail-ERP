"""Seed quarantine — DATA_REVIEW addendum §A1.3.

"Not a convention, a code path. A number without that banner is a number someone
will act on."

These tests are the thing that makes it a control. Delete the banner from
templates/includes/dataset_banner.html, or from the admin override, or drop the
context processor from settings, and every test in the first class below fails.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core.context_processors import BANNER_TEXT
from core.models import DatasetKind, DatasetSettings

REQUIRED_BANNER = "SAMPLE DATA — NOT ACTUALS"


class SampleBannerRendersWhileSampleTests(TestCase):
    """Every one of these FAILS if the banner is absent while dataset_kind = SAMPLE."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser(
            username="founder", email="founder@example.com", password="slice-0-test-pw"
        )

    def setUp(self):
        settings_row = DatasetSettings.load()
        settings_row.dataset_kind = DatasetKind.SAMPLE
        settings_row.save()

    def assert_banner_present(self, response):
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn(
            REQUIRED_BANNER,
            body,
            msg=f"The {REQUIRED_BANNER!r} banner is missing while dataset_kind = SAMPLE.",
        )
        self.assertIn('id="dataset-banner"', body)

    def test_banner_text_constant_is_exactly_the_required_wording(self):
        self.assertEqual(BANNER_TEXT, REQUIRED_BANNER)

    def test_banner_renders_on_the_public_landing_page(self):
        self.assert_banner_present(self.client.get("/"))

    def test_banner_renders_on_the_admin_login_page(self):
        self.assert_banner_present(self.client.get(reverse("admin:login")))

    def test_banner_renders_on_the_admin_index(self):
        self.client.force_login(self.superuser)
        self.assert_banner_present(self.client.get(reverse("admin:index")))

    def test_banner_renders_on_an_admin_changelist(self):
        self.client.force_login(self.superuser)
        self.assert_banner_present(
            self.client.get(reverse("admin:core_auditlogentry_changelist"))
        )

    def test_banner_renders_on_an_unrelated_admin_app_page(self):
        """A banner that only covers `core`'s own pages is not "every page"."""
        self.client.force_login(self.superuser)
        self.assert_banner_present(
            self.client.get(reverse("admin:auth_user_changelist"))
        )


class BannerIsDrivenByTheFlagTests(TestCase):
    def test_banner_absent_once_dataset_kind_is_actual(self):
        settings_row = DatasetSettings.load()
        settings_row.dataset_kind = DatasetKind.ACTUAL
        settings_row.save()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(REQUIRED_BANNER, response.content.decode())


class QuarantineDefaultsTests(TestCase):
    def test_singleton_exists_and_defaults_to_sample(self):
        """Created by migration 0004, so a fresh database is quarantined from birth."""
        self.assertEqual(DatasetSettings.objects.count(), 1)
        self.assertEqual(DatasetSettings.objects.get(pk=1).dataset_kind, DatasetKind.SAMPLE)

    def test_a_missing_settings_row_fails_safe_to_sample(self):
        """Hiding the banner wrongly is the whole risk; showing it wrongly costs nothing."""
        DatasetSettings.objects.all().delete()
        response = self.client.get("/")
        self.assertIn(REQUIRED_BANNER, response.content.decode())

    def test_a_second_settings_row_is_refused_by_the_database(self):
        """Singleton, enforced in Postgres.

        Two settings rows would mean two answers to "is this sample data", and the
        banner would then depend on which one happened to be read first.
        """
        with self.assertRaises(IntegrityError), transaction.atomic():
            DatasetSettings.objects.create(dataset_kind=DatasetKind.ACTUAL)
        self.assertEqual(DatasetSettings.objects.count(), 1)

    def test_saving_with_a_different_id_is_rewritten_to_row_1(self):
        """Proof that `save()` rewrites the id rather than honouring it.

        Were id=99 respected, this INSERT would succeed and there would be two
        settings rows. It collides on the pk instead, which can only happen if the
        id was rewritten to 1 on the way in.
        """
        row = DatasetSettings(id=99, dataset_kind=DatasetKind.ACTUAL)
        with self.assertRaises(IntegrityError), transaction.atomic():
            row.save()
        self.assertEqual(row.pk, 1)
        self.assertEqual(DatasetSettings.objects.count(), 1)
        self.assertEqual(DatasetSettings.objects.get(pk=1).dataset_kind, DatasetKind.SAMPLE)

    def test_updating_the_loaded_singleton_works(self):
        row = DatasetSettings.load()
        row.dataset_kind = DatasetKind.ACTUAL
        row.save()
        self.assertEqual(DatasetSettings.objects.count(), 1)
        self.assertEqual(DatasetSettings.load().dataset_kind, DatasetKind.ACTUAL)
