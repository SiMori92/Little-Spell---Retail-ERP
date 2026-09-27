"""Record the business-tax regime (catalogue G.5.6). An input, never assumed."""

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import BUSINESS_TAX_REGIMES, DatasetSettings


class Command(BaseCommand):
    help = ("Set DatasetSettings.business_tax_regime. Only assessed or general lets supplier-invoice tax "
            "be creditable (1268). The answer is the 記帳士's (Message 3), not this system's.")

    def add_arguments(self, parser):
        parser.add_argument("regime", choices=BUSINESS_TAX_REGIMES)

    @transaction.atomic
    def handle(self, *args, **options):
        settings = DatasetSettings.objects.select_for_update().get(pk=1)
        old = settings.business_tax_regime
        settings.business_tax_regime = options["regime"]
        settings.save(update_fields=["business_tax_regime", "updated_at"])
        self.stdout.write(f"business_tax_regime: {old} -> {settings.business_tax_regime}")
