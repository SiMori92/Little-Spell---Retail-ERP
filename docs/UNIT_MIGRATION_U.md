# Slice U operator note — inventory is now pieces

Deploy Slice U only after resetting the SAMPLE database. The migration deliberately refuses a populated SAMPLE database when any SKU with `pieces_per_sale_unit != 1` has quantity-bearing rows; it also refuses every ACTUAL database. It never rewrites posted journal lines.

## Railway reset and deploy

1. In Railway, open the project and select the PostgreSQL service attached to this SAMPLE environment.
2. Confirm the application banner and `core_datasetsettings.dataset_kind` both say `SAMPLE`. If either says `ACTUAL`, stop: this migration is not permitted.
3. Use Railway's PostgreSQL data tab or shell to drop and recreate the SAMPLE database/schema using the project's normal reset procedure. This destroys SAMPLE rows, so take a backup first if the samples are needed for comparison. Do not run the reset against an ACTUAL service.
4. Deploy the Slice U revision. Railway's pre-deploy command runs `python manage.py migrate`; it must finish before the web service starts.
5. Re-import, in order:
   1. `docs/samples/SAMPLE_suppliers_2026-09-27.csv`
   2. `docs/samples/SAMPLE_products_2026-09-27.csv`
   3. any v2 opening count file (`qty_pieces`, with cost per piece)
   4. the Etsy sample order-items and statement pair
   5. `docs/samples/SAMPLE_ig_deals_2026-10.csv`
   6. any other SAMPLE receipts or later counts
6. Re-run posting and the close gates. Confirm the inventory roll-forward displays `pcs` and the contribution reports display `sale units`.

The v1 product, count, and Instagram headers are intentionally rejected. Do not rename a v1 column without converting count quantities and per-unit costs as required by Catalogue Addendum F.
