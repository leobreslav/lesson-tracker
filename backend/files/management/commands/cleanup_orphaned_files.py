"""
Rubbish in two directions, and one command that names both.

Nothing here should ever find anything: an attachment removed in the normal
way takes its file with it. But the normal way runs on transaction commit and
talks to a network, so both halves have a way of failing:

* **an object with no row.** The upload put bytes in R2 and the transaction
  that would have recorded them rolled back;
* **a row with no reference.** The last attachment went, and R2 refused the
  delete — the signal deliberately keeps the row so that this command can
  finish the job later.

Showing is the default. `--delete` is a separate, deliberate keystroke,
because the first thing this command does when something is subtly wrong is
propose deleting a school's teaching materials.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count
from files import storage
from files.models import StoredFile


class Command(BaseCommand):
    help = "Find files in storage with no record, and records with no reference."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            help="actually remove what was found (otherwise it is only listed)",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="say nothing when there is nothing to say (for cron)",
        )

    def handle(self, *args, **options):
        delete = options["delete"]
        # еженедельная строка «сирот нет» через год станет всем логом, а
        # пустой лог — это и есть «всё в порядке»
        self.quiet = options["quiet"]

        unreferenced = list(
            StoredFile.objects.annotate(references=Count("attachments")).filter(
                references=0
            )
        )

        try:
            keys_in_store = set(storage.iter_keys())
        except storage.StorageUnavailable as error:
            self.stderr.write(
                self.style.ERROR(f"хранилище не отвечает: {error}")
            )
            # the half that needs only the database is still worth reporting
            keys_in_store = None

        self.report_records(unreferenced, delete)

        if keys_in_store is not None:
            known = set(StoredFile.objects.values_list("key", flat=True))
            self.report_objects(sorted(keys_in_store - known), delete)

        if not delete:
            self.say("\nничего не удалено; повторите с --delete")

    # --- rows with nothing pointing at them ---

    def say(self, text, found=False):
        """Печатать, если есть о чём — или если тишину не просили."""
        if found or not self.quiet:
            self.stdout.write(text)

    def report_records(self, rows, delete):
        self.say(f"\nзаписи без единого вложения: {len(rows)}", found=bool(rows))

        for stored in rows:
            self.stdout.write(f"  {stored.key}  ({stored.size} Б, {stored.original_name})")
            if not delete:
                continue

            try:
                storage.delete(stored.key)
            except storage.StorageUnavailable as error:
                self.stderr.write(self.style.WARNING(f"    не удалось: {error}"))
                continue

            stored.delete()
            self.stdout.write(self.style.SUCCESS("    удалено"))

    # --- objects nobody knows about ---

    def report_objects(self, keys, delete):
        self.say(f"\nобъекты в хранилище без записи: {len(keys)}", found=bool(keys))

        for key in keys:
            self.stdout.write(f"  {key}")
            if not delete:
                continue

            try:
                storage.delete(key)
            except storage.StorageUnavailable as error:
                self.stderr.write(self.style.WARNING(f"    не удалось: {error}"))
                continue

            self.stdout.write(self.style.SUCCESS("    удалено"))
