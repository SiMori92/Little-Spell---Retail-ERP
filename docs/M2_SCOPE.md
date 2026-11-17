# M2 scope contract

The existing PARITY inventory remains binding. M2 targets Order, OrderLine, Shipment, EtsyStatementPeriod, EtsyStatementRow, IgDeal, IgDealStatus, the Etsy pair importer and IG v2 importer/command replacements, plus guided forms, tables/kanban, immutable lifecycle histories, previews, and dispatch effects. Shared mixed modules remain deferred until all their behavior is ported.

Preserve exact headers, multiset statement identity, coupon-funder evidence, sale-unit/piece conversion, monotonic Instagram states, paid-state immutability, period admission on every effective date, and dataset isolation. Buyer columns are discarded before a request crosses the persistence boundary; no customer data or source attachment containing it is retained. No notification is sent.

Source constraints: Etsy headers are explicitly unverified and require an evidenced founder verification before committing imports. ACTUAL paid Instagram states stay blocked by H-0b. Source importers emit events separately from accounting posting; M4 retains the posting UI, FX masters, and journals. M2 provides tested placement/dispatch posting functions without silently posting an import. Shipments may consume only existing counted sellable pieces; M1 preparations are not stock. Financial fixture materialization and tie-out remain M3–M5, never a zero-by-default result.
