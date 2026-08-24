"""
Единственное место, знающее про Mathpix. Второй читатель той же полоски.

Модель читает шапку одна, и ошибается она **молча**: «Denis» становится
«Misha», «LAPE» — «LAPA», и обе страницы выглядят уверенно прочитанными.
Поймать такое можно только вторым свидетельством, и оно должно приходить от
кого-то, кто ошибается **иначе**. Mathpix — распознаватель рукописного, а не
языковая модель: у него другая природа и другие промахи, поэтому его согласие
что-то значит, а расхождение — повод посмотреть глазами.

Заменять модель он не может и не должен: он не знает ни про список класса, ни
про красные подписи над плитками, ни про то, что сумма — не задача. Он умеет
одно — сказать, какие буквы и цифры видит на бумаге. Ровно это у него и
спрашивается.

**Отказ Mathpix не отменяет чтения.** Второй читатель — прибавка, и если её
нет, страница читается ровно как раньше. Поэтому наружу отсюда не летит ни
одного исключения: не ответил — вернули «не ответил, вот почему», и пачка
разбирается дальше.

Ходим стандартной библиотекой, а не `requests`: один POST в JSON, а новая
зависимость в образе живёт вечно и требует пересборки у каждого, кто потянет
ветку.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request

from django.conf import settings

from .client import CELLS, cell_index

# Адрес один и в настройки не вынесен: у Mathpix он не меняется, а переменная
# окружения тут значила бы «можно подсунуть другой сервер», чего мы не хотим.
API = "https://api.mathpix.com/v3/text"

# Секунды. Полоска — маленькая картинка, и ответ приходит за пару секунд;
# ждать дольше значит держать воркер, которых на проде два.
TIMEOUT = 20


def configured() -> bool:
    """Есть ли чем звать. Нет ключей — второго читателя просто нет."""
    return bool(
        getattr(settings, "MATHPIX_APP_ID", "")
        and getattr(settings, "MATHPIX_APP_KEY", "")
    )


def read_strip(image: bytes, *, media_type: str = "image/jpeg") -> dict:
    """
    Собранная картинка шапки -> что увидел второй читатель.

    Возвращает всегда словарь, и всегда с ключом `reader`. Не получилось —
    в нём стоит `error`, и это не ошибка вызывающего: чтение продолжается без
    второго мнения.
    """
    if not configured():
        return {"reader": "mathpix", "error": "not_configured"}

    body = json.dumps(
        {
            "src": f"data:{media_type};base64,"
            + base64.standard_b64encode(image).decode(),
            "formats": ["text"],
            # Строки с координатами: по ним видно, где кончается строка имени и
            # начинаются плитки. Плоский текст такого не говорит.
            "include_line_data": True,
            "math_inline_delimiters": ["$", "$"],
        }
    ).encode()

    request = urllib.request.Request(
        API,
        data=body,
        headers={
            "Content-Type": "application/json",
            "app_id": settings.MATHPIX_APP_ID,
            "app_key": settings.MATHPIX_APP_KEY,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            payload = json.loads(answer.read().decode())
    except urllib.error.HTTPError as bad:
        # Код ответа говорит больше тела: 401 — ключи, 429 — потолок Mathpix.
        return {"reader": "mathpix", "error": f"http_{bad.code}"}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"reader": "mathpix", "error": "unreachable"}
    except (json.JSONDecodeError, ValueError):
        return {"reader": "mathpix", "error": "unreadable"}

    # Mathpix умеет отвечать двухсотым с полем `error` внутри.
    if payload.get("error"):
        return {"reader": "mathpix", "error": "refused"}

    return reading_from(lines_of(payload))


def lines_of(payload: dict) -> list[str]:
    """
    Строки ответа по порядку сверху вниз.

    `line_data` даёт их разложенными, и это лучше плоского текста: строка имени
    отделена от плиток самим распознавателем. Нет его — берём `text`, потому
    что половина ответа лучше отказа.
    """
    lines = []
    for one in payload.get("line_data") or []:
        if not isinstance(one, dict):
            continue
        # `included: false` — то, что Mathpix выбросил сам (шум, обрезки).
        if one.get("included") is False:
            continue
        text = (one.get("text") or "").strip()
        if text:
            lines.append(text)
    if lines:
        return lines
    return [line for line in (payload.get("text") or "").splitlines() if line.strip()]


# Подпись над плиткой: `Q1`..`Q15` и сумма. Сигму Mathpix пишет то знаком, то
# латехом, поэтому обе формы.
LABEL = re.compile(
    r"(?:\bQ\s*(?:1[0-5]|[1-9])\b|\bSUM\b|\bTOTAL\b|Σ|\\Sigma\b)",
    re.IGNORECASE,
)

# Печатные подписи строки имени. Ищутся по порядку появления, а не по месту:
# Mathpix может склеить строку иначе, чем она напечатана.
FIELDS = ("first name", "surname", "grade", "date")

# Латех вокруг цифры: `$3$`, `\(3\)`, `{3}`. Цифра от этого не меняется.
NOISE = re.compile(r"[$\\{}()\[\]]|\\text|\\mathrm")


def clean(text: str) -> str:
    return NOISE.sub(" ", text or "")


def reading_from(lines: list[str]) -> dict:
    """
    Строки Mathpix -> то же самое, что возвращает чтение моделью.

    Форма ответа совпадает с моделью нарочно: сверять два чтения можно только
    тогда, когда они одинаковой формы, а приводить их друг к другу в третьем
    месте — значит завести третье место, где живёт форма.
    """
    text = " ".join(lines)
    first_label = LABEL.search(text)
    head = text[: first_label.start()] if first_label else text
    tiles = text[first_label.start():] if first_label else ""

    first, surname, date = names_from(head)
    return {
        "reader": "mathpix",
        "first_name": first,
        "surname": surname,
        "date": date,
        "values": values_from(tiles),
        # Строка имени как есть: человеку показываем прочитанное, а не наш
        # разбор его на графы. Разбор мог и не сойтись.
        "text": clean(head).strip(),
    }


def names_from(head: str) -> tuple[str, str, str]:
    """
    Строка имени -> имя, фамилия, дата.

    Разводит их **печать**: `First name:`, `Surname:`, `Date:` стоят на бланке
    и распознаются как обычный текст, а рукописное лежит между ними. Значение
    поля — это всё, что идёт до следующей печатной подписи.

    Подписей не нашлось вовсе — значит Mathpix прочитал одно рукописное. Тогда
    два слова кладутся в имя и фамилию по порядку, и ошибиться тут не страшно:
    сверяются чтения парой слов целиком, а не по графам.
    """
    text = clean(head)
    found = []
    for name in FIELDS:
        place = text.lower().find(name)
        if place >= 0:
            found.append((place, name))
    found.sort()

    if not found:
        words = [word for word in re.split(r"[\s,]+", text.strip()) if word]
        return (words[0] if words else ""), (words[1] if len(words) > 1 else ""), ""

    values: dict[str, str] = {}
    for number, (place, name) in enumerate(found):
        start = place + len(name)
        end = found[number + 1][0] if number + 1 < len(found) else len(text)
        values[name] = text[start:end].strip(" \t:;.,-—_")

    return values.get("first name", ""), values.get("surname", ""), values.get("date", "")


def values_from(tiles: str) -> list:
    """
    Плитки -> шестнадцать значений по местам.

    Каждая плитка подписана красным (`Q1`…`Q15`, сигма) — эти подписи и режут
    текст на куски: что стоит после подписи и до следующей, то и написано в
    её клетке.

    **Два числа в одном куске — это отказ, а не выбор.** Значит Mathpix
    прочитал что-то, чего мы не понимаем: слипшиеся плитки, обрывок даты,
    подпись, принятую за цифру. Взять первое попавшееся значило бы выдать
    догадку за свидетельство — а всё, ради чего второй читатель заведён, это
    свидетельство.
    """
    values: list = [None] * CELLS
    marks = list(LABEL.finditer(tiles))
    for number, mark in enumerate(marks):
        place = cell_index(mark.group().replace("\\Sigma", "Σ"))
        if place is None:
            continue
        end = marks[number + 1].start() if number + 1 < len(marks) else len(tiles)
        digits = re.findall(r"\d+", clean(tiles[mark.end():end]))
        if len(digits) == 1 and len(digits[0]) <= 3:
            values[place] = int(digits[0])
    return values
