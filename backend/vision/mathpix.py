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
import urllib.error
import urllib.request

from django.conf import settings

from . import strip

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

    return strip.reading_from(lines_of(payload), reader="mathpix")


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
