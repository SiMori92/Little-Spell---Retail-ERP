"""Execute frozen reference code against isolated synthetic fixtures in memory.

No project settings/.env, migrations, actual data, or source writes. Generic core
AppConfig omits PostgreSQL-only audit receivers; posting/report functions are
unchanged. This checks arithmetic/report behavior, not PostgreSQL triggers.
"""
import sys
sys.dont_write_bytecode = True
import csv
import importlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "app"))
from django.conf import settings
from django.apps import AppConfig
settings.configure(INSTALLED_APPS=[AppConfig("core", importlib.import_module("core")), "ops", "acct"],
 DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
 TIME_ZONE="Asia/Taipei", USE_TZ=True, DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
 SETTLEMENT_SPREAD_TOLERANCE_FRACTION=Decimal("0.10"), SECRET_KEY="synthetic")
import django
django.setup()
from django.apps import apps
from django.db import connection
with connection.schema_editor() as editor:
    for model in apps.get_models():
        if model._meta.managed:
            editor.create_model(model)
with connection.cursor() as cursor:
    cursor.execute("CREATE VIEW ops_onhand AS SELECT product_id AS sku, SUM(qty_delta_pieces) AS qty_pieces FROM ops_inventorymove GROUP BY product_id")
from acct.models import Account, JournalLine, JournalEntry, AcctManualEntry, FxRate
from core.models import DatasetSettings
from ops.models import Product, InventoryMove, LedgerEvent
from acct.posting import post_event
from acct.reporting import profit_loss, balance_sheet, inventory_roll_forward
from ops.file_intake import import_suppliers, import_products
from ops.receiving import import_grn, import_invoice
from ops.payments import import_supplier_payment
from ops.file_intake import import_po

chart=json.loads((ROOT / "seed/coa_snapshot.json").read_text())["rows"]+json.loads((ROOT / "seed/coa_addenda.json").read_text())["rows"]
for row in chart:
    Account.objects.create(code=row["account_code"], name_en=row["account_name_en"],name_zh=row["account_name_zh"],type=row["type"],statement=row["statement"],normal_balance=row["normal_balance"],tax_treatment=row["tax_treatment"],is_reserved=row["is_reserved"]=="true")
DatasetSettings.objects.create(id=1,dataset_kind="SAMPLE",business_tax_regime="unregistered")
g3=ROOT / "seed/samples/g3"
import_suppliers(g3 / "SAMPLE_suppliers_2026-09-27.csv",commit=True)
import_products(g3 / "SAMPLE_products_2026-09-27.csv",commit=True)
when=datetime(2026,1,1,12,tzinfo=ZoneInfo("Asia/Taipei"))
rows=[{"sku":p.sku,"qty_pieces":"0","agreed_unit_cost_twd":"0.0000","line_value_twd":"0.0000","condition":"sellable"} for p in Product.objects.order_by("sku")]
opening=LedgerEvent.objects.create(event_type="inventory.opening_counted",entity_table="ops.stockcount",entity_id=1,occurred_at=when,currency="TWD",payload={"counted_at":"2026-01-01","evidence_ref":"synthetic-parity-opening","lines":rows,"damaged_lines":[],"total_value_twd":"0.0000"},idempotency_key="opening-count|synthetic-parity",source_filename="synthetic-parity",dataset_kind="SAMPLE")
post_event(opening)
for row in rows:
    InventoryMove.objects.create(product_id=row["sku"],kind="opening",qty_delta_pieces=0,value_delta_twd=0,occurred_at=when,idempotency_key=f"synthetic-opening-{row['sku']}",source_filename="synthetic-parity",dataset_kind="SAMPLE")
import_po(g3 / "SAMPLE_po_PO-2026-002.csv",commit=True)
for fn,name in [(import_supplier_payment,"SAMPLE_pay_DEP-002.csv"),(import_grn,"SAMPLE_grn_PO-2026-002_R1.csv"),(import_invoice,"SAMPLE_inv_INV-A.csv"),(import_supplier_payment,"SAMPLE_pay_BAL-A.csv"),(import_grn,"SAMPLE_grn_PO-2026-002_R2.csv"),(import_invoice,"SAMPLE_inv_INV-B.csv"),(import_supplier_payment,"SAMPLE_pay_BAL-B.csv")]:
    fn(g3/name,commit=True)
for key,event_type,amount,payload,basis,professional in [
 ("funding","owner.funds_moved","200000.0000",{"funds_type":"capital"},"actual",False),
 ("accrual","period.accrued","1234.5678",{"expense_account":"6161","accrual_account":"2193","basis_note":"Synthetic prorated license"},"estimate",False),
 ("tax-assessment","tax.assessed","1250.0000",{},"actual",True),
 ("tax-payment","tax.paid","1000.0000",{},"actual",False),
]:
    entry=AcctManualEntry.objects.create(event_type=event_type,occurred_at=datetime(2026,10,2,12,tzinfo=ZoneInfo("Asia/Taipei")),period="2026-10",amount=amount,currency="TWD",payload=payload,basis=basis,evidence_ref=f"synthetic-parity-{key}",needs_prof_conf=professional,idempotency_key=f"synthetic-parity-{key}")
    post_event(entry)
def figures(report,key):
    return {row["account"].split(" ")[0]:str(row[key].amount) for row in report.rows if row["account"]!="ABSENT"}
trial={}
for line in JournalLine.objects.all():
    item=trial.setdefault(line.account_id,{"debit":Decimal(0),"credit":Decimal(0)})
    item["debit"]+=line.debit; item["credit"]+=line.credit
out={"scenario":"G3 lifecycle, complete zero opening and explicit synthetic manual vouchers","trialBalance":{key:{side:f"{value:.4f}" for side,value in item.items()} for key,item in sorted(trial.items())},"profitLoss":figures(profit_loss("2026-10"),"balance"),"balanceSheet":figures(balance_sheet("2026-10"),"balance"),"inventory":{row["sku"]:{"pieces":str(row["closing"].amount),"value":str(row["ops_value"].amount)} for row in inventory_roll_forward("2026-10").rows if row["sku"] not in ("ABSENT","TOTAL")}}
(ROOT / "docs/PARITY_REFERENCE_G3.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
print(json.dumps({"reference":"computed","scenario":out["scenario"],"journalEntries":JournalEntry.objects.count()}))

# Independently reproduce the frozen importer's order.placed envelope. Its
# current source sends parsed gross; placed() requires the seller-discount net.
from ops.etsy_import import _orders, ImportResult
from ops.models import Order, Channel
from acct.posting import placed, PostingError
with (ROOT / "seed/fixtures/SAMPLE_etsy_orderitems_2025-12_fixture.csv").open() as source:
    parsed=_orders(list(csv.DictReader(source)),{key:"seller" for key in ("WELCOME10","HOLIDAY15","FREESHIP")},ImportResult())
channel=Channel.objects.create(code="etsy",name="Etsy")
blockers=[]
for ref,row in parsed.items():
    order=Order.objects.create(channel=channel,channel_order_id=ref,order_date=row["date"].date(),currency=row["currency"],coupon_code=row["coupon"],discount_funded_by=row["funder"],gross_minor=row["gross"],discount_minor=row["discount"],buyer_paid_minor=row["buyer_paid"],shipping_minor=row["ship"],shipping_discount_minor=row["ship_discount"],tax_remitted_by_platform_minor=row["tax"],dest_country=row["country"],source_filename="synthetic-reference-probe",dataset_kind="SAMPLE")
    FxRate.objects.get_or_create(rate_date=row["date"].date(),currency="USD",kind="public",source_event_key="",defaults={"rate":"31.000000","rate_source":"manual","evidence_ref":"synthetic-public-rate"})
    event=LedgerEvent(event_type="order.placed",entity_table="ops.order",entity_id=order.pk,occurred_at=row["date"],amount_minor=row["gross"],currency="USD",payload={"discount_funded_by":row["funder"]})
    try:
        placed(event)
    except PostingError as error:
        blockers.append({"order":ref,"reference_error":str(error),"imported_minor":row["gross"],"expected_minor":row["gross"]-row["discount"] if row["funder"]=="seller" else row["gross"]})
(ROOT / "docs/PARITY_REFERENCE_ETSY_BLOCKERS.json").write_text(json.dumps({"scope":"Frozen importer envelope replayed through unmodified reference placed()","blockers":blockers,"full_etsy_tieout":"BLOCKED" if blockers else "NOT_RUN"},indent=2)+"\n")
print(json.dumps({"etsy_posting_blockers":len(blockers)}))
