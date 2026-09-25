"""Recorded Gate 1, timed Gate 2 close, and audited reopen."""

import json

from django.core.management.base import BaseCommand, CommandError

from acct.close import record_gate1, reopen_period, run_close


class Command(BaseCommand):
    help = "Run one close step: gate1, close, or reopen. Requires a named actor."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("gate1", "close", "reopen"))
        parser.add_argument("period", help="YYYY-MM")
        parser.add_argument("--actor", required=True)
        parser.add_argument("--evidence-ref", default="", help="Gate 1 pre-close input-review evidence")
        parser.add_argument("--reason", default="", help="Required for reopen")

    def handle(self, *args, **options):
        try:
            if options["action"] == "gate1":
                result = record_gate1(options["period"], options["actor"], options["evidence_ref"])
                output = {"action": "gate1", "audit_id": result.pk, "recorded_at": result.recorded_at.isoformat()}
            elif options["action"] == "reopen":
                result = reopen_period(options["period"], options["actor"], options["reason"])
                output = {"action": "reopen", "audit_id": result.pk, "recorded_at": result.recorded_at.isoformat()}
            else:
                result = run_close(options["period"], options["actor"])
                output = {"action": "close", "run_id": result.pk, "status": result.status,
                          "elapsed_seconds": str(result.elapsed_seconds), "gate_results": result.gate_results,
                          "signature": result.signature}
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(output, ensure_ascii=False, default=str))
