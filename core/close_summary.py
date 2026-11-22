"""Presentation of a stored CloseRun: every gate, why it stopped, and the next valid step.

Pure functions over the run's stored JSON — no queries, no re-evaluation. The card shows what
the recorded attempt found; it never implies a gate passed that did not run.
"""

from django.urls import reverse

# Order matters: a close evaluates G-1..G-5 in sequence and stops at the first non-PASS.
GATES = (
    ("G-1", "Every fact is posted", "No unposted or errored events or manual entries before period end.",
     "Post or correct the unposted and errored facts, then rerun the close.", ()),
    ("G-2", "Settlement and deposits are explained", "Rail aging explained, 2205 exactly zero, supplier deposits cleared.",
     "Explain or clear the aged settlement items and open deposits, then rerun the close.",
     (("settlement-aging", "Settlement aging"), ("supplier-deposits", "Supplier deposits"))),
    ("G-3", "Inventory ties to the ledger", "SKU pieces and value match the GL with zero tolerance.",
     "Resolve the SKU differences between stock records and the GL, then rerun the close.",
     (("inventory", "Inventory roll-forward"),)),
    ("G-4", "Contribution ties to P&L", "Orders and SKU allocations reconcile to period P&L.",
     "Supply the missing contribution inputs or fix the allocation, then rerun the close.",
     (("contribution-orders", "Contribution by order"), ("profit-loss", "Profit and loss"))),
    ("G-5", "No plugs or unsupported estimates", "No suspense balances, unreferenced adjustments or estimates without basis.",
     "Clear the suspense or difference balances and document each estimate's basis, then rerun the close.",
     (("balance-sheet", "Balance sheet"),)),
)

PRECHECKS = {
    "Gate 1": ("WD+1 input review signed off",
               "Record the WD+1 pre-close input-review signoff, then rerun the close.",
               "close_period gate1 {period} --actor <name> --evidence-ref <reference>"),
    "Gate 2": ("WD+3 close window open",
               "The close cannot run before WD+3. Rerun it once that working day arrives.", ""),
}

LABELS = {"NOT_RUNNABLE": "NOT RUNNABLE"}


def _links(slugs, period):
    return [{"url": f"{reverse('report-detail', args=[slug])}?period={period}", "label": label}
            for slug, label in slugs]


def summarize(run):
    """Return the checklist for a CloseRun-like object (period, status, gate_results)."""
    if run is None:
        return None
    period = run.period
    recorded = {row.get("gate"): row for row in (run.gate_results or [])}
    precheck = next((row for name, row in recorded.items() if name in PRECHECKS), None)
    steps = []
    if precheck:
        title, recovery, command = PRECHECKS[precheck["gate"]]
        steps.append({"code": precheck["gate"], "title": title, "status": precheck["status"],
                      "label": LABELS.get(precheck["status"], precheck["status"]),
                      "reason": precheck.get("reason", ""), "recovery": recovery,
                      "command": command.format(period=period) if command else "", "links": []})
    for code, title, checks, recovery, slugs in GATES:
        row = recorded.get(code)
        if row is None:
            steps.append({"code": code, "title": title, "status": "NOT_RUN", "label": "NOT RUN",
                          "reason": checks, "recovery": "", "command": "", "links": []})
        else:
            steps.append({"code": code, "title": title, "status": row["status"],
                          "label": LABELS.get(row["status"], row["status"]), "reason": row.get("reason", ""),
                          "recovery": recovery if row["status"] != "PASS" else "", "command": "",
                          "links": _links(slugs, period) if row["status"] != "PASS" else []})
    blocker = next((step for step in steps if step["status"] not in ("PASS", "NOT_RUN")), None)
    if blocker and not blocker["command"]:
        blocker["command"] = f"close_period close {period} --actor <name>"
    passed = sum(step["status"] == "PASS" for step in steps if step["code"].startswith("G-"))
    return {"steps": steps, "blocker": blocker, "passed": passed, "total": len(GATES),
            "closed": run.status == "CLOSED" and passed == len(GATES)}
