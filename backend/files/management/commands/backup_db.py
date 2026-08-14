"""
Положить готовый дамп базы в резервный бакет.

Дамп на диске сервера — это не копия: диск и база живут на одной машине и
умрут вместе. Бакет для этого уже есть — тот же, куда уезжают вложения, — и
токен к нему есть только у резервных ключей.

Дамп команда **не делает**: `pg_dump` живёт в контейнере базы, а boto3 — в
этом. Поэтому разделение такое: `scripts/backup-db.sh` снимает дамп и
проверяет, что он не пустой, а сюда отдаёт его на stdin. Команда лежит в
`files` по той же причине, по которой там лежит `backup_files`: про R2 в
проекте знает ровно одно приложение.

Дампы держатся под своим префиксом `db/`. Это не косметика: `backup_files`
ходит по `files/`, и с общим префиксом `--restore` попытался бы вернуть
дампы в бакет вложений.
"""

import sys
from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from files import storage

DB_PREFIX = "db/"


def stamp_of(key: str) -> date | None:
    """
    Дата из имени `db/lessons_2026-08-14_0330.sql.gz`, или None.

    Возраст берётся из имени, а не из `LastModified`: имя задаём мы сами и
    оно означает «за какой день дамп», тогда как время объекта означает
    «когда его сюда положили» — при переливке бакета оно обнулится, и
    хранение поехало бы.
    """
    name = key.removeprefix(DB_PREFIX)
    if not name.startswith("lessons_"):
        return None

    try:
        stamp = name[len("lessons_") : len("lessons_") + 10]
        return datetime.strptime(stamp, "%Y-%m-%d").date()
    except ValueError:
        return None


def expired(keys, keep_days: int, today: date) -> list[str]:
    """
    Какие дампы пора убрать. Чужое и непонятное не трогаем.

    Объект, имя которого не разобралось, остаётся навсегда: не понял, что
    это, — не удаляй. Ошибиться здесь дороже, чем заплатить за лишний
    килобайт.
    """
    edge = today - timedelta(days=keep_days)

    return sorted(
        key
        for key in keys
        if (stamp := stamp_of(key)) is not None and stamp < edge
    )


class Command(BaseCommand):
    help = "Upload a database dump (on stdin) to the backup bucket."

    # `stdin` подменяется в тестах — как у django-овского createsuperuser
    stealth_options = ("stdin",)

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            required=True,
            help="file name of the dump, e.g. lessons_2026-08-14_0330.sql.gz",
        )
        parser.add_argument(
            "--keep-days",
            type=int,
            default=7,
            help="how long the copies live in the bucket (default: 7)",
        )

    def handle(self, *args, **options):
        if not storage.backup_configured():
            raise CommandError(
                "резервный бакет не настроен: нужны R2_BACKUP_BUCKET_NAME, "
                "R2_BACKUP_ACCESS_KEY_ID, R2_BACKUP_SECRET_ACCESS_KEY "
                "и R2_ENDPOINT_URL"
            )

        name = options["name"].strip()
        if "/" in name or not name:
            raise CommandError(f"имя дампа никуда не годится: {name!r}")

        # читаем целиком: дамп базы этого проекта — единицы мегабайт (файлы
        # лежат в R2, а не в базе), а с телом в руках видно и размер
        body = self.read_dump(options.get("stdin") or sys.stdin)
        bucket = settings.R2_BACKUP_BUCKET_NAME
        key = DB_PREFIX + name
        client = storage.backup_client()

        try:
            storage.put_object(client, bucket, key, body)
            self.stdout.write(f"загружено: {key} ({len(body)} Б) -> {bucket}")
            self.prune(client, bucket, options["keep_days"])
        except storage.StorageUnavailable as error:
            raise CommandError(f"хранилище не отвечает: {error}")

    def read_dump(self, stdin) -> bytes:
        """
        Тело дампа со stdin.

        Пустой ввод — это отказ, а не пустой объект: пустой дамп в бакете
        выглядит как копия и обнаруживается в тот день, когда понадобится.
        """
        body = getattr(stdin, "buffer", stdin).read()
        if isinstance(body, str):
            body = body.encode()

        if not body:
            raise CommandError("на stdin пусто: дамп не передан")

        return body

    def prune(self, client, bucket: str, keep_days: int) -> None:
        """Убрать копии старше срока — тем же правилом, что и на диске."""
        keys = [item.key for item in storage.iter_objects(client, bucket, DB_PREFIX)]
        doomed = expired(keys, keep_days, timezone.localdate())

        for key in doomed:
            storage.delete_object(client, bucket, key)
            self.stdout.write(f"  убрано старое: {key}")

        self.stdout.write(
            f"копий в бакете: {len(keys) - len(doomed)}, убрано: {len(doomed)}"
        )
