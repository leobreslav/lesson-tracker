"""
Строки, увиденные распознавателем -> шапка нашего бланка.

Разбор этот **про бумагу, а не про поставщика**. Он опирается на то, что
напечатано на бланке: подписи `First name:`, `Surname:`, `Date:` в строке
имени и красные `Q1`…`Q15` с сигмой над плитками. Кто именно прочитал эти
буквы — Mathpix, Yandex или кто-то третий — разбору безразлично.

Жил он поэтому не на месте: внутри `mathpix.py`, как будто знание о нашем
бланке принадлежит поставщику. Со вторым распознавателем это выяснилось сразу
же — либо копировать сотню строк, либо импортировать разбор из чужого модуля,
и оба варианта плохи одинаково. Копия разошлась бы молча: правку подписи на
бланке сделали бы в одном месте, и один читатель начал бы видеть плитки, а
другой нет.

Ответ читателя приводится **к той же форме, что у модели**, и это не
вежливость. Сверять два чтения можно только тогда, когда они одинаковой формы;
приводить их друг к другу в третьем месте значит завести третье место, где
живёт форма.
"""

from __future__ import annotations

import re

from .client import CELLS, cell_index

# Подпись над плиткой: `Q1`..`Q15` и сумма. Сигму распознаватели пишут то
# знаком, то латехом, поэтому обе формы.
LABEL = re.compile(
    r"(?:\bQ\s*(?:1[0-5]|[1-9])\b|\bSUM\b|\bTOTAL\b|Σ|\\Sigma\b)",
    re.IGNORECASE,
)

# Печатные подписи строки имени. Ищутся по порядку появления, а не по месту:
# распознаватель может склеить строку иначе, чем она напечатана.
FIELDS = ("first name", "surname", "grade", "date")

# Латех вокруг цифры: `$3$`, `\(3\)`, `{3}`. Цифра от этого не меняется.
NOISE = re.compile(r"[$\\{}()\[\]]|\\text|\\mathrm")


def clean(text: str) -> str:
    return NOISE.sub(" ", text or "")


def reading_from(lines: list[str], *, reader: str) -> dict:
    """
    Строки -> то же самое, что возвращает чтение моделью.

    `reader` подписывает ответ именем того, кто читал. Подпись эта доезжает до
    экрана: человеку, решающему спор, важно знать, чьё второе чтение он видит,
    а нам — чьё свидетельство чего стоит.
    """
    text = " ".join(lines)
    first_label = LABEL.search(text)
    head = text[: first_label.start()] if first_label else text
    tiles = text[first_label.start():] if first_label else ""

    first, surname, date = names_from(head)
    return {
        "reader": reader,
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

    Подписей не нашлось вовсе — значит прочитано одно рукописное. Тогда два
    слова кладутся в имя и фамилию по порядку, и ошибиться тут не страшно:
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

    **Два числа в одном куске — это отказ, а не выбор.** Значит прочитано
    что-то, чего мы не понимаем: слипшиеся плитки, обрывок даты, подпись,
    принятая за цифру. Взять первое попавшееся значило бы выдать догадку за
    свидетельство — а всё, ради чего второй читатель заведён, это
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
