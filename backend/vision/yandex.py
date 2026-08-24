"""
Единственное место, знающее про Yandex Vision OCR. Ещё один читатель полоски.

Заведён он ради контура, до Anthropic не достающего: там языковой модели нет
вовсе, а читать пачку надо. Но польза его не только в этом — он **ошибается
иначе**, чем Mathpix, а два свидетеля одной природы стоят меньше, чем два
разной.

**Это распознаватель, а не модель, и путать их нельзя.** Он не знает списка
класса, не понимает бланка и не даёт `guess`; он говорит, какие буквы и цифры
видит. В нашей расстановке это делает его читателем имени там, где языковой
модели нет, — но не её заменой.

Моделей у него несколько, и берётся `handwritten`: она читает печатное
вперемешку с рукописным, а на нашей полоске именно так и есть — печатные
подписи бланка и рукописное между ними. Есть и `table`, отдельная модель для
таблиц; плитки с баллами — как раз таблица, и это стоит попробовать живой
пачкой, прежде чем закладывать в код (см. `.claude/rules/works.md`).

**Форму ответа мы не проверяли живым запросом** — он стоит денег, и правило
CLAUDE.md про это прямое. Поэтому разбор написан защитно: берутся строки, а
не структура, и если разложенных строк не нашлось, идёт сплошной текст. Так
же устроен и Mathpix, и по той же причине — половина ответа лучше отказа.

Ходим стандартной библиотекой, а не `requests`: один POST в JSON, а новая
зависимость в образе живёт вечно и требует пересборки у каждого, кто потянет
ветку.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

from django.conf import settings

from . import strip

# Адрес один и в настройки не вынесен: у сервиса он не меняется, а переменная
# окружения тут значила бы «можно подсунуть другой сервер», чего мы не хотим.
API = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"

# Секунды. Полоска — маленькая картинка; ждать дольше значит держать воркер,
# которых на проде два.
TIMEOUT = 20

# Моделей у сервиса несколько, и **у нас в ходу две**. Полоска шапки — это две
# разные вещи на одной картинке: строка имени, написанная от руки, и сетка
# плиток с баллами. Одной моделью они читаются плохо, и это выяснилось живой
# пачкой: `handwritten` разобрал имена на всех страницах и не увидел почти ни
# одной клетки — ноль или одну из шестнадцати.
#
# Причина не в качестве, а в задаче: плитки это **таблица**, а для таблиц у
# сервиса отдельная модель. Поэтому полоска читается дважды, разными моделями,
# и каждое чтение отвечает за своё. Цена от этого удваивается — два запроса
# вместо одного, — и это осознанный размен: без него баллы пришлось бы вбивать
# руками.
#
# Обе ограничены русским и английским, и оба языка надо назвать явно: без
# `languageCodes` сервис берёт другую модель.
HANDWRITTEN = "handwritten"
TABLE = "table"
LANGUAGES = ["ru", "en"]

# Наш `media_type` -> то, как этот сервис называет формат.
MIME = {
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/png": "PNG",
    "application/pdf": "PDF",
}


def configured() -> bool:
    """Есть ли чем звать. Нет ключа — нет и читателя."""
    return bool(getattr(settings, "YANDEX_OCR_API_KEY", ""))


def read_cells(image: bytes, *, media_type: str = "image/jpeg") -> dict:
    """
    Та же картинка, но моделью для таблиц: ради плиток с баллами.

    Отдельная дверь, а не флаг у `read_strip`, потому что и роль другая: это
    чтение зовут там, где нужен **читатель клеток**, и его ответ идёт в
    слияние по своей графе (`merge.py`). Имя из него не берут — модель для
    таблиц строку имени разбирает как придётся.
    """
    return read_strip(image, media_type=media_type, model=TABLE)


def read_strip(
    image: bytes, *, media_type: str = "image/jpeg", model: str = HANDWRITTEN
) -> dict:
    """
    Собранная картинка шапки -> что увидел этот читатель.

    Возвращает всегда словарь, и всегда с ключом `reader`. Не получилось — в
    нём стоит `error`. Что делать с отказом, решает вызывающий: прибавке он
    ничего не ломает, а единственному читателю означает непрочитанную
    страницу.
    """
    if not configured():
        return {"reader": "yandex", "error": "not_configured"}

    body = json.dumps(
        {
            "mimeType": MIME.get(media_type, "JPEG"),
            "languageCodes": LANGUAGES,
            "model": model,
            "content": base64.standard_b64encode(image).decode(),
        }
    ).encode()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {settings.YANDEX_OCR_API_KEY}",
    }
    # С API-ключом каталог не нужен — сервис берёт тот, где заведён сервисный
    # аккаунт. Строка оставлена для контуров, где ключ выдан иначе: лишний
    # заголовок безвреден, а отсутствующий стоит отказа, который не объяснить.
    folder = getattr(settings, "YANDEX_FOLDER_ID", "")
    if folder:
        headers["x-folder-id"] = folder

    request = urllib.request.Request(API, data=body, headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            payload = json.loads(answer.read().decode())
    except urllib.error.HTTPError as bad:
        # Код ответа говорит больше тела: 401 и 403 — ключ или права, 429 —
        # потолок на стороне сервиса.
        return {"reader": "yandex", "error": f"http_{bad.code}"}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"reader": "yandex", "error": "unreachable"}
    except (json.JSONDecodeError, ValueError):
        return {"reader": "yandex", "error": "unreadable"}

    lines = lines_of(payload)
    if not lines:
        # Двухсотый с пустым разбором — это не «на бумаге пусто», а «мы не
        # поняли ответ». Молчаливо вернуть пустую шапку значило бы свалить на
        # бумагу чужую беду.
        return {"reader": "yandex", "error": "unreadable"}
    return strip.reading_from(lines, reader="yandex")


def lines_of(payload: dict) -> list[str]:
    """
    Строки ответа по порядку сверху вниз.

    Слова сложены в строки, строки в блоки, блоки в страницу — берём строки:
    по ним видно, где кончается строка имени и начинаются плитки. Разложенных
    строк не нашлось — берём сплошной текст, потому что половина ответа лучше
    отказа.

    Написано **терпимо к форме**: ответ мы видели только в документации, а
    падать на неожиданном ключе значило бы менять «прочитали хуже» на «не
    прочитали вовсе».
    """
    annotation = ((payload or {}).get("result") or {}).get("textAnnotation") or {}

    lines = []
    for block in annotation.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        for line in block.get("lines") or []:
            if not isinstance(line, dict):
                continue
            text = (line.get("text") or "").strip()
            if text:
                lines.append(text)
    if lines:
        return lines

    whole = annotation.get("fullText") or ""
    return [line for line in whole.splitlines() if line.strip()]
