from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AdminAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser(
            username="founder", email="founder@" + "example.com", password="slice-0-test-pw"
        )

    def test_admin_index_returns_200_for_logged_in_superuser(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)

    def test_admin_redirects_anonymous_user_to_login(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_health_endpoint_reports_ok(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
