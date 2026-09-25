"""Exercise the committed hook in an isolated repository inside app/tests/."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]


class PreCommitHookTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix=".hook-test-", dir=APP_ROOT / "tests")
        self.repo = Path(self.sandbox.name)
        (self.repo / ".githooks").mkdir()
        (self.repo / "tools").mkdir()
        shutil.copy2(APP_ROOT / ".githooks" / "pre-commit", self.repo / ".githooks")
        shutil.copy2(APP_ROOT / "tools" / "repo_guard.py", self.repo / "tools")
        self.git("init", "-q")
        self.git("config", "user.name", "Guard Test")
        self.git("config", "user.email", "guard@" + "example.test")
        self.git("config", "core.hooksPath", ".githooks")

    def tearDown(self):
        self.sandbox.cleanup()

    def git(self, *args, env=None):
        return subprocess.run(
            ["git", *args], cwd=self.repo, capture_output=True, text=True,
            env=env, check=False,
        )

    def stage(self, relative: str, content: str):
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        result = self.git("add", "-f", "--", relative)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_customers_csv_is_rejected_before_a_commit_exists(self):
        self.stage("customers.csv", "id,name\n1,Example\n")
        result = self.git("commit", "-m", "must fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sensitive-path", result.stderr)
        self.assertIn("customers.csv", result.stderr)
        self.assertNotEqual(self.git("rev-parse", "--verify", "HEAD").returncode, 0)

    def test_named_fixture_is_allowed(self):
        self.stage("tests/fixtures/etsy_headers_fixture.csv", "order_id,sku\n")
        result = self.git("commit", "-m", "fixture")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("rev-parse", "--verify", "HEAD").returncode, 0)

    def test_concept_named_migration_is_allowed(self):
        self.stage("acct/migrations/0002_settlements.py", "# schema migration\n")
        result = self.git("commit", "-m", "migration")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_env_example_is_allowed(self):
        self.stage(".env.example", "DJANGO_DEBUG=0\n")
        result = self.git("commit", "-m", "example")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_python_cache_is_rejected(self):
        path = "module/__pycache__/thing.cpython-312.pyc"
        self.stage(path, "fake bytecode")
        result = self.git("commit", "-m", "must fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python-cache", result.stderr)
        self.assertIn(path, result.stderr)

    def test_email_in_staged_source_is_rejected_without_echoing_value(self):
        address = "person@" + "example.test"
        self.stage("settings.py", f'EMAIL = "{address}"\n')
        result = self.git("commit", "-m", "must fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("email-content", result.stderr)
        self.assertIn("settings.py", result.stderr)
        self.assertNotIn(address, result.stderr)

    def test_street_address_in_staged_json_is_rejected(self):
        digits = "".join(("1", "2", "3"))
        self.stage("payload.json", json.dumps({"address": digits + " Road"}))
        result = self.git("commit", "-m", "must fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("address-content", result.stderr)
        self.assertIn("payload.json", result.stderr)

    def test_escape_hatch_names_the_file_and_rule(self):
        self.stage("customers.csv", "id,name\n1,Example\n")
        env = os.environ.copy()
        env["ALLOW_DATA_COMMIT"] = "1"
        result = self.git("commit", "-m", "deliberate override", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WARNING", result.stderr)
        self.assertIn("sensitive-path", result.stderr)
        self.assertIn("customers.csv", result.stderr)


if __name__ == "__main__":
    unittest.main()
