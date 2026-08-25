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

# Кто может прочитать шапку целиком — имя и клетки. Их **двое**, и между ними
# человек выбирает одним вопросом.
#
# Порядок предпочтения, он же порядок падения. Первой — языковая модель: она
# знает, что перед ней имя, и держит слово целиком, а распознаватель видит
# буквы по одной и на рукописном ошибается заметно чаще.
#
# **Mathpix сюда не входит, и это упрощение, купленное опытом.** Читателей было
# трое, и каждый мог оказаться на любом месте: выбор имени, выбор клеток,
# запасной путь у обоих. Развилок от этого стало больше, чем случаев, которые
# они разбирают, — на экране вышло два вопроса с шестью ответами, а из ответов
# половина отличалась только ценой одного лишнего запроса. Mathpix теперь одно
# и только одно: **второй свидетель**, которого зовут поверх первого читателя.
NAME_READERS = (ANTHROPIC, YANDEX)

# Все, кого этот код умеет звать, — в одном месте. Роли у них разные, и списков
# по ролям было бы два; но есть вопросы, которые задаются **каждому** читателю
# независимо от роли: до кого не достучались, кому обнулили ключ на прогоне.
# Пока такого списка не было, эти вопросы задавались по `NAME_READERS`, и в тот
# день, когда Mathpix оттуда ушёл, помощник тестов молча перестал забывать его
# вердикт — а тесты стали зависеть от порядка запуска.
READERS = (ANTHROPIC, YANDEX, MATHPIX)


# Почему читателя нельзя позвать. Слово, а не флаг: «ключей не задали» и «не
# дозвонились» — разные беды, и лечатся они разными руками. Первая — настройкой
# контура, вторая проходит сама.
NOT_CONFIGURED = "not_configured"
UNREACHABLE = "unreachable"


def readers_state(order) -> list[dict]:
    """
    Все читатели из списка — каждый со своим состоянием и причиной отказа.

    Отвечает на вопрос экрана целиком, а не наполовину. Отдавался раньше
    список тех, кого позвать можно, и недоступный читатель из него просто
    исчезал — а вместе с ним исчезал и сам вопрос: контур без ключей Mathpix
    выглядел как контур, где Mathpix не бывает вовсе. Пропавшая строка себя не
    объясняет, заглушённая объясняет; и второе важнее, потому что чинится это
    настройкой, а не гаданием.

    «Настроен» и «отвечает» — разные вопросы, и второй спрашивается у самой
    сети. Читателя, о котором только что выяснили, что до него не достучаться,
    не предлагают и не пробуют: ждать его повторно значит тратить по двадцать
    секунд на каждой странице пачки.
    """
    able = {
        ANTHROPIC: client.configured(),
        YANDEX: yandex.configured(),
        MATHPIX: mathpix.configured(),
    }
    state = []
    for one in order:
        why = ""
        if not able[one]:
            why = NOT_CONFIGURED
        elif not reach.reachable(one):
            why = UNREACHABLE
        state.append({"name": one, "able": not why, "why": why})
    return state


def name_readers() -> list[str]:
    """
    Кем этот контур умеет читать имя, в порядке предпочтения.

    Спрашивает это не экран, а само чтение: экрану нужны все читатели с
    причинами (`readers_state`), а чтению — тот, кого можно позвать прямо
    сейчас.
    """
    return [one["name"] for one in readers_state(NAME_READERS) if one["able"]]


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
    second: bool = True,
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

    Вопросов человеку два, и оба простые. `reader` — **кто читает шапку**:
    языковая модель или Yandex; пустой значит «кем умеете», и тогда берётся
    первый доступный по `NAME_READERS`. `second` — **звать ли поверх него
    Mathpix**: он удваивает цену пачки, а нужен не всегда — у стопки, где имена
    вписаны печатными буквами, спорить не о чем.

    Клетки читает тот же, кто прочитал шапку, если Mathpix не позвали. Это и
    есть всё устройство: раньше читателя клеток выбирали отдельно, и от этого
    приходилось различать три вида «того же читателя» — а решений у человека
    от этого больше не становилось.

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

    cells = second_reading(
        school,
        user,
        work,
        image,
        media_type,
        asked=second,
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
    school,
    user,
    work,
    image: bytes,
    media_type: str,
    *,
    asked: bool = True,
) -> dict:
    """
    Позвать второго свидетеля — Mathpix — и записать трату. Не позвался — не беда.

    Возвращается всегда словарь: `error` внутри значит «второго чтения по этой
    странице нет», и это законное состояние, а не отказ. Ключей может не быть
    вовсе — тогда всё работает так, как работало до него: шапку читает один, и
    клетки берутся у него же.

    Причин «не было» несколько, и они **разные**: не просили, нечем звать,
    нечем платить, не дозвонились, ответил отказом. Пишем каждую своим словом,
    а не общим пустым словарём: страница без второго чтения потом объясняет,
    почему его нет, — иначе снятая галочка и отвалившийся сервис на экране
    неразличимы.

    **Свидетель тут один, и это упрощение, купленное опытом.** Читателем клеток
    мог быть и Yandex, и от этого приходилось различать «тот же читатель по
    имени» и «тот же по вызову», а человеку — выбирать читателя клеток отдельно
    от читателя имени. Развилок вышло больше, чем случаев. Теперь клетки читает
    тот же, кто прочитал шапку, а Mathpix — прибавка поверх него, и вопрос про
    него один: звать или нет.
    """
    if not asked:
        return {"reader": "", "error": "not_asked"}
    if not mathpix.configured():
        return {"reader": MATHPIX, "error": "not_configured"}
    # До него могли не достучаться минуту назад — тогда не ждём снова. Без этой
    # проверки каждая страница пачки честно висела двадцать секунд на читателе,
    # которого нет в сети: одиннадцать минут на пачку из тридцати четырёх
    # листов, и снаружи это неотличимо от зависшего чтения.
    if not reach.reachable(MATHPIX):
        return {"reader": MATHPIX, "error": "unreachable"}
    if not has_budget(school):
        return {"reader": MATHPIX, "error": "no_budget"}

    answer = mathpix.read_strip(image, media_type=media_type)
    if answer.get("error") == "unreachable":
        reach.remember_unreachable(MATHPIX)
    if not answer.get("error"):
        _charge(school, user, work, AiSpend.SCAN_SECOND, prices.MATHPIX, 0, 0)
    return answer


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
                reach.remember_unreachable(ANTHROPIC)
                unreachable = True
                continue
            _charge(school, user, work, purpose, model, input_tokens, output_tokens)
            data["reader"] = ANTHROPIC
            data["model"] = model
            return data

        module, priced = (yandex, prices.YANDEX)
        data = module.read_strip(image, media_type=media_type)
        if data.get("error"):
            # Запоминается только «не дозвонились»: остальные отказы приходят
            # мгновенно и ждать себя не заставляют, а этот стоит двадцати
            # секунд на каждой странице.
            if data["error"] == "unreachable":
                reach.remember_unreachable(one)
                unreachable = True
            continue
        _charge(school, user, work, purpose, priced, 0, 0)
        data["model"] = priced

        # Полоска — две разные вещи на одной картинке, и у Yandex под них две
        # модели: рукописную строку имени читает `handwritten`, сетку баллов —
        # `table`. Одной моделью не выходит, и это выяснила живая пачка:
        # `handwritten` разобрал имена на всех страницах и не увидел почти ни
        # одной клетки.
        #
        # Поэтому «Yandex прочитал шапку» — это **два запроса**, и второй его
        # же, а не чужой. Наружу это одно чтение одним читателем: развилка тут
        # про модель сервиса, а не про выбор человека, и вытаскивать её на
        # экран значит спрашивать про то, чего человек не решает.
        cells = _yandex_cells(school, user, work, image, media_type, purpose)
        if cells:
            data["values"] = cells
        return data

    # Читателей нет вовсе и ключа нет — это «не настроено», а не «не
    # достучаться»: достукиваться не до чего. Разница не словесная, чинят их
    # в разных местах, и сказать «сеть закрыта» тому, кто просто не вписал
    # ключ, значит отправить его искать несуществующую беду.
    if not order and not client.configured():
        api_error(
            Codes.AI_KEY_MISSING,
            "Reading scans is not set up: the service has no reader.",
        )
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


def _yandex_cells(school, user, work, image, media_type, purpose) -> list | None:
    """
    Клетки той же полоски моделью для таблиц. Не вышло — не беда.

    Молчание тут законно: имя уже прочитано, страница есть, а баллы человек
    видит на бумаге и впишет сам. Ронять из-за них всю страницу значило бы
    менять «прочитали хуже» на «не прочитали вовсе».

    Потолок спрашивается отдельно: первый запрос мог оказаться последним, на
    который хватало.
    """
    if not has_budget(school):
        return None
    answer = yandex.read_cells(image, media_type=media_type)
    if answer.get("error"):
        if answer["error"] == "unreachable":
            reach.remember_unreachable(YANDEX)
        return None
    _charge(school, user, work, purpose, prices.YANDEX, 0, 0)
    return answer.get("values")


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
