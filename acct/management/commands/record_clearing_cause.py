"""Attach a named, sourced cause to a clearing item without editing the journal."""

from django.core.management.base import BaseCommand, CommandError

from acct.models import ClearingCause, JournalLine


class Command(BaseCommand):
    help = "Record a named cause and evidence reference for an open 1191/1192/1193 item."

    def add_arguments(self, parser):
        parser.add_argument("line_id", type=int)
        parser.add_argument("--cause", required=True)
        parser.add_argument("--evidence-ref", required=True)
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        if not all(options[key].strip() for key in ("cause", "evidence_ref", "actor")):
            raise CommandError("cause, evidence reference and actor must be nonempty")
        line = JournalLine.objects.filter(pk=options["line_id"], account_id__in=("1191", "1192", "1193")).first()
        if line is None:
            raise CommandError("journal line must belong to 1191, 1192 or 1193")
        if ClearingCause.objects.filter(line=line).exists():
            raise CommandError("cause already recorded for this line")
        item = ClearingCause.objects.create(line=line, cause=options["cause"],
            evidence_ref=options["evidence_ref"], recorded_by=options["actor"])
        self.stdout.write(f"Clearing cause {item.pk} recorded for journal line {line.pk}")
