"""Load the combined Run A + Run B SAMPLE pack in dependency order."""

from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import DatasetKind, DatasetSettings

PACK = Path(__file__).resolve().parents[3] / "docs" / "samples" / "uat"
STEPS = (
    ("suppliers", "import_suppliers", "SAMPLE_suppliers_2026-09-27.csv"),
    ("products", "import_products", "SAMPLE_products_2026-09-27.csv"),
    ("PO-001 draft", "import_po", "SAMPLE_po_PO-2026-001.csv"),
    ("PO-002 sent", "import_po", "SAMPLE_po_PO-2026-002.csv"),
    ("PO-003 sent", "import_po", "SAMPLE_po_PO-2026-003.csv"),
    ("PO-004 sent", "import_po", "SAMPLE_po_PO-2026-004.csv"),
    ("PO-002 deposit", "import_supplier_payment", "SAMPLE_pay_DEP-002.csv"),
    ("PO-002 receipt R1", "import_grn", "SAMPLE_grn_PO-2026-002_R1.csv"),
    ("PO-002 invoice A", "import_supplier_invoice", "SAMPLE_inv_INV-A.csv"),
    ("PO-002 receipt R2", "import_grn", "SAMPLE_grn_PO-2026-002_R2.csv"),
    ("PO-002 invoice B", "import_supplier_invoice", "SAMPLE_inv_INV-B.csv"),
    ("PO-002 balance A", "import_supplier_payment", "SAMPLE_pay_BAL-A.csv"),
    ("PO-002 balance B", "import_supplier_payment", "SAMPLE_pay_BAL-B.csv"),
    ("PO-003 receipt", "import_grn", "SAMPLE_grn_PO-2026-003_R1.csv"),
    ("PO-003 invoice", "import_supplier_invoice", "SAMPLE_inv_EP-2026-0129.csv"),
    ("PO-004 receipt", "import_grn", "SAMPLE_grn_PO-2026-004_R1.csv"),
    ("Instagram deals", "import_ig_deals", "SAMPLE_ig_deals_2026-10.csv"),
)


class Command(BaseCommand):
    help = "Validate or commit the combined UAT SAMPLE pack in dependency order."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        if DatasetSettings.load().dataset_kind != DatasetKind.SAMPLE:
            raise CommandError("load_uat_sample is restricted to SAMPLE mode")
        commit = options["commit"]
        with transaction.atomic():
            for label, command, filename in STEPS:
                output = StringIO()
                try:
                    call_command(command, file=PACK / filename, commit=True, stdout=output)
                except CommandError as exc:
                    raise CommandError(f"{label}: {exc}") from exc
                rendered = output.getvalue().strip().replace("\n", " | ")
                self.stdout.write(f"{label}: {rendered}")
            if not commit:
                transaction.set_rollback(True)
                self.stdout.write("Validation complete; transaction rolled back (use --commit to persist).")
            else:
                self.stdout.write("Combined UAT SAMPLE pack committed.")
