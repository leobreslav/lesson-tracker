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

Моделей у него несколько, и в ходу две. `handwritten` читает печатное
вперемешку с рукописным — это про строку имени; `table` читает таблицы — это
про сетку баллов. Почему их две, сказано ниже, у самих имён.

**Форму ответа мы живым запросом не проверяли** — он стоит денег, и правило
CLAUDE.md про это прямое. Поэтому разбор написан защитно: берутся строки, а
не структура, и если разложенных строк не нашлось, идёт сплошной текст. Так
же устроен и Mathpix, и по той же причине — половина ответа лучше отказа.

**Одна поправка в эту форму пришла с живой пачки, и дорого.** Модель для
таблиц кладёт узнанное не в `blocks`, а в `tables` — мы туда не смотрели, и
пачка из тридцати четырёх листов приехала без единого балла. Читаются теперь
оба места; подробности — у `table_lines`.

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


def whole_number(value) -> int:
    """
    Индекс клетки таблицы -> число. Сервис отдаёт их строками (`"3"`).

    Не разобралось — ноль: порядок колонок при этом собьётся, но собьётся
    предсказуемо, а падать на форме ответа нельзя.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def table_lines(annotation: dict) -> list[str]:
    """
    Клетки таблицы -> строки «подпись значение», по строке на колонку.

    **Разложенных строк у таблицы нет, и это стоило целой пачки.** Модель для
    таблиц кладёт узнанное не в `blocks`, а в `tables`: там клетки со своими
    номерами строки и колонки. Мы читали только блоки, поэтому от полоски
    приезжали печатные подписи строки имени — и ни одной плитки. Выглядело
    это как «Yandex не умеет читать баллы», хотя мы просто не смотрели туда,
    куда он их положил.

    Собирается **по колонкам**, а не по строкам, и это прямо про наш бланк:
    подпись `Q1` стоит над своей клеткой, то есть в той же колонке строкой
    выше. Колонкой они и склеиваются в «Q1 3» — ровно ту форму, которую ждёт
    разбор полоски, где значение идёт за подписью. Собери мы по строкам,
    вышло бы «Q1 Q2 … Σ» и отдельно «3 1 …», а связь подписи со значением
    осталась бы в номерах колонок, то есть потерялась бы.
    """
    lines = []
    for table in annotation.get("tables") or []:
        if not isinstance(table, dict):
            continue
        columns: dict[int, list[tuple[int, str]]] = {}
        for cell in table.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            text = (cell.get("text") or "").strip()
            if not text:
                continue
            columns.setdefault(whole_number(cell.get("columnIndex")), []).append(
                (whole_number(cell.get("rowIndex")), text)
            )
        for column in sorted(columns):
            lines.append(" ".join(text for _, text in sorted(columns[column])))
    return lines


def lines_of(payload: dict) -> list[str]:
    """
    Строки ответа по порядку сверху вниз.

    Слова сложены в строки, строки в блоки, блоки в страницу — берём строки:
    по ним видно, где кончается строка имени и начинаются плитки. За ними идут
    клетки таблиц (`table_lines`): у модели для таблиц узнанное лежит там, и
    без них от сетки баллов не приезжает ничего. Не нашлось ни того ни
    другого — берём сплошной текст, потому что половина ответа лучше отказа.

    **Порядок тут не косметический.** Клетки таблицы идут последними нарочно:
    если сетка приехала и блоками, и таблицей, разбор берёт последнее
    прочтение подписи, а у таблицы связь подписи со значением надёжнее — она
    в номерах колонок, а не в том, как читатель склеил строку.

    Написано **терпимо к форме**: падать на неожиданном ключе значило бы
    менять «прочитали хуже» на «не прочитали вовсе».
    """
    annotation = ((payload or {}).get("result") or {}).get("textAnnotation") or {}
    if not isinstance(annotation, dict):
        return []

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

    lines += table_lines(annotation)
    if lines:
        return lines

    whole = annotation.get("fullText") or ""
    return [line for line in whole.splitlines() if line.strip()]
