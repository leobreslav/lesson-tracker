"""
Потолок расхода и журнал трат.

Потолок ставит администратор школы, месячный: календарный месяц кончается сам,
и это единственная граница, которую не надо ни обнулять по расписанию, ни
объяснять. Проверяется он **до** вызова, а стоимость известна только после, —
значит перешагнуть его можно ровно на цену одного вызова, доли цента. Это
названо честно, а не спрятано: альтернатива — резервировать оценку заранее и
возвращать разницу, и она сложнее ровно настолько, насколько бессмысленна.

Ноль в потолке значит «нельзя», а не «без ограничений»: школа, которой забыли
поставить лимит, не должна тратить.
"""

from __future__ import annotations

from datetime import datetime, timezone

from django.db.models import Sum

from config.errors import Codes, api_error

from . import agreement, mathpix, prices
from .client import read_header, read_questions
from .models import AiSpend


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spent_this_month(school) -> int:
    """Сколько школа потратила с первого числа, в микродолларах."""
    total = AiSpend.objects.filter(
        school=school, created_at__gte=month_start()
    ).aggregate(total=Sum("cost_micros"))["total"]
    return total or 0


def limit_micros(school) -> int:
    return int(school.ai_month_limit_cents) * 10_000


def budget(school) -> dict:
    """Состояние потолка — то же самое, что показывается на экране."""
    limit = limit_micros(school)
    spent = spent_this_month(school)
    return {
        "limit_micros": limit,
        "spent_micros": spent,
        "left_micros": max(0, limit - spent),
        "month_start": month_start().date().isoformat(),
    }


def has_budget(school) -> bool:
    """
    Осталось ли чем платить. Спрашивают об этом там, где вызов **необязателен**.

    Второй читатель и арбитр — прибавка к чтению, а не оно само: упереться на
    них в потолок значит потерять уже сделанную и уже оплаченную работу. Отказ
    поэтому поднимается только на главном чтении, а прибавки просто не
    случаются — молчаливо, потому что расход виден в журнале, а страница и без
    них полноценно прочитана.
    """
    return budget(school)["left_micros"] > 0


def check_budget(school) -> None:
    state = budget(school)
    if state["left_micros"] <= 0:
        raise api_error(
            Codes.AI_BUDGET_EXCEEDED,
            "The school has spent its monthly limit for reading scans.",
            limit=state["limit_micros"],
            spent=state["spent_micros"],
        )


def read_and_charge(
    *,
    school,
    user,
    work,
    image: bytes,
    media_type: str = "image/jpeg",
    candidates: list[str] | None = None,
    model: str | None = None,
    purpose: str = AiSpend.SCAN_HEADER,
    asked_second: bool = True,
) -> dict:
    """
    Прочитать полоску и записать трату. Одна дверь: считать, не заплатив, нельзя.

    Модель по умолчанию берётся из настроек (`SCAN_HEADER_MODEL`), а не зашита
    здесь: на цифрах в отдельных квадратиках разницы между моделями нет, а на
    рукописном имени есть — и стоит она втрое. Проверять это надо на живой
    пачке, и переключение должно стоить строки в `.env`, а не правки кода.

    **Читателей бывает двое, и второй нужен не ради второго мнения, а ради
    расхождения.** Модель ошибается молча: «Denis» становится «Misha», и
    страница уходит не тому — уверенно и без единой пометки. Поймать такое
    можно только другим свидетельством, и Mathpix годится потому, что он не
    модель: распознаватель рукописного ошибается иначе. Сошлись — странице
    можно верить сильнее прежнего; разошлись — человек об этом узнает.

    **Чужого чтения первым двум читателям не показывают.** Закон проекта
    выведен дважды и дорого: подсказанное подставляется вместо увиденного.
    Подскажи мы модели ответ Mathpix — их согласие перестало бы что-либо
    значить, а вместе с ним и вся затея. Обе версии видит только **арбитр**,
    и только тогда, когда спор уже случился и уже записан.

    **Порядок вызовов не случаен: сперва модель, потом прибавки.** Чтение
    моделью — это то, без чего страницы нет вовсе; второй читатель и арбитр —
    прибавка. Упрись мы в потолок или в отказ сети на первом шаге из трёх,
    потерять хочется прибавку, а не страницу.

    `asked_second` — просьба человека, галочка на шаге выбора файла. Второй
    читатель удваивает цену пачки, а нужен он не всегда: у пачки, где имена
    вписаны учителем печатными буквами, спорить не о чем. Решение поэтому не
    наше и не настроечное — того, кто платит и держит стопку в руках.
    """
    from django.conf import settings

    model = model or getattr(settings, "SCAN_HEADER_MODEL", prices.HAIKU)
    check_budget(school)
    data, input_tokens, output_tokens = read_header(
        image,
        media_type=media_type,
        candidates=candidates,
        model=model,
    )
    _charge(school, user, work, purpose, model, input_tokens, output_tokens)
    data["model"] = model

    second = second_reading(school, user, work, image, media_type, asked=asked_second)
    # Спор записывается **до** арбитража и потом не пересчитывается. Иначе он
    # исчезал бы ровно тогда, когда арбитр встал на сторону второго читателя:
    # чтение сошлось бы с ним, и страница, о которой спорили трое, выглядела бы
    # бесспорной. Событие тут — сам спор, а не его нынешний след.
    second["differs"] = agreement.compare(data, second)
    if second["differs"]:
        data = arbitrate(
            school,
            user,
            work,
            image,
            media_type=media_type,
            candidates=candidates,
            rivals=[data, second],
            reading=data,
            second=second,
        )

    data["second"] = second
    return data


def second_reading(
    school, user, work, image: bytes, media_type: str, *, asked: bool = True
) -> dict:
    """
    Позвать второго читателя и записать трату. Не позвался — не беда.

    Возвращается всегда словарь: `error` внутри значит «второго мнения по этой
    странице нет», и это законное состояние, а не отказ. Ключей Mathpix может
    не быть вовсе — тогда всё работает ровно так, как работало до него.

    Причин «не было» четыре, и они **разные**: не просили, нечем звать, нечем
    платить, не ответил. Пишем поэтому каждую своим словом, а не общим
    пустым словарём: страница без второго мнения потом объясняет, почему его
    нет, — иначе выключенная галочка и отвалившийся сервис на экране
    неразличимы.
    """
    if not asked:
        return {"reader": "mathpix", "error": "not_asked"}
    if not mathpix.configured():
        return {"reader": "mathpix", "error": "not_configured"}
    if not has_budget(school):
        return {"reader": "mathpix", "error": "no_budget"}

    second = mathpix.read_strip(image, media_type=media_type)
    if not second.get("error"):
        _charge(school, user, work, AiSpend.SCAN_SECOND, prices.MATHPIX, 0, 0)
    return second


def arbitrate(
    school,
    user,
    work,
    image: bytes,
    *,
    media_type: str,
    candidates: list[str] | None,
    rivals: list[dict],
    reading: dict,
    second: dict,
) -> dict:
    """
    Читатели разошлись — позвать третьего, дорогого и внимательного.

    Он видит ту же картинку и обе версии, и его ответ становится чтением
    страницы. Пометка о расхождении при этом **не снимается**: спор был, и
    человек о нём узнает — арбитраж улучшает догадку, а не заменяет глаза.

    Модель арбитра — настройка, и пустая значит «не звать»: расхождение тогда
    просто помечается. Это честный выбор школы, у которой каждая страница
    стоит денег, а не забытая ветка.
    """
    from django.conf import settings

    arbiter = getattr(settings, "SCAN_ARBITER_MODEL", "")
    # Цена спрашивается **до** вызова, и неизвестная модель тут не отказ, а
    # пропуск: опечатка в `.env` иначе стоила бы страницы, за которую уже
    # заплачено первому читателю. Сторож на умолчание есть в тестах.
    if not arbiter or not prices.known(arbiter) or not has_budget(school):
        return reading

    better, input_tokens, output_tokens = read_header(
        image,
        media_type=media_type,
        candidates=candidates,
        model=arbiter,
        rivals=rivals,
    )
    _charge(
        school, user, work, AiSpend.SCAN_REREAD, arbiter, input_tokens, output_tokens
    )
    better["model"] = arbiter
    # Кем перечитано — видно человеку рядом с обеими версиями: без этого
    # «страница спорная, но прочитана вот так» выглядит необъяснимо.
    second["arbiter"] = arbiter
    return better


def _charge(school, user, work, purpose, model, input_tokens, output_tokens):
    AiSpend.objects.create(
        school=school,
        user=user,
        work=work,
        purpose=purpose,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_micros=prices.cost_micros(model, input_tokens, output_tokens),
    )


def questions_and_charge(
    *,
    school,
    user,
    work,
    image: bytes,
    media_type: str = "image/jpeg",
    model: str = prices.SONNET,
) -> list:
    """Прочитать лист условий и записать трату. Та же дверь, что у шапок."""
    check_budget(school)
    found, input_tokens, output_tokens = read_questions(
        image, media_type=media_type, model=model
    )
    _charge(
        school, user, work, AiSpend.SCAN_QUESTIONS, model, input_tokens, output_tokens
    )
    return found
