"""
Copy the attachment bucket into the backup bucket, once a day.

R2 has no object versioning — the setting exists in AWS S3 and nowhere in
Cloudflare's dashboard or API — so the copy has to be made by somebody. This
command is that somebody, driven by `scripts/backup-files.sh` from cron.

Three rules make it a backup rather than a mirror:

* **it never deletes.** An object gone from the main bucket stays in the copy;
  that is the whole point, since the thing being guarded against is a deletion
  nobody meant to make;
* **it copies only what is new or different**, so a nightly run over an
  unchanged bucket is a couple of listings and no traffic;
* **it is idempotent** — running it twice in a row changes nothing the second
  time, and interrupting it half way just means the rest goes tomorrow (or on
  the next manual run).

The copy is server-side: one token reads both buckets, Cloudflare moves the
bytes internally, and the VPS never sees them. Restoring is the same walk
with the buckets swapped — `--restore` — which puts back what is missing and
leaves alone what is already there.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from files import storage


class Command(BaseCommand):
    help = "Copy new and changed attachment objects into the backup bucket."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="only say what would be copied",
        )
        parser.add_argument(
            "--restore",
            action="store_true",
            help="the other direction: put objects back from the backup bucket",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        main, backup = settings.R2_BUCKET_NAME, settings.R2_BACKUP_BUCKET_NAME

        if not main:
            raise CommandError("не задан R2_BUCKET_NAME")
        if not storage.backup_configured():
            raise CommandError(
                "резервный бакет не настроен: нужны R2_BACKUP_BUCKET_NAME, "
                "R2_BACKUP_ACCESS_KEY_ID, R2_BACKUP_SECRET_ACCESS_KEY "
                "и R2_ENDPOINT_URL"
            )

        source, target = (backup, main) if options["restore"] else (main, backup)
        client = storage.backup_client()

        self.stdout.write(
            f"{'проверка (--dry-run)' if dry_run else 'синхронизация'}: "
            f"{source} -> {target}"
        )

        try:
            existing = storage.index(client, target)
            copied, skipped, failed, seen = self.walk(
                client, source, target, existing, dry_run
            )
        except storage.StorageUnavailable as error:
            raise CommandError(f"хранилище не отвечает: {error}")

        # objects the source no longer has: deleted there, kept here on purpose
        kept = len(set(existing) - seen)

        self.stdout.write(
            f"скопировано: {copied}, пропущено (уже есть): {skipped}, "
            f"осталось только в резерве: {kept}"
        )

        if failed:
            raise CommandError(f"не удалось скопировать объектов: {failed}")

    def walk(self, client, source, target, existing, dry_run):
        """One pass over the source. Returns the counters and the keys seen."""
        copied = skipped = failed = 0
        seen = set()

        for item in storage.iter_objects(client, source):
            seen.add(item.key)

            if not storage.needs_copy(item, existing.get(item.key)):
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"  скопировался бы {item.key} ({item.size} Б)")
                copied += 1
                continue

            try:
                storage.copy_object(client, item.key, source=source, target=target)
            except storage.StorageUnavailable as error:
                # one bad object should not cost the rest of the run: the
                # remainder still gets copied, and tomorrow's run retries it
                self.stderr.write(self.style.WARNING(f"  {item.key}: {error}"))
                failed += 1
                continue

            self.stdout.write(f"  {item.key} ({item.size} Б)")
            copied += 1

        return copied, skipped, failed, seen
