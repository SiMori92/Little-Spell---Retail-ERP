"""Post one existing ops or accounting-originated event; never creates ops facts."""
from django.core.management.base import BaseCommand, CommandError
from acct.models import AcctManualEntry
from acct.posting import PostingError, post_event
from ops.models import LedgerEvent


class Command(BaseCommand):
    help = "Post one event by table and ID. Required evidence failures stay unposted."

    def add_arguments(self, parser):
        parser.add_argument("stream", choices=("ops", "manual"))
        parser.add_argument("event_id", type=int)

    def handle(self, *args, **options):
        model = LedgerEvent if options["stream"] == "ops" else AcctManualEntry
        try:
            event = model.objects.get(pk=options["event_id"])
            entry_id = post_event(event)
        except model.DoesNotExist as exc:
            raise CommandError("event ID does not exist") from exc
        except PostingError as exc:
            model.objects.filter(pk=options["event_id"]).update(posting_error=str(exc))
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"posted journal entry {entry_id}")
