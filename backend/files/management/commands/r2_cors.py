"""
Разрешить браузеру **читать** файл из бакета кодом, а не только тегом.

Настройка эта живёт в бакете, а не в репозитории, и потому норовит стать
фольклором: «а, там надо в дашборде галочку». Отсюда команда — чтобы правило
было записано в коде, применялось одной строкой и проверялось глазами.

**Зачем понадобилось.** До просмотра PDF всё, что браузер брал из R2, он брал
тегом: `<img src="подписанная ссылка">`. Тегу CORS не нужен вовсе — картинка
рисуется и с чужого домена. А `pdf.js` читает файл **кодом**, запросами с
диапазонами байт, и такой запрос браузер без заголовков `Access-Control-*`
не отдаёт странице: файл на месте, ссылка верная, а в просмотрщике пусто.

**Почему не проксируем байты через Django.** Потому что там про это сказано
прямо, и сказано верно: воркеров два, и держать один из них на время
скачивания нельзя (`files/views.py`, `download`). Проксирование ради одного
вида файлов завело бы вторую дорогу к тому же объекту — и первый же
двадцатимегабайтный скан занял бы половину прода на минуту.

Правило узкое намеренно: **чтение, со своих доменов**. Запись, удаление и
чужие источники сюда не входят; подписанная ссылка и так живёт пять минут, а
CORS не заменяет право — он только разрешает браузеру показать странице то,
что сервер уже согласился отдать.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from files import storage

# Что разрешаем. `GET` и `HEAD` — чтение; `Range` в заголовках запроса и
# `Content-Range` с `Content-Length` в ответе нужны pdf.js: он читает документ
# кусками, а не целиком, и без них листание тянуло бы весь файл на каждую
# страницу.
RULE = {
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedHeaders": ["Range", "Content-Type"],
    "ExposeHeaders": ["Content-Range", "Content-Length", "Accept-Ranges"],
    "MaxAgeSeconds": 3600,
}


def origins() -> list[str]:
    """
    Кому разрешено. Домены контура, а не звёздочка.

    Звёздочка тут выглядела бы безобидной — ссылка подписана и живёт пять
    минут, — но она означает «любая страница в интернете может читать наши
    файлы кодом, если добыла ссылку». Ссылка же попадает в историю браузера,
    в лог прокси и в пересланное сообщение; сужение до своих доменов ничего не
    стоит и убирает целый класс разговоров.
    """
    # Оба списка отвечают на один и тот же вопрос — «какие домены наши», — и
    # заведены они в `.env` контура. Третьего списка тут быть не должно:
    # разъехавшись, он дал бы контур, где страница открывается, а файлы в ней
    # не читаются, и искать это пришлось бы в бакете.
    names = [
        *getattr(settings, "CORS_ALLOWED_ORIGINS", []),
        *getattr(settings, "CSRF_TRUSTED_ORIGINS", []),
    ]

    seen = []
    for name in names:
        name = (name or "").strip().rstrip("/")
        if name and name not in seen:
            seen.append(name)
    return seen


class Command(BaseCommand):
    help = "Allow the browser to read bucket objects with code (pdf.js needs it)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--show",
            action="store_true",
            help="Show what the bucket says now and change nothing.",
        )

    def handle(self, *args, **options):
        if not storage.configured():
            raise CommandError(
                "Хранилище не настроено: без ключей R2 настраивать нечего."
            )

        bucket = settings.R2_BUCKET_NAME
        client = storage.backend().bucket.meta.client

        if options["show"]:
            try:
                answer = client.get_bucket_cors(Bucket=bucket)
            except Exception as problem:  # noqa: BLE001 — печатаем как есть
                self.stdout.write(f"Правил нет или их не прочитать: {problem}")
                return
            self.stdout.write(str(answer.get("CORSRules")))
            return

        allowed = origins()
        if not allowed:
            raise CommandError(
                "Некому разрешать: CORS_ALLOWED_ORIGINS и CSRF_TRUSTED_ORIGINS пусты."
            )

        client.put_bucket_cors(
            Bucket=bucket,
            CORSConfiguration={"CORSRules": [{"AllowedOrigins": allowed} | RULE]},
        )
        self.stdout.write(self.style.SUCCESS(f"Разрешено читать кодом: {', '.join(allowed)}"))
