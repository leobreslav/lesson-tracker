"""
Модели и цены — в одном месте, потому что расходятся они молча.

Цена живёт рядом с именем модели: разъехавшись, они дают счёт, который не
сходится с настоящим, а заметить это можно только по выписке от Anthropic
через месяц. Числа — доллары за миллион токенов, вход и выход.

Обновлять при смене прайса. Модель, которой тут нет, к вызову не допускается
вовсе (`price_of` поднимает ошибку): считать расход по нулевой цене — это
тихо снятый потолок.
"""

# Дешёвая, ей читается каждая полоска шапки.
HAIKU = "claude-haiku-4-5-20251001"
# Дорогая и внимательная: ею перечитывается то, что не сошлось.
SONNET = "claude-sonnet-5"

PRICES = {
    HAIKU: (1.0, 5.0),
    SONNET: (3.0, 15.0),
}


def price_of(model: str) -> tuple[float, float]:
    try:
        return PRICES[model]
    except KeyError:
        raise ValueError(f"Unknown model {model!r}: add it to vision/prices.py")


def cost_micros(model: str, input_tokens: int, output_tokens: int) -> int:
    """
    Стоимость вызова в миллионных долях доллара.

    Целые числа, а не float: деньги складываются и сравниваются с потолком, а
    накопленная ошибка сложения float'ов в этом месте — не мелочь.
    """
    in_price, out_price = price_of(model)
    return round(input_tokens * in_price + output_tokens * out_price)
