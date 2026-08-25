"""
Разбор пачки: чья страница и что на ней написано.

Читает страницы модель, а раскладывает по ученикам этот модуль — и делает это
**независимо от порядка**. Порядок в PDF ничего не гарантирует: листы сдают
как попало, сканируют как попало, а один ученик мог взять три листа, второй
один. Правил ровно два, и оба проверяемы глазами:

1. **страница с однозначным именем** отходит своему ученику;
2. **остальные** пристраиваются по покрытию задач: страница с баллами за
   Q4..Q6 влезает туда, где этих задач ещё нет.

Что не разложилось однозначно, идёт человеку с суженными кандидатами. Это не
запасной путь, а главный: чужая контрольная, приписанная однокласснику,
дороже любой экономии на вопросах.

Похожесть считает `difflib` из стандартной библиотеки, а не rapidfuzz:
сравниваются короткие имена, разница в качестве незаметна, а зависимость
осталась бы навсегда.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Ниже этого сходства (0..100) имя вообще не считается похожим.
NEAR = 70
# Однозначным считается имя, которое похоже сильно и заметно сильнее прочих.
SURE = 85
MARGIN = 12

QUESTIONS = 15
CELLS = 16


def fold(first: str, surname: str) -> str:
    """
    Написанное на листе -> ключ памяти курса.

    Сравнимый вид, а не красивый: нижний регистр, `ё` как `е`, лишние пробелы
    прочь. Имя и фамилия склеиваются **в порядке чтения**, потому что помнится
    не имя человека, а то, что увидел читатель, — а он и графы путает, и
    кириллицу пишет латиницей.

    Пустое написание ключом не бывает: страница без имени похожа на любую
    другую такую же, и запомнить по ней ничего нельзя.
    """
    words = f"{first or ''} {surname or ''}".lower().replace("ё", "е").split()
    return " ".join(words)


def similarity(one: str, two: str) -> float:
    one, two = (one or "").strip().lower(), (two or "").strip().lower()
    if not one or not two:
        return 0.0
    return SequenceMatcher(None, one, two).ratio() * 100


# Уменьшительное имя -> полные, к которым оно относится.
#
# **Список нарочно короткий и нарочно односторонний.** В нём только те пары,
# где одно имя — заведомо уменьшительное от другого: «Соня» и «Софья» это один
# человек, а «Александр» и «Александра» — двое, и здесь их нет. Соблазн
# написать «схлопнуть похожие имена» велик, но схлопывание работает в обе
# стороны: собрав вместе Александра и Александру, мы получили бы двух учеников
# класса, неразличимых по имени, — то есть ровно ту молчаливую ошибку, ради
# которой всё это и делается. Двусмысленности допускаются только там, где
# короткое имя честно принадлежит нескольким полным («Саша», «Женя»): такой
# лист поднимет обоих кандидатов и уйдёт к человеку.
#
# Буква «ё» приводится к «е» при поиске, поэтому здесь она не нужна.
SHORT_NAMES = {
    "саша": ("александр", "александра"),
    "шура": ("александр", "александра"),
    "аля": ("алевтина", "алина"),
    "алеша": ("алексей",),
    "леша": ("алексей",),
    "настя": ("анастасия",),
    "ася": ("анастасия", "анна"),
    "аня": ("анна",),
    "тоня": ("антонина",),
    "тема": ("артем",),
    "боря": ("борис",),
    "валя": ("валентин", "валентина"),
    "лера": ("валерия", "валерий"),
    "варя": ("варвара",),
    "вася": ("василий",),
    "вера": ("вера",),
    "вика": ("виктория",),
    "витя": ("виктор",),
    "вова": ("владимир",),
    "володя": ("владимир",),
    "влад": ("владислав", "владимир"),
    "слава": ("вячеслав", "святослав", "ярослав"),
    "галя": ("галина",),
    "гриша": ("григорий",),
    "даша": ("дарья",),
    "дима": ("дмитрий",),
    "митя": ("дмитрий",),
    "женя": ("евгений", "евгения"),
    "катя": ("екатерина",),
    "лена": ("елена",),
    "лиза": ("елизавета",),
    "зина": ("зинаида",),
    "ваня": ("иван",),
    "илюша": ("илья",),
    "ира": ("ирина",),
    "кира": ("кира",),
    "костя": ("константин",),
    "ксюша": ("ксения",),
    "леня": ("леонид",),
    "люба": ("любовь",),
    "люда": ("людмила",),
    "макс": ("максим",),
    "марго": ("маргарита",),
    "рита": ("маргарита",),
    "маша": ("мария",),
    "миша": ("михаил",),
    "надя": ("надежда",),
    "коля": ("николай",),
    "оля": ("ольга",),
    "паша": ("павел",),
    "петя": ("петр",),
    "поля": ("полина",),
    "рома": ("роман",),
    "сережа": ("сергей",),
    "соня": ("софия", "софья"),
    "степа": ("степан",),
    "таня": ("татьяна",),
    "тимоша": ("тимофей",),
    "федя": ("федор",),
    "юля": ("юлия",),
    "яна": ("яна",),
}


def _plain(name: str) -> str:
    return (name or "").strip().lower().replace("ё", "е")


def short_for(one: str, two: str) -> bool:
    """Одно из имён — уменьшительное от другого."""
    one, two = _plain(one), _plain(two)
    if not one or not two:
        return False
    return two in SHORT_NAMES.get(one, ()) or one in SHORT_NAMES.get(two, ())


def like_name(written: str, known: str) -> float:
    """
    Насколько написанное похоже на имя из списка класса.

    Побуквенное сходство слепо к тому, что «Соня» — это Софья: общих букв в
    них три из пяти, и лист уходил к человеку, хотя решить его могла машина.
    Уменьшительное имя поэтому считается полным совпадением, а не «похоже
    наполовину»: это не опечатка, а другое имя того же человека.
    """
    return 100.0 if short_for(written, known) else similarity(written, known)


@dataclass(frozen=True)
class Person:
    """Ученик курса глазами разбора: имя, фамилия и id."""

    id: int
    first: str
    last: str

    @property
    def full(self) -> str:
        return " ".join(x for x in (self.first, self.last) if x).strip()


@dataclass
class Page:
    """Прочитанная страница."""

    index: int
    first: str = ""
    surname: str = ""
    guess: str = ""
    headerless: bool = False
    ours: bool = False
    cells: list = field(default_factory=lambda: [None] * CELLS)
    student_id: int | None = None
    decided_by_human: bool = False
    # Что увидел на той же полоске второй читатель и в чём он не сошёлся с
    # первым (`differs`). Пустой словарь — второго читателя не было.
    second: dict = field(default_factory=dict)
    # Кем оказалось **это же написание** в прошлый раз (`works.ScanAlias`).
    # Заполняется там, где живёт база, — разбор остаётся чистыми функциями и
    # ходит только по тому, что ему дали.
    alias_id: int | None = None

    @property
    def named(self) -> bool:
        return bool((self.first or "").strip() or (self.surname or "").strip())

    @property
    def answered(self) -> set:
        """Номера задач (с нуля), за которые на странице стоит балл."""
        return {q for q in range(QUESTIONS) if self.cells[q] is not None}

    @property
    def page_sum(self) -> int | None:
        return self.cells[QUESTIONS] if len(self.cells) > QUESTIONS else None


def candidates_for(page: Page, roster: list[Person]) -> list[tuple[Person, float]]:
    """
    Кандидаты по написанному на листе, от самого похожего.

    **В какое поле бланка попало слово — не свидетельство.** Сравнение было
    привязано к полю намертво: имя сверялось только с именем, фамилия только
    с фамилией. На живой пачке этого хватило, чтобы лист, подписанный
    «Гусев» в графе имени, не сравнился с фамилией Гусева вовсе — и получил в
    кандидаты случайного человека, чьё **имя** оказалось похоже на «Гусев»
    больше прочих. Причин, по которым слово попадает не в ту графу, две, и обе
    обычные: подписываются «фамилия имя», а модель ещё и может перепутать
    графы местами.

    Поэтому одно заполненное поле сверяется с **обоими** — и с именем, и с
    фамилией; два заполненных считаются и прямо, и накрест, а берётся лучшее
    из двух прочтений. Среднее по паре остаётся: одно совпавшее поле при
    втором чужом — это не совпадение.
    """
    scored = []
    for person in roster:
        # Это написание уже разбирал человек, и назвал вот этого. Свидетельство
        # прямое: не «похоже на», а «в прошлый раз оказалось им». Побуквенное
        # сходство тут не при чём — так узнаются и «Ксюша», и `Cocramol`.
        if page.alias_id is not None and person.id == page.alias_id:
            scored.append((person, 100.0))
            continue
        first, last = page.first.strip(), page.surname.strip()
        if first and last:
            direct = (like_name(first, person.first) + like_name(last, person.last)) / 2
            crossed = (like_name(first, person.last) + like_name(last, person.first)) / 2
            score = max(direct, crossed)
        else:
            written = first or last
            score = max(
                like_name(written, person.first), like_name(written, person.last)
            )
        scored.append((person, score))
    scored.sort(key=lambda pair: -pair[1])
    return scored


def own_owner(page: Page, roster: list[Person]) -> int | None:
    """
    Кого лист называет сам — и только когда называет однозначно.

    Это то же решение, что принимает `group` для отдельной страницы, вынутое
    отдельно: пакетной раскладке оно нужно, чтобы отличить «лист молчит и
    положен по соседству» от «лист подписан, и подписан не тем именем».
    """
    if not page.named:
        return None

    scored = {person.id: score for person, score in candidates_for(page, roster)}
    opinion = guessed(page, roster)
    if opinion:
        scored[opinion.id] = max(scored.get(opinion.id, 0.0), SURE)

    people = {person.id: person for person in roster}
    best = sorted(
        ((people[pk], score) for pk, score in scored.items()), key=lambda pair: -pair[1]
    )
    return best[0][0].id if _sure(best) else None


def split_off_signed(packets: list[Packet], roster: list[Person]) -> list[Packet]:
    """
    Лист, подписанный своим именем, принадлежит тому, кто подписался.

    Пакет — догадка о группировке: границы ему рисуют листы условий, а внутри
    голосуют все листы разом, и одно уверенное имя решает за всех. Пока это
    работало на пачке, разрезанной по-настоящему, всё сходилось; на живой
    пачке, разрезанной по ошибке, этого хватило, чтобы страница, подписанная
    «Кирилл Орлов», уехала Варваре Мироновой — её имя стояло на первом листе
    того же пакета.

    Подпись — свидетельство сильнее любой группировки, поэтому такой лист
    забирают из пакета и отдают тому, кто на нём написан. Молчать об этом
    нельзя: страница несёт `signed_apart`, и человек видит, что её переложили.

    Решение человека не пересматривается: сказанное им сильнее и подписи.
    """
    out: list[Packet] = []
    for packet in packets:
        if packet.decided_by_human:
            out.append(packet)
            continue

        stays: list[Page] = []
        moved: dict[int, list[Page]] = {}
        for page in packet.pages:
            mine = own_owner(page, roster)
            if mine is not None and mine != packet.student_id:
                moved.setdefault(mine, []).append(page)
            else:
                stays.append(page)

        packet.pages = stays
        # Пакет, оставшийся без единого листа решения, — это его условия и
        # ничего больше. Условия ездят с работой, поэтому они уходят вместе с
        # листами, если ушли все и к одному человеку.
        if not stays and len(moved) == 1 and packet.conditions:
            only = next(iter(moved))
            out.append(
                Packet(
                    conditions=packet.conditions,
                    pages=moved.pop(only),
                    student_id=only,
                    signed_apart=[],
                )
            )
        elif stays or packet.conditions:
            out.append(packet)

        for student_id, pages in moved.items():
            out.append(
                Packet(
                    pages=pages,
                    student_id=student_id,
                    signed_apart=[page.index for page in pages],
                )
            )
    return out


def top_candidates(page: Page, roster: list[Person], limit: int = 3) -> list[int]:
    """
    Кого предложить человеку по этой странице — лучшие, от самого похожего.

    Считается **по странице**, а не по пакету, и это не мелочь. Кандидаты
    пакета есть только тогда, когда пакет не решился целиком: у решённого их
    нет вовсе, а у собранного постранично — тем более. Экран показывал их
    как есть, и на пустом списке падал на запасной путь «первые шесть по
    списку класса». Выглядело это дико: страница подписана «Миронова», а
    предлагают Белова, Волкову и Гусева — то есть тех, кого на ней точно нет.

    Мнение модели (`guess`) поднимается на самый верх, если оно сошлось с
    составом курса: это свидетельство того же листа, а не отдельный голос, и
    ровно так же оно учитывается в голосовании пакета.
    """
    if not page.named:
        return []

    scored = {person.id: score for person, score in candidates_for(page, roster)}
    opinion = guessed(page, roster)
    if opinion:
        scored[opinion.id] = max(scored.get(opinion.id, 0.0), SURE)

    best = sorted(scored.items(), key=lambda pair: -pair[1])
    return [pk for pk, _ in best[:limit]]


def guessed(page: Page, roster: list[Person]) -> Person | None:
    """
    Кого модель назвала из списка. Строка сверяется с составом, а не берётся
    на веру: модель могла написать что угодно, а мы отвечаем за то, что этот
    человек в курсе есть.
    """
    if not page.guess:
        return None
    best, score = None, 0.0
    for person in roster:
        near = similarity(page.guess, person.full)
        if near > score:
            best, score = person, near
    return best if score >= SURE else None


def _sure(scored: list[tuple[Person, float]]) -> bool:
    """Похоже сильно и заметно сильнее второго — иначе это не однозначность."""
    if not scored or scored[0][1] < SURE:
        return False
    if len(scored) < 2:
        return True
    return scored[0][1] - scored[1][1] >= MARGIN


@dataclass
class Packet:
    """
    Работа одного ученика: его листы и его условия.

    Пакет — единица решения, а не страница. Спросить у человека «чей это
    пакет» надо один раз, а не восемь; и ошибиться в имени на одном листе из
    восьми не страшно, если остальные семь согласны.
    """

    conditions: list = field(default_factory=list)
    pages: list = field(default_factory=list)
    student_id: int | None = None
    candidates: list = field(default_factory=list)
    decided_by_human: bool = False
    # страницы, положенные сюда **не по своему имени**, а по свободным задачам
    # или по соседу. Догадка законная, но это догадка, и человек о ней узнаёт
    by_fit: list = field(default_factory=list)
    # страницы, забранные из чужого пакета по собственной подписи
    signed_apart: list = field(default_factory=list)
    # пакет назван **вычетом**, а не чтением: остальные разобраны, и он
    # достался тому, кто остался. Свидетельство это сильное, но косвенное, и
    # человек о нём узнаёт — как и о догадке по соседству
    by_elimination: bool = False
    # страницы, повторившие задачи, уже закрытые в этом блоке. Покрытие задач
    # больше не решает, чей это лист, — оно **сомневается**: два листа с одной
    # и той же задачей значат, что в блок затесался чужой
    overlaps: list = field(default_factory=list)

    @property
    def all_pages(self) -> list:
        """Условия впереди, потом решения — в том порядке, в каком лежали."""
        return sorted(self.conditions + self.pages, key=lambda page: page.index)


READ = "read"
CONDITIONS = "conditions"
UNREADABLE = "unreadable"


def classify(pages: list[Page]) -> dict:
    """
    Что это за страница: лист решения, лист условий или наш лист, который не
    прочитался.

    Решается **по всей пачке**, а не по странице отдельно, и вот почему. Метка
    в углу говорит «это наш бланк», и по ней «условия» отличаются от «плохого
    фото нашего листа» наверняка. Но метки может не оказаться ни на одном
    листе — печатали со старого бланка, принтер съел угол, скан обрезал низ, —
    и тогда доверять ей значит объявить условиями всю пачку. Поэтому: **нет
    метки ни у кого — сигнала нет**, и работает прежнее правило «шапка
    прочиталась или нет».
    """
    trusted = any(page.ours for page in pages)

    kinds = {}
    for page in pages:
        # Сказанное человеком не пересматривается — и здесь тоже. Отдал
        # страницу ученику значит «это его работа», чем бы её ни счёл поиск
        # шапки. Пока этого не было, страница с плохо снятой шапкой оставалась
        # листом условий даже после того, как её назначили руками: в раскладку
        # такая не попадает, и её баллы не ехали никуда.
        if page.decided_by_human and page.student_id is not None:
            kinds[page.index] = READ
        elif not page.headerless:
            kinds[page.index] = READ
        elif trusted and page.ours:
            kinds[page.index] = UNREADABLE
        else:
            kinds[page.index] = CONDITIONS
    return kinds


def condition_runs(pages: list[Page], kinds: dict) -> list[list[Page]]:
    """Непрерывные ряды листов условий, в порядке следования."""
    runs: list[list[Page]] = []
    previous = False
    for page in sorted(pages, key=lambda one: one.index):
        if kinds[page.index] == CONDITIONS:
            if not previous:
                runs.append([])
            runs[-1].append(page)
            previous = True
        else:
            previous = False
    return runs


def _work_follows(run: list[Page], pages: list[Page], kinds: dict) -> bool:
    """Есть ли за этим рядом условий хоть один лист решения."""
    after = run[-1].index
    return any(
        page.index > after and kinds[page.index] != CONDITIONS for page in pages
    )


def split_by_conditions(pages: list[Page], kinds: dict) -> list[Packet] | None:
    """
    Разрезать пачку по рядам листов условий.

    Условия раздают перед работой, и непрерывный ряд таких листов значит
    «дальше следующий ученик». Свидетельство надёжнее любого почерка: оно не
    зависит ни от чтения, ни от того, вписал ли ученик фамилию.

    Возвращает `None`, если рядов меньше двух: делить нечем. Один ряд — это не
    разметка, а общие условия на всю пачку, и с ними разбирается `arrange`.

    **Ряд в самом конце пачки границей не считается — за ним нет работы.**
    Стоило это целой разобранной пачки. Две последние страницы не опознались
    как наш бланк (пустые обороты), попали в «условия» и дали второй ряд — а
    два ряда включают разрезку. Пачка из тридцати четырёх листов стала двумя
    пакетами по тринадцать учеников в каждом, и голосование, у которого один
    пакет — один ученик, отдало пять чужих листов Варваре Мироновой, а
    двадцать шесть не решило вовсе.
    """
    runs = [run for run in condition_runs(pages, kinds) if _work_follows(run, pages, kinds)]
    if len(runs) < 2:
        return None

    packets: list[Packet] = []
    current: Packet | None = None
    previous_conditions = False

    for page in sorted(pages, key=lambda one: one.index):
        conditions = kinds[page.index] == CONDITIONS
        if conditions:
            if not previous_conditions:
                current = Packet()
                packets.append(current)
            current.conditions.append(page)
        else:
            if current is None:
                # пачка начинается с листов решения: у первого ученика условий
                # не оказалось — не повод отказываться от разметки
                current = Packet()
                packets.append(current)
            current.pages.append(page)
        previous_conditions = conditions

    return packets


def vote(packet: Packet, roster: list[Person]) -> list[tuple[Person, float]]:
    """
    Имя пакета — по всем его листам сразу.

    **Не среднее.** Среднее разбавляет: ученик подписывается полностью на
    первом листе, а дальше черкает фамилию как придётся, и один идеально
    прочитанный лист тонул среди двух скомканных — на живой пачке пакет
    Смирновой набирал 81 при пороге 85 и уходил к человеку зря.

    Поэтому берётся **лучшее свидетельство** — самое уверенное чтение среди
    листов, — а согласие остальных добавляет к нему понемногу. Тогда полностью
    выписанное имя решает, а один неверно прочитанный лист не решает ничего:
    он поднимает своего кандидата к тому же порогу, и пакет честно уходит к
    человеку — так и случилось с листом, где «Denis» прочиталось как «Misha».
    """
    people = {person.id: person for person in roster}
    best: dict[int, float] = {}
    support: dict[int, int] = {}

    for page in packet.pages:
        if not page.named:
            continue

        scored = {person.id: score for person, score in candidates_for(page, roster)}
        # мнение модели — свидетельство этого листа, а не отдельный голос
        opinion = guessed(page, roster)
        if opinion:
            scored[opinion.id] = max(scored.get(opinion.id, 0.0), SURE)

        leader = max(scored, key=lambda pk: scored[pk])
        for pk, score in scored.items():
            best[pk] = max(best.get(pk, 0.0), score)
        if scored[leader] >= NEAR:
            support[leader] = support.get(leader, 0) + 1

    out = [
        (people[pk], score + 3 * max(0, support.get(pk, 0) - 1))
        for pk, score in best.items()
    ]
    out.sort(key=lambda pair: -pair[1])
    return out


def group(pages: list[Page], roster: list[Person]) -> tuple[dict, list, set]:
    """
    Разложить страницы по ученикам.

    Возвращает `({index: student_id}, [(index, [кандидаты])], {положенные по
    догадке})`: раскладку, список того, что человек должен решить сам, и
    третьим — страницы, попавшие к ученику **не по своему имени**.

    Третье не мелочь. Измерено на живой пачке: раскладка по свободным задачам и
    соседству ошиблась четыре раза из пятнадцати, и ошиблась молча — безымянный
    лист достался тому, у кого нашлось место. Догадка тут законна (иначе всякий
    неподписанный лист шёл бы к человеку), но выдавать её за прочитанное нельзя.

    Решения человека уважаются: страница, у которой уже стоит `decided_by_human`,
    в раскладку входит как есть и в сомнения не попадает.
    """
    scored = {page.index: candidates_for(page, roster) for page in pages}
    assigned: dict[int, int] = {}
    left: list[Page] = []

    for page in pages:
        if page.decided_by_human:
            if page.student_id is not None:
                assigned[page.index] = page.student_id
            continue
        if page.named and _sure(scored[page.index]):
            assigned[page.index] = scored[page.index][0][0].id
        else:
            left.append(page)

    def covered(student_id: int) -> set:
        out: set = set()
        for page in pages:
            if assigned.get(page.index) == student_id:
                out |= page.answered
        return out

    doubts = []
    by_fit = set()
    for page in left:
        mine = page.answered
        # Пустая страница ни к кому не «подходит» по покрытию: подходит она ко
        # всем, а это и есть неоднозначность.
        fits = [
            student_id
            for student_id in set(assigned.values())
            if mine and not (mine & covered(student_id))
        ]
        if page.named:
            near = {
                person.id
                for person, score in scored[page.index][:3]
                if score >= NEAR
            }
            narrowed = [student_id for student_id in fits if student_id in near]
            fits = narrowed or fits

        # Сосед сверху — свидетельство сильнее покрытия: покрытие говорит
        # «может принадлежать», а соседство — «принадлежит вот этому». Берём
        # только **вплотную** стоящую страницу: пачку могли и перемешать, и
        # чем дальше сосед, тем меньше он значит.
        above = assigned.get(page.index - 1)
        if len(fits) > 1 and above in fits:
            fits = [above]

        if len(fits) == 1:
            assigned[page.index] = fits[0]
            by_fit.add(page.index)
        else:
            suggest = [person.id for person, score in scored[page.index][:3]]
            offered = fits or suggest
            # мнение модели идёт первым: угадывает она заметно лучше, чем
            # нечёткое сравнение искажённого почерка, но решает всё равно человек
            opinion = guessed(page, roster)
            if opinion:
                offered = [opinion.id] + [one for one in offered if one != opinion.id]
            doubts.append((page.index, offered))

    return assigned, doubts, by_fit


def arrange(pages: list[Page], roster: list[Person]) -> list[Packet]:
    """
    Разложить пачку по ученикам — пакетами, откуда бы границы ни взялись.

    Единица решения одна и та же во всех случаях, и это главное здесь: экран,
    тесты и запись не должны знать, как в этот раз лежали условия. Случаев
    ровно три, и все три встречаются в жизни:

    * **условия перед каждой работой** — границы известны точно, а имя пакета
      решается голосованием по всем его листам;
    * **условия один раз в начале пачки** — общие для всех: границ они не
      дают, но в работу каждого ученика попадают. Иначе он открывает свои
      ответы без вопросов;
    * **условий нет вовсе** — работает раскладка по имени и покрытию задач.

    Решения человека уважаются в любом из трёх: сказанное им не пересматривается.
    """
    kinds = classify(pages)
    by_conditions = split_by_conditions(pages, kinds)

    if by_conditions is None:
        runs = condition_runs(pages, kinds)
        # ряд в самом начале — общие условия на всю пачку; всё остальное
        # заблудилось и достанется тому пакету, перед которым лежит
        common: list[Page] = []
        stray: list[Page] = []
        for number, run in enumerate(runs):
            if number == 0 and run[0].index == 0:
                common = run
            else:
                stray += run

        answers = [page for page in pages if kinds[page.index] != CONDITIONS]
        assigned, doubts, by_fit = group(answers, roster)
        doubted = dict(doubts)
        packets = blocks(sorted(answers, key=lambda one: one.index), assigned, doubted, by_fit)

        # общие условия едут в работу каждого ученика; заблудившийся ряд
        # посреди пачки — тому пакету, перед которым он лежит
        for packet in packets:
            if packet.student_id is not None or common:
                packet.conditions = list(common)
        for page in stray:
            following = next(
                (
                    packet
                    for packet in packets
                    if packet.pages and packet.pages[0].index > page.index
                ),
                None,
            )
            if following is not None:
                following.conditions.append(page)
        if not pile_contradicts(packets):
            by_elimination(packets, roster)
        # Блоки позиционны, и два блока одного ученика врозь остаются двумя —
        # ровно затем, чтобы противоречие было видно. А в ответ едет работа, и
        # работа у человека одна, сколько бы раз он ни брал бумагу.
        return packets_without_duplicates(packets)

    for packet in by_conditions:
        decided = [page for page in packet.pages if page.decided_by_human]
        if decided:
            packet.student_id = decided[0].student_id
            packet.decided_by_human = True
            continue

        scored = vote(packet, roster)
        if _sure(scored):
            packet.student_id = scored[0][0].id
        else:
            packet.candidates = [person.id for person, _ in scored[:3]]

    # Вычет идёт **после** того, как все пакеты названы по чтению: он опирается
    # на то, что осталось, и запускать его раньше значило бы вычитать из
    # неполного.
    if not pile_contradicts(by_conditions):
        by_elimination(by_conditions, roster)
    return packets_without_duplicates(split_off_signed(by_conditions, roster))


def blocks(pages: list[Page], assigned: dict, doubted: dict, by_fit: set) -> list[Packet]:
    """
    Собрать пачку без листов условий в **блоки**, а не в отдельные страницы.

    Порядок листов в пачке жёсткий: работы лежат подряд, и чужая страница
    посреди чужого блока — событие примерно на тысячу пачек. Значит границу
    блока задаёт **смена владельца**, а неподписанный лист продолжает тот, что
    лежит над ним.

    Раньше эта мысль была разрывом ничьей: неподписанная страница шла к тому,
    у кого свободны её задачи, а сосед сверху вспоминался, только если таких
    оказывалось несколько. Покрытие задач — свидетельство слабое: оно говорит
    «может принадлежать», а порядок говорит «принадлежит вот этому». На живой
    пачке из тридцати четырёх листов покрытие резало её на **двадцать четыре**
    пакета вместо тринадцати работ — то есть человеку приходилось решать
    «чей это лист» вдвое чаще, чем есть работ, а вычету по остатку было не из
    чего вычитать.

    Правило поэтому простое: неподписанный лист **всегда** достаётся
    предыдущему блоку. Подписанный открывает новый — кроме случая, когда
    подписан он тем же, кто владеет нынешним: ученик подписывает и второй свой
    лист, и это не новая работа.
    """
    packets: list[Packet] = []
    current: Packet | None = None

    for page in pages:
        owner = assigned.get(page.index)
        same = current is not None and owner is not None and current.student_id == owner
        # неподписанный лист продолжает блок, подписанный своим же именем тоже
        joins = current is not None and (same or (not page.named and not page.decided_by_human))

        if joins:
            # Покрытие задач тут не решает, а сомневается: лист, повторивший
            # уже закрытую в блоке задачу, — повод спросить человека, а не
            # повод переложить лист. Решать им было слишком слабо (на живой
            # пачке такая раскладка ошибалась молча), а сомневаться в самый раз.
            if page.answered & {q for one in current.pages for q in one.answered}:
                current.overlaps.append(page.index)
            current.pages.append(page)
            current.decided_by_human |= page.decided_by_human
            if owner is None and current.student_id is not None:
                # лист лёг к соседу, а не по собственному имени — и человек
                # об этом узнает: догадка законная, но это догадка
                current.by_fit.append(page.index)
            if page.index in by_fit and page.index not in current.by_fit:
                current.by_fit.append(page.index)
            continue

        current = Packet(
            pages=[page],
            student_id=owner,
            candidates=doubted.get(page.index, []),
            decided_by_human=page.decided_by_human,
            by_fit=[page.index] if page.index in by_fit else [],
        )
        packets.append(current)

    return packets


def pile_contradicts(packets: list[Packet]) -> bool:
    """
    Есть ли в пачке противоречие — то, чего при жёстком порядке быть не может.

    Порядок листов в пачке жёсткий: работы лежат блоками, и чужая страница в
    середине чужого блока — событие примерно на тысячу пачек. Из этого следует
    проверка, которой раньше не было: **один ученик не может владеть двумя
    пакетами, лежащими врозь.** Соседние пакеты одного ученика — это законный
    второй комплект листов (их сливает `packets_without_duplicates`), а вот
    пакет в начале пачки и пакет в конце с тем же именем значат, что одно из
    двух имён прочитано неверно.

    Нужно это не ради самой пометки, а ради **вычета**: он опирается на то, что
    пачка разложена без сдвига, и сдвиг обязан его выключать. Перепутанный лист
    сдвигает нумерацию, и «остаток» после сдвига даёт уверенно неверный ответ
    вместо честного вопроса — а это худшая беда из возможных здесь.
    """
    # Дважды закрытая задача внутри блока — то же самое противоречие, только
    # увиденное с другой стороны: в блок затесался чужой лист.
    if any(packet.overlaps for packet in packets):
        return True

    seen: dict = {}
    for number, packet in enumerate(packets):
        if packet.student_id is None:
            continue
        if packet.student_id in seen and number - seen[packet.student_id] > 1:
            return True
        seen[packet.student_id] = number
    return False


def by_elimination(packets: list[Packet], roster: list[Person]) -> None:
    """
    Дать имена оставшимся пакетам по остатку. Меняет пакеты на месте.

    **Смысл в том, что список класса конечен.** Двенадцать пакетов из
    тринадцати разобраны уверенно — значит тринадцатый принадлежит тому
    единственному, кто остался, и это не догадка, а вычет. На живой пачке
    страницу «Артём Степанов» не прочитал **ни один** из четырёх читателей —
    «Кирилл Беганов», «Состанов», «анов Сделано с», — и вернуть её мог только
    остаток. Стоит он ноль запросов и ноль денег.

    Правил два, и оба идут до неподвижности:

    * **один пакет и один ученик** — они друг друга, и спорить не с чем;
    * **счёт против оставшихся, а не против всего класса.** Имя, бывшее ничьёй
      среди двадцати пяти, среди трёх оставшихся становится однозначным:
      «Белов» и «Белова» неразличимы, пока оба свободны, и различимы, как
      только один из них уже разобран.

    Чего вычет **не** делает: он не спорит с прочитанным именем. Пакет,
    названный уверенно, в свободные не попадает вовсе, и остаток на него не
    покушается. И вся процедура не запускается, если в пачке нашлось
    противоречие (`pile_contradicts`): опора вычета — жёсткий порядок, а
    противоречие говорит, что порядка нет.
    """
    while True:
        free_packets = [
            packet
            for packet in packets
            if packet.student_id is None and not packet.decided_by_human
        ]
        taken = {packet.student_id for packet in packets if packet.student_id is not None}
        free_people = [person for person in roster if person.id not in taken]
        if not free_packets or not free_people:
            return

        if len(free_packets) == 1 and len(free_people) == 1:
            free_packets[0].student_id = free_people[0].id
            free_packets[0].by_elimination = True
            free_packets[0].candidates = []
            return

        moved = False
        for packet in free_packets:
            scored = vote(packet, free_people)
            if _sure(scored):
                packet.student_id = scored[0][0].id
                packet.by_elimination = True
                packet.candidates = []
                moved = True
                break
        if not moved:
            return


def packets_without_duplicates(packets: list[Packet]) -> list[Packet]:
    """
    Два пакета на одного ученика — это не ошибка, а второй комплект листов.

    Сливаем их: работа у человека одна, сколько бы раз он ни брал бумагу. А
    вот если задачи в них пересекаются, это увидит слияние баллов и скажет
    вслух — там для этого есть конфликт.
    """
    seen: dict = {}
    out = []
    for packet in packets:
        if packet.student_id is None or packet.student_id not in seen:
            if packet.student_id is not None:
                seen[packet.student_id] = packet
            out.append(packet)
            continue
        first = seen[packet.student_id]
        first.pages += packet.pages
        first.conditions += packet.conditions
        # пометки едут вместе со страницами: слияние не повод потерять «этот
        # лист положен догадкой» или «этот забран по своей подписи»
        first.by_fit += packet.by_fit
        first.signed_apart += packet.signed_apart
    return out


def troubles(
    page: Page,
    assigned_to: int | None,
    max_mark: int | None,
    questions: int = QUESTIONS,
) -> list[str]:
    """
    Что с этой страницей не так. Список кодов — их показывают человеку.

    Сумма за страницу проверяется, только если она заполнена: ставить её
    необязательно, и пустая клетка не повод для тревоги.

    Не всё в этом списке — беда: часть кодов просто «посмотрите глазами».
    Блокирует разбор один `no_owner`, остальные показываются и пропускаются. А вот балл в клетке,
    которой у этой работы нет вовсе, — повод: клеток на бланке всегда
    пятнадцать, задач бывает меньше, и лишние обязаны остаться пустыми. Это
    бесплатная проверка чтения, и она ловит сдвиг на клетку.
    """
    out = []
    if assigned_to is None:
        out.append("no_owner")
    if not page.named:
        out.append("no_name")
    # Подписана одним именем, без фамилии, — и по этому имени кому-то отдана.
    # Свидетельство тут половинное, а имена повторяются чаще фамилий: на живой
    # пачке страница «Denis» прочиталась как «Misha» и молча ушла Мише, у
    # которого своя страница уже была. Не отказ — пометка: такие показываются
    # человеку всегда, даже когда всё остальное сошлось.
    elif assigned_to is not None and page.first.strip() and not page.surname.strip():
        out.append("first_name_only")
    # Читателей было двое, и они прочитали разное. Сама по себе такая страница
    # может быть прочитана верно — но узнать это можно только глазами, а
    # молчаливо неверное чтение выглядит ровно так же уверенно, как верное.
    # Ради этой пометки второй читатель и заведён.
    if page.second.get("differs"):
        out.append("readers_differ")
    if any(page.cells[q] is not None for q in range(questions, QUESTIONS)):
        out.append("beyond_questions")
    if max_mark:
        for q in range(questions):
            value = page.cells[q]
            if value is not None and value > max_mark:
                out.append("mark_too_big")
                break
    total = page.page_sum
    if total is not None:
        counted = sum(page.cells[q] for q in page.answered)
        if total != counted:
            out.append("sum_mismatch")
    return out


def merge_marks(pages: list[Page]) -> tuple[dict, list[int]]:
    """
    Баллы одного ученика со всех его страниц в один набор.

    Конфликт — это одна задача с разными баллами на двух страницах: молча
    выбрать одно из двух нельзя, поэтому он называется и идёт человеку.

    Возвращаются **номера клеток**, а не готовые подписи. Подпись зависит от
    того, как учитель назвал вопрос («1а», «324 из Галицкого»), а здесь про
    работу не известно ничего: сюда приезжают только прочитанные страницы.
    Пока функция клеила «Q1» сама, переименование вопроса до этого места не
    доходило — и в списке конфликтов оставались номера, которых на экране уже
    не было.
    """
    marks: dict[int, int] = {}
    conflicts: set[int] = set()
    for page in sorted(pages, key=lambda p: p.index):
        for q in page.answered:
            value = page.cells[q]
            if q in marks and marks[q] != value:
                conflicts.add(q)
            marks[q] = value
    return marks, sorted(conflicts)
