"""
Copy production's attachments into the development bucket.

The other half of `scripts/pull-prod-db.sh`: the database dump brings rows
that point at objects, and this brings the objects, so a copy of production on
the laptop opens its scans and materials instead of answering 404 for each.

The source is read with a token of its own — read-only, on one bucket, kept
in `~/secrets/lesson-tracker.pull.env` and handed in through the environment
(`PULL_R2_*`). The target is written with the application's own dev token.
No key on the laptop can write where production lives, which is the reason the
copy goes through this process instead of R2's server-side copy: that one
needs a single token that reads the source and writes the target.

Three refusals, each cheaper than what it prevents:

* **DEBUG off is a refusal.** Production runs with DEBUG off, and this
  command has no business there — the same line `seed_demo` draws;
* **the target must be a dev bucket** — its name ends in `-dev`. A whitelist:
  an unknown name is a refusal, not «probably fine»;
* **source and target must differ.**

Like `backup_files` it never deletes and copies only what is missing or
different, so a second run over an unchanged source moves nothing.
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from files import storage

ENV_BUCKET = "PULL_R2_BUCKET"
ENV_KEY = "PULL_R2_ACCESS_KEY_ID"
ENV_SECRET = "PULL_R2_SECRET_ACCESS_KEY"


class Command(BaseCommand):
    help = "Copy attachments from production's bucket into the dev bucket."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="only say what would be copied",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if not settings.DEBUG:
            raise CommandError(
                "pull_files работает только при DEBUG=True — на машине "
                "разработчика, не на проде"
            )

        missing = [name for name in (ENV_BUCKET, ENV_KEY, ENV_SECRET) if not os.environ.get(name)]
        if missing:
            raise CommandError(
                "нет ключа источника: " + ", ".join(missing)
                + " (они в ~/secrets/lesson-tracker.pull.env, их передаёт "
                "scripts/pull-prod-db.sh)"
            )

        if not storage.configured():
            raise CommandError(
                "dev-бакет не настроен: нужны R2_* в .env разработки"
            )

        source = os.environ[ENV_BUCKET]
        target_client, target = storage.app_client()

        if not target.endswith("-dev"):
            raise CommandError(
                f"целевой бакет «{target}» не похож на dev-бакет (имя должно "
                "кончаться на -dev) — копировать туда не буду"
            )
        if target == source:
            raise CommandError("источник и цель — один и тот же бакет")

        source_client = storage.pull_client(os.environ[ENV_KEY], os.environ[ENV_SECRET])

        self.stdout.write(
            f"{'проверка (--dry-run)' if dry_run else 'копирование'}: "
            f"{source} -> {target}"
        )

        try:
            existing = storage.index(target_client, target)
            copied = skipped = failed = 0

            for item in storage.iter_objects(source_client, source):
                if not storage.needs_copy(item, existing.get(item.key)):
                    skipped += 1
                    continue

                if dry_run:
                    self.stdout.write(f"  скопировался бы {item.key} ({item.size} Б)")
                    copied += 1
                    continue

                try:
                    storage.carry_object(
                        source_client, target_client, item.key, source=source, target=target
                    )
                except storage.StorageUnavailable as error:
                    # one bad object should not cost the rest: the next run
                    # picks it up, since it is still missing from the target
                    self.stderr.write(self.style.WARNING(f"  {item.key}: {error}"))
                    failed += 1
                    continue

                copied += 1
        except storage.StorageUnavailable as error:
            raise CommandError(f"хранилище не отвечает: {error}")

        self.stdout.write(f"скопировано: {copied}, пропущено (уже есть): {skipped}")

        if failed:
            raise CommandError(f"не удалось скопировать объектов: {failed}")
