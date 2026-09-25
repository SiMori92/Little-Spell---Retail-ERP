"""Timed, signed close attempts and single-step audited period reopen."""

import json
import hmac
from datetime import timedelta
from decimal import Decimal
from time import perf_counter

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from acct.gates import GATES, GateResult
from acct.models import CloseAudit, CloseRun, JournalEntry, Period
from acct.reporting import dataset_kind, period_bounds
from ops.models import OpsPeriod


def workday_after(day, number):
    cursor = day
    passed = 0
    while passed < number:
        cursor += timedelta(days=1)
        passed += cursor.weekday() < 5
    return cursor


@transaction.atomic
def record_gate1(period, actor, evidence_ref):
    """Record pre-posting input-review signoff; never claim the P-suite is automated here."""
    _, end = period_bounds(period)
    if not actor.strip() or not evidence_ref.strip():
        raise ValueError("Gate 1 needs an actor and pre-close evidence reference")
    if timezone.localdate() < workday_after(end.date() - timedelta(days=1), 1):
        raise ValueError("Gate 1 is scheduled at WD+1")
    if JournalEntry.objects.filter(period=period).exists():
        raise ValueError("Gate 1 must be recorded before any journal entry in the period")
    if CloseAudit.objects.filter(period=period, action="GATE1").exists():
        raise ValueError("Gate 1 already recorded")
    return CloseAudit.objects.create(period=period, action="GATE1", actor=actor,
                                     reason=f"WD+1 pre-close input review evidence: {evidence_ref}")


def _signature(payload):
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return salted_hmac("acct.close.v1", serialized, algorithm="sha256").hexdigest()


def verify_close_signature(run):
    payload = {field: getattr(run, field) for field in (
        "period", "dataset_kind", "runner", "started_at", "finished_at", "elapsed_seconds",
        "status", "gate_results", "remaining_open")}
    return hmac.compare_digest(run.signature, _signature(payload))


@transaction.atomic
def run_close(period, runner):
    start, end = period_bounds(period)
    if not runner or not runner.strip():
        raise ValueError("close runner is required")
    begun = timezone.now()
    tick = perf_counter()
    lock, _ = Period.objects.select_for_update().get_or_create(period=period)
    ops_lock, _ = OpsPeriod.objects.select_for_update().get_or_create(period=period)
    if lock.status == "CLOSED" or ops_lock.status == "CLOSED":
        raise ValueError("period is already closed; reopen must be audited first")
    results = []
    gate1 = CloseAudit.objects.filter(period=period, action="GATE1").first()
    if gate1 is None:
        results.append(GateResult("Gate 1", "NOT_RUNNABLE", "WD+1 pre-close review has no recorded signoff", {}).record())
    elif timezone.localdate() < workday_after(end.date() - timedelta(days=1), 3):
        results.append(GateResult("Gate 2", "NOT_RUNNABLE", "WD+3 close gate is not due", {}).record())
    else:
        for gate in GATES:
            result = gate(period)
            results.append(result.record())
            if result.status != "PASS":
                break
    passed = len(results) == 5 and all(row["status"] == "PASS" for row in results)
    finished = timezone.now()
    elapsed = Decimal(str(perf_counter() - tick)).quantize(Decimal("0.0001"))
    remaining = [] if passed else [f"{row['gate']}: {row['reason']}" for row in results if row["status"] != "PASS"]
    if not passed:
        executed = len(results) if results[-1]["gate"].startswith("G-") else 0
        remaining += [f"G-{index} not run after {results[-1]['gate']}" for index in range(executed + 1, 6)]
    payload = {"period": period, "dataset_kind": dataset_kind(), "runner": runner,
               "started_at": begun, "finished_at": finished,
               "elapsed_seconds": elapsed, "status": "CLOSED" if passed else "BLOCKED",
               "gate_results": results, "remaining_open": remaining}
    run = CloseRun.objects.create(**payload, signature=_signature(payload))
    if passed:
        lock.status = "CLOSED"
        ops_lock.status = "CLOSED"
        lock.save(update_fields=["status"])
        ops_lock.save(update_fields=["status"])
        CloseAudit.objects.create(period=period, action="CLOSE", actor=runner, close_run=run,
                                  reason="G-1 through G-5 passed in order")
    return run


@transaction.atomic
def reopen_period(period, actor, reason):
    period_bounds(period)
    if not actor or not actor.strip() or not reason or not reason.strip():
        raise ValueError("reopen needs named actor and reason")
    lock = Period.objects.select_for_update().get(pk=period)
    ops_lock = OpsPeriod.objects.select_for_update().get(pk=period)
    if lock.status != "CLOSED" or ops_lock.status != "CLOSED":
        raise ValueError("both accounting and ops periods must be CLOSED to reopen")
    run = CloseRun.objects.filter(period=period, status="CLOSED").order_by("-id").first()
    lock.status = "OPEN"
    ops_lock.status = "OPEN"
    lock.save(update_fields=["status"])
    ops_lock.save(update_fields=["status"])
    return CloseAudit.objects.create(period=period, action="REOPEN", actor=actor,
                                     reason=reason, close_run=run)
