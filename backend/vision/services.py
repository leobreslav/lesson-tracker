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

from config.errors import Codes, api_error, api_unavailable

from . import agreement, client, mathpix, merge, prices, reach, yandex
from .client import read_header, read_questions
from .models import AiSpend

# Кто может читать имя. Имена человеческие, а не названия моделей: по ним
# человек выбирает на экране, и версии в них нет — сменить `claude-haiku-4-5`
# на следующую значит поправить `.env`, а не переучивать учителя.
ANTHROPIC = "anthropic"
YANDEX = "yandex"
MATHPIX = "mathpix"

# Порядок предпочтения, он же порядок падения. Первой — языковая модель: она
# знает, что перед ней имя, и держит слово целиком, а распознаватель видит
# буквы по одной и на рукописном ошибается заметно чаще. Последним — Mathpix:
# в этом списке он не выбор, а «хоть что-то вместо ничего».
NAME_READERS = (ANTHROPIC, YANDEX, MATHPIX)


def name_readers() -> list[str]:
    """
    Кем этот контур умеет читать имя, в порядке предпочтения.

    Спрашивает это экран, чтобы предложить выбор, и спрашивает не из
    любопытства: предложить читателя, которого нет, значит соврать, а узнать
    об этом отказом на первой странице пачки — плохой способ выяснять состав.
    """
    able = {
        ANTHROPIC: client.configured() and reach.model_reachable(),
        YANDEX: yandex.configured(),
        MATHPIX: mathpix.configured(),
    }
    return [one for one in NAME_READERS if able[one]]


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
    reader: str = "",
    asked_second: bool = True,
) -> dict:
    """
    Прочитать полоску и записать трату. Одна дверь: считать, не заплатив, нельзя.

    Модель по умолчанию берётся из настроек (`SCAN_HEADER_MODEL`), а не зашита
    здесь: на цифрах в отдельных квадратиках разницы между моделями нет, а на
    рукописном имени есть — и стоит она втрое. Проверять это надо на живой
    пачке, и переключение должно стоить строки в `.env`, а не правки кода.

    **Читателей двое, и сильны они в разном.** Имя и фамилию лучше читает
    языковая модель: она знает, что перед ней имя, и держит слово целиком.
    Клетки с баллами лучше читает распознаватель: плитки — это таблица, а
    цифра в квадратике требует зрения, а не понимания, и модель на них
    сбивается со счёта. Поэтому чтение страницы **собирается из двух**: имя от
    одного, клетки от другого (`merge.py`).

    **Пометка о расхождении при этом остаётся.** Приоритет решает, что
    записать; пометка — о чём сказать человеку. Правило «имя от модели» не
    делает модель непогрешимой — оно говорит, чья версия правдоподобнее.
    Убери мы пометку, и молчаливая ошибка вернулась бы ровно там, ради чего
    второго читателя заводили.

    **Чужого чтения читателям не показывают.** Закон проекта выведен дважды и
    дорого: подсказанное подставляется вместо увиденного. Подскажи мы одному
    ответ другого — их согласие перестало бы что-либо значить, а вместе с ним
    и вся затея. Оба читают вслепую, и сводит их только правило.

    **Порядок вызовов не случаен: сперва имя, потом клетки.** Чтение имени —
    это то, без чего страницы нет вовсе; клетки правит человек на шаге
    проверки. Упрись мы в потолок или в отказ сети, потерять хочется второе, а
    не первое.

    `reader` — выбор человека: кем читать имя. Пустой значит «кем умеете»,
    и тогда берётся первый доступный по `NAME_READERS`. `asked_second` — его
    же решение, звать ли Mathpix за клетками: он удваивает цену пачки, а нужен
    не всегда.

    **Выбор человека мы уступаем только вниз.** Не достучались до модели —
    читаем тем, кто ближе и дешевле, и говорим об этом. Обратно нет: подменить
    выбранный местный распознаватель дорогим заграничным чтением значит
    потратить чужие деньги вместо того, кто их считает.
    """
    from django.conf import settings

    model = model or getattr(settings, "SCAN_HEADER_MODEL", prices.HAIKU)
    check_budget(school)

    names = name_reading(
        school,
        user,
        work,
        image,
        media_type,
        candidates=candidates,
        model=model,
        purpose=purpose,
        chosen=reader,
    )

    # Того же читателя второй раз не зовут: он ответит то же самое, а деньги
    # спишутся дважды. Случается это, когда имя читал Mathpix, — то есть
    # тогда, когда больше читать было некому.
    cells = (
        {"reader": MATHPIX, "error": "same_reader"}
        if names.get("reader") == MATHPIX
        else second_reading(school, user, work, image, media_type, asked=asked_second)
    )
    if cells.get("error"):
        names["second"] = cells
        return names

    # Спор записывается **до** слияния и потом не пересчитывается. Приоритет
    # решает, что записать; пометка — о чём сказать человеку. Посчитай мы его
    # после, спор исчезал бы ровно там, где правило встало на чью-то сторону,
    # то есть на каждой спорной странице.
    cells["differs"] = agreement.compare(names, cells)

    reading = merge.take(names_from=names, cells_from=cells)
    reading["second"] = cells
    return reading


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


def name_reading(
    school,
    user,
    work,
    image: bytes,
    media_type: str,
    *,
    candidates: list[str] | None,
    model: str,
    purpose: str,
    chosen: str,
) -> dict:
    """
    Прочитать имя. Кем — решает человек; чем закончить, если он не смог, — мы.

    Отличается это от `second_reading` не вызовом, а **ролью**: там читатель
    свидетель, которого можно не звать и чей отказ ничего не ломает, здесь он
    единственный, и его молчание — это непрочитанная страница. Поэтому и
    отказы тут громкие: страница, тихо вернувшаяся пустой, выглядела бы как
    «шапки не разобрать», то есть свалила бы на бумагу вину сети.

    **Уступаем выбор человека только вниз** — от модели к тому, кто ближе и
    дешевле. Обратно нет: выбрал он местный распознаватель, а мы бы молча
    сходили за границу за его деньги. Поэтому падение с первого места
    разрешено, а подъём на него — нет.

    Трата записывается поводом `SCAN_HEADER` независимо от того, кто читал:
    повод отвечает на вопрос «за что заплачено», а заплачено за чтение шапки.
    Кем именно — сказано в поле `model`, и по нему в журнале видно, что читал
    не тот, кто обычно.

    Отказы идут дверью «не сейчас» (503), а не «вы ошиблись» (400): человек
    ничего не напутал и перепечатыванием ничего не исправит — та же причина,
    по которой так отвечает недоступное хранилище.
    """
    order = name_readers()
    if chosen in order:
        order = [chosen] + [one for one in order if one != chosen]

    # Чем кончился обход, решает **последнее слово**, а не длина списка:
    # «до модели не достучаться» и «читатель промолчал» чинятся по-разному, и
    # общий отказ на оба отправил бы человека искать не там.
    unreachable = False

    for number, one in enumerate(order):
        # Подъём к модели после чужого выбора запрещён — см. докстринг.
        if number and one == ANTHROPIC:
            break

        if one == ANTHROPIC:
            try:
                data, input_tokens, output_tokens = read_header(
                    image,
                    media_type=media_type,
                    candidates=candidates,
                    model=model,
                )
            except client.ModelUnreachable:
                # Неудавшийся вызов не стоил ничего: платят за токены, а
                # токенов не было. Записать трату значило бы взять деньги за
                # молчание.
                reach.remember_unreachable()
                unreachable = True
                continue
            _charge(school, user, work, purpose, model, input_tokens, output_tokens)
            data["reader"] = ANTHROPIC
            data["model"] = model
            return data

        module, priced = (
            (yandex, prices.YANDEX) if one == YANDEX else (mathpix, prices.MATHPIX)
        )
        data = module.read_strip(image, media_type=media_type)
        if data.get("error"):
            continue
        _charge(school, user, work, purpose, priced, 0, 0)
        data["model"] = priced
        return data

    if unreachable or not order:
        api_unavailable(
            Codes.AI_UNREACHABLE,
            "This server cannot reach the language model, and no other reader "
            "could take its place.",
            tried=order,
        )
    api_unavailable(
        Codes.SCAN_READER_SILENT,
        "No reader answered.",
        tried=order,
    )


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
    try:
        found, input_tokens, output_tokens = read_questions(
            image, media_type=media_type, model=model
        )
    except client.ModelUnreachable:
        # Заменить тут некем: распознаватель видит буквы, а не задачи, и
        # шкалу из листа условий не соберёт. Значит честный отказ, а не
        # пустая шкала, молча уехавшая в работу.
        reach.remember_unreachable()
        api_unavailable(
            Codes.AI_UNREACHABLE,
            "This server cannot reach the language model, and reading a "
            "question paper needs one.",
        )
    _charge(
        school, user, work, AiSpend.SCAN_QUESTIONS, model, input_tokens, output_tokens
    )
    return found
