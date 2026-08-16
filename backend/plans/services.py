"""
Учебный план: дерево ровно из двух уровней.

На верхнем уровне вперемешку лежат папки и уроки, внутри папки — только
уроки. Сквозная нумерация уроков нигде не хранится: её даёт обход в глубину,
папки в нумерации не участвуют.

Ядро (`build_tree`, `number_lessons`, `counts`, `structure_problems`) работает
над любыми объектами с полями `pk`/`parent_id`/`position`/`is_section`,
поэтому проверяется без базы. Ниже — обёртки, которые подставляют выборку из
ORM и переписывают позиции.
"""

from __future__ import annotations

import csv
import io
from datetime import timedelta
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, NamedTuple, Sequence

from calendars.services import find_term
from django.db.models import Count, Q

from config.errors import Codes, error_payload

from .content import CONTENT_FIELDS

SECTION_INSIDE_SECTION = Codes.SECTION_INSIDE_SECTION
PARENT_NOT_SECTION = Codes.PARENT_NOT_SECTION
PARENT_OTHER_CLASS = Codes.PARENT_OTHER_CLASS

UP = "up"
DOWN = "down"
DIRECTIONS = (UP, DOWN)


@dataclass(frozen=True)
class Branch:
    """Узел верхнего уровня вместе с его уроками (у урока детей нет)."""

    node: object
    children: Sequence[object] = ()


@dataclass(frozen=True)
class Lesson:
    """Урок со сквозным номером и папкой, в которой он лежит."""

    number: int
    node: object
    section: object | None = None


def _order_key(node):
    # id как второй ключ: пока позиции не переписаны, порядок должен быть
    # предсказуемым, а не зависеть от того, как легли строки в базе
    return (node.position, node.pk or 0)


def build_tree(nodes: Iterable) -> list[Branch]:
    """Дерево верхнего уровня с вложенными детьми, всё по position."""
    ordered = sorted(nodes, key=_order_key)

    children = defaultdict(list)
    for node in ordered:
        if node.parent_id is not None:
            children[node.parent_id].append(node)

    return [
        Branch(node, tuple(children.get(node.pk, ())))
        for node in ordered
        if node.parent_id is None
    ]


def number_lessons(tree: Iterable[Branch]) -> list[Lesson]:
    """
    Уроки в порядке обхода в глубину со сквозными номерами.

    Уровней ровно два, поэтому «обход» — это цикл по верхнему уровню с
    заходом в детей папки; папки сами номеров не получают.
    """
    lessons: list[Lesson] = []

    for branch in tree:
        if branch.node.is_section:
            for child in branch.children:
                lessons.append(Lesson(len(lessons) + 1, child, branch.node))
        else:
            lessons.append(Lesson(len(lessons) + 1, branch.node))

    return lessons


def lesson_numbers(tree: Iterable[Branch]) -> dict[int, int]:
    return {lesson.node.pk: lesson.number for lesson in number_lessons(tree)}


def counts(tree: Iterable[Branch]) -> dict:
    branches = list(tree)
    lessons = number_lessons(branches)

    return {
        "lessons": len(lessons),
        "sections": sum(1 for branch in branches if branch.node.is_section),
    }


# статусы записи раскладки
STATUS_MATCHED = "matched"
STATUS_NO_SLOT = "no_slot"
STATUS_NO_PLAN = "no_plan"


@dataclass(frozen=True)
class LayoutEntry:
    """Одна строка раскладки: слот и урок плана, которые встретились."""

    status: str
    slot: object | None = None
    lesson: Lesson | None = None
    # терм, в который попала дата слота; у записей без слота его нет
    term: object | None = None


def build_layout(
    lessons: Sequence[Lesson], slots: Sequence, terms: Iterable = ()
) -> list[LayoutEntry]:
    """
    Сопоставление плана и расписания: **запись, а где её нет — позиция**.

    Долго это был чистый `zip` — i-й урок в i-й слот, — то есть не запись, а
    догадка: допущение, что обе оси идут в ногу. Догадка хорошая (в обычной
    жизни так и есть) и бесплатная, но она молча переписывала прошлое:
    вставили урок в сентябрьскую тему в марте, и сентябрь съезжал вместе со
    всей лентой.

    Теперь у часа бывает **связь** (`slot.lesson`) — учитель нажал «занятие
    проведено», и это уже не догадка. Правило поэтому двухступенчатое:

    1. час со связью показывает свой урок, всегда и что бы ни случилось с
       планом; такой урок из общей очереди изымается;
    2. остальные часы разбирают оставшиеся уроки плана по порядку — та же
       позиционная догадка, только на том, о чём никто ничего не сказал.

    Отсюда важное следствие: `no_plan` перестал быть непременно хвостом.
    Если план кончился, а дальше стоит связанный час, свободные часы лежат
    **между** занятыми, и всё, что ходит по раскладке, обязано это уметь.

    Ничего не хранит и не создаёт: несовпадение длин — это пометки. Лишние
    уроки плана идут как `no_slot` в конце.

    `lessons` — уроки плана по порядку (заголовки отфильтрованы),
    `slots` — неотменённые слоты по (дате, номеру). Запросы делаются
    снаружи, функция чистая.
    """
    terms = list(terms)

    # связь сильнее позиции: сначала разбираем записанное
    recorded = {
        slot.lesson_id: slot for slot in slots if getattr(slot, "lesson_id", None)
    }
    by_node = {lesson.node.pk: lesson for lesson in lessons}
    bound = {
        slot.pk: by_node[node_id]
        for node_id, slot in recorded.items()
        if node_id in by_node
    }

    # остальные уроки плана — общая очередь для часов без связи
    queue = iter(lesson for lesson in lessons if lesson.node.pk not in recorded)
    entries = []

    for slot in slots:
        lesson = bound.get(slot.pk) or next(queue, None)
        entries.append(
            LayoutEntry(
                status=STATUS_MATCHED if lesson is not None else STATUS_NO_PLAN,
                slot=slot,
                lesson=lesson,
                term=find_term(slot.date, terms),
            )
        )

    entries.extend(LayoutEntry(status=STATUS_NO_SLOT, lesson=lesson) for lesson in queue)

    return entries


def monday_of(day):
    return day - timedelta(days=day.weekday())


def number_weeks(study_days: Iterable, slots: Iterable = ()) -> dict:
    """
    Понедельник недели → её номер. Считаются только **учебные** недели.

    Нумерация сквозная от начала года и без дыр: неделя, целиком выпавшая
    на каникулы, номера не получает, и следующая за ней — не «одиннадцатая»,
    а та, что идёт по счёту занятий. Учителю нужен именно этот счёт, и
    «третья неделя» он скажет скорее, чем «тридцать девятая».

    Неделя, в которой учебных дней нет, но урок стоит (отработка в субботу
    посреди каникул), в счёт всё-таки входит: иначе у этого урока не было
    бы недели вовсе.
    """
    mondays = {monday_of(day) for day in study_days}
    mondays |= {monday_of(slot.date) for slot in slots}
    return {monday: number for number, monday in enumerate(sorted(mondays), start=1)}


def slot_ribbon(
    slots: Sequence,
    terms: Iterable = (),
    breaks: Iterable = (),
    study_days: Iterable = (),
) -> list:
    """
    Лента слотов: всё про даты, что **не зависит** от плана.

    Раскладка — это zip: i-й урок в i-й слот. Из двух её половин от правки
    плана меняется только одна, и как раз она тривиальна; календарь же —
    учебные дни, термы, каникулы — от плана не зависит вовсе. Поэтому
    страница плана берёт ленту один раз и сшивает её с планом у себя,
    получая мгновенный пересчёт после каждой правки и не унося на клиент
    ни одного настоящего правила.

    У слота есть его терм целиком (с датами) — по смене терма страница
    рисует заголовок «1 четверть · 07.09 — 25.10» — и номер учебной недели с
    её понедельником, по смене которого рисуется разделитель недели. У
    слота, перед которым в календаре лежат каникулы, заполнено
    `break_before`: между этими двумя уроками в расписании дыра, и её стоит
    назвать.
    """
    terms = list(terms)
    breaks = list(breaks)
    weeks = number_weeks(study_days, slots)
    rows = []
    previous = None

    for slot in slots:
        term = find_term(slot.date, terms)
        monday = monday_of(slot.date)

        gap = next(
            (
                period
                for period in breaks
                if previous is not None
                and previous.date < period.start_date
                and period.end_date < slot.date
            ),
            None,
        )

        rows.append(
            {
                "id": slot.pk,
                "date": slot.date,
                "lesson_number": slot.lesson_number,
                "is_extra": slot.is_extra,
                # связь: какой урок плана записан за этим часом. Клиент сшивает
                # ленту с планом сам, и без этого поля он повторял бы старый
                # чистый `zip` — то есть переписывал бы прошлое там, где
                # сервер его уже не переписывает
                "lesson_id": slot.lesson_id,
                "week": weeks.get(monday),
                "week_start": monday,
                "term_id": term.pk if term else None,
                "term_name": term.name if term else None,
                "term": (
                    {
                        "id": term.pk,
                        "name": term.name,
                        "start": term.start_date,
                        "end": term.end_date,
                    }
                    if term
                    else None
                ),
                "break_before": (
                    {
                        "title": gap.title,
                        "start": gap.start_date,
                        "end": gap.end_date,
                    }
                    if gap
                    else None
                ),
            }
        )
        previous = slot

    return rows


def summary_by_term(entries: Sequence[LayoutEntry], terms: Iterable = ()) -> list[dict]:
    """
    Слоты и уроки плана по термам плюс отдельная запись «вне термов».

    Баланс терма — `slots - lessons`. Раскладка позиционная, поэтому внутри
    заполненного терма он нулевой; минус появляется там, где плану не хватило
    слотов (такие уроки дат не имеют и попадают в «вне термов»), плюс — там,
    где слоты остались свободными.
    """
    def bucket(name, items, term=None):
        slots = sum(1 for entry in items if entry.slot is not None)
        lessons = sum(1 for entry in items if entry.lesson is not None)
        return {
            "id": term.pk if term is not None else None,
            "name": name,
            "start": term.start_date if term is not None else None,
            "end": term.end_date if term is not None else None,
            "slots": slots,
            "lessons": lessons,
            "balance": slots - lessons,
        }

    rows = [
        bucket(
            term.name,
            [e for e in entries if e.term is not None and e.term.pk == term.pk],
            term,
        )
        for term in terms
    ]

    outside = [entry for entry in entries if entry.term is None]
    if outside:
        rows.append(bucket("вне термов", outside))

    return rows


@dataclass(frozen=True)
class Numbers:
    """
    Всё, что можно сосчитать по готовой раскладке. Один расчёт на всех.

    Считалось это дважды — в сводке раскладки и в ответе «Состояния
    курсов», — под разными именами и по разным формулировкам: `balance` и
    `reserve`, `past_lessons` и `done`. Числа совпадали, но держались на
    том, что обе копии правили вместе; сторож их сверял, а не выводил из
    одного места.

    Имена в ответах остались прежними: их читают страницы и словарь, и
    переименование ради красоты стоило бы правок в трёх местах ради нуля.
    Обёртки ниже — это перевод одного расчёта на два словаря.
    """

    lessons_total: int
    slots_total: int
    balance: int
    missing: int
    past_slots: int
    remaining_slots: int
    past_lessons: int
    remaining_lessons: int
    extra: int
    last_lesson_date: object | None
    # уроки плана, до которых ещё не дошли: «где я» и «что дальше»
    upcoming: Sequence[LayoutEntry] = ()


def count_layout(entries: Iterable[LayoutEntry], today) -> Numbers:
    """
    Единственный расчёт чисел раскладки.

    `today` влияет только на «прошло/осталось» и на список ближайших
    уроков, но не на само сопоставление: раскладка позиционная и о
    сегодняшнем дне не знает.
    """
    entries = list(entries)
    with_slot = [entry for entry in entries if entry.slot is not None]
    with_lesson = [entry for entry in entries if entry.lesson is not None]
    matched = [entry for entry in entries if entry.status == STATUS_MATCHED]

    past_slots = sum(1 for entry in with_slot if entry.slot.date < today)
    past_lessons = sum(1 for entry in matched if entry.slot.date < today)

    # план не помещается — последнего урока в году просто нет
    fits = len(matched) == len(with_lesson)

    return Numbers(
        lessons_total=len(with_lesson),
        slots_total=len(with_slot),
        balance=len(with_slot) - len(with_lesson),
        missing=len(with_lesson) - len(matched),
        past_slots=past_slots,
        remaining_slots=len(with_slot) - past_slots,
        past_lessons=past_lessons,
        remaining_lessons=len(with_lesson) - past_lessons,
        extra=sum(1 for entry in with_slot if entry.slot.is_extra),
        last_lesson_date=matched[-1].slot.date if fits and matched else None,
        upcoming=[entry for entry in matched if entry.slot.date >= today],
    )


def layout_summary(
    entries: Iterable[LayoutEntry],
    today,
    cancelled_count: int = 0,
    terms: Iterable = (),
) -> dict:
    """Итоги раскладки для `/layout/summary/`: числа плюс разбивка по термам."""
    entries = list(entries)
    numbers = count_layout(entries, today)

    return {
        "lessons_total": numbers.lessons_total,
        "slots_total": numbers.slots_total,
        "balance": numbers.balance,
        "past_slots": numbers.past_slots,
        "remaining_slots": numbers.remaining_slots,
        "past_lessons": numbers.past_lessons,
        "remaining_lessons": numbers.remaining_lessons,
        "last_lesson_date": numbers.last_lesson_date,
        "cancelled_count": cancelled_count,
        "extra_count": numbers.extra,
        "terms": summary_by_term(entries, terms),
    }


def course_progress(
    entries: Sequence[LayoutEntry],
    today,
    cancelled_count: int = 0,
    ahead: int = 2,
) -> dict:
    """
    Где курс идёт по году: положение, резерв, потери и ближайшие уроки.

    Отменённые считаются числом, без разбивки по причинам: на экране она
    была единственным местом, где высота плашки зависела от данных, а
    причины видны в расписании, где отмену и ставили.

    **Главное число — резерв**: `слоты минус уроки плана`. Плюс значит, что
    в году есть незанятые дни, минус — что план не помещается и его придётся
    сократить. Порогов и промежуточных состояний нет: либо помещается, либо
    нет.

    Темпа здесь не считается, и это осознанно. «Отстаю на два урока» при
    позиционной раскладке не бывает: i-й урок лежит в i-м слоте, и пройдено
    всегда ровно столько уроков, сколько прошло слотов. Любая такая метрика
    была бы пересчётом резерва, выданным за новость.

    Расхождение с эталоном (`baseline_diff`) считает вызывающий код: снимок
    живёт в базе, а эта функция работает над готовой раскладкой.
    """
    numbers = count_layout(entries, today)

    return {
        "lessons_total": numbers.lessons_total,
        "slots_total": numbers.slots_total,
        "done": numbers.past_lessons,
        "reserve": numbers.balance,
        "current": (
            lesson_position(numbers.upcoming[0]) if numbers.upcoming else None
        ),
        "next": [lesson_position(entry) for entry in numbers.upcoming[:ahead]],
        "last_lesson_date": numbers.last_lesson_date,
        "missing": numbers.missing,
        "cancelled": cancelled_count,
        "extra": numbers.extra,
    }


#: сколько дней система настаивает на том, чтобы день закрыли
def record_state(slots: Sequence, today) -> dict:
    """
    Долги по записи: прошедшие часы, за которыми ничего не записано.

    **Долг появляется только там, где связь хоть раз ставили.** Учителю,
    который кнопкой не пользуется, каждый прошедший час был бы «долгом», и
    экран орал бы на человека, которому эта механика не нужна. Начал —
    пропуски значат что-то; не начал — работает позиционная догадка, как
    работала всегда.

    **Срока давности у долга нет.** Две недели тут были: старое из счётчика
    уходило и досчитывалось позиционно, чтобы настойчивость не догоняла
    человека через месяц и не заставляла сочинять. Отменено вместе с
    приходом строгого порядка — при нём дырка не «протухает», а блокирует
    следующую запись, и амнистия означала бы навсегда закрытую очередь.
    Настойчивости при этом не прибавилось: долги видно в таблице плана,
    куда приходят сами, а не полосой на дороге.

    **Дыра называется вслух**: `confirmed` из `held` — доля, на которой
    посчитано всё остальное.
    """
    held = [slot for slot in slots if slot.date <= today]
    started = any(slot.lesson_id for slot in slots)

    return {
        "held": len(held),
        "confirmed": sum(1 for slot in held if slot.lesson_id),
        "unclosed": sum(1 for slot in held if not slot.lesson_id) if started else 0,
    }


def reserve_since(
    slots_then: int | None,
    lessons_then: int,
    slots_now: int,
    lessons_now: int,
) -> dict | None:
    """
    Почему резерв стал таким: что сделало расписание, что сделала программа.

    Резерв (`слоты − уроки`) — единственное число приложения, живущее сразу
    на обеих осях: календарной и программной. Именно поэтому его падение
    само по себе ничего не объясняет — то ли дни потерялись, то ли план
    вырос, — и рядом с ним всегда стоял вопрос «а почему».

    Ответ становится точным, как только известна точка отсчёта, и потому у
    эталона есть `slots_total`: сколько часов было у курса в момент
    утверждения. Дальше это тождество, а не оценка:

        резерв сейчас = резерв тогда + (часы) − (уроки плана)

    `None`, если точки отсчёта нет: эталон не утверждён или утверждён до
    того, как это число стали снимать. Догадываться тут не о чем.
    """
    if slots_then is None:
        return None

    return {
        "then": slots_then - lessons_then,
        "now": slots_now - lessons_now,
        "schedule": slots_now - slots_then,
        "plan": lessons_now - lessons_then,
    }


def baseline_diff(rows: Iterable, lessons: Sequence[Lesson]) -> dict:
    """
    Насколько план разошёлся с зафиксированным эталоном.

    Две категории, а не сальдо: **добавлено** и **удалено**. Обе плохие, но
    по-разному — рост съедает резерв, удаление означает выкинутый материал,
    и «плюс три минус три» тут не ноль, а шесть событий.

    Считается по id узлов, а не по названиям: переименованный урок остаётся
    тем же уроком, а два «Контрольная работа» в разных темах — разными.
    Удалённый и заново заведённый урок честно считается и удалённым, и
    добавленным: это и есть две правки.

    По темам показывается только рост: дефицита по теме не бывает — тема,
    из которой убрали урок, просто стала короче, а не «должна» его.
    """
    known = {row.node_id for row in rows if row.node_id}
    alive = {lesson.node.pk for lesson in lessons}

    added = [lesson for lesson in lessons if lesson.node.pk not in known]
    removed = sum(
        1
        for row in rows
        if not row.is_section and row.node_id and row.node_id not in alive
    )

    grown: dict[str | None, int] = {}
    for lesson in added:
        title = lesson.section.title if lesson.section else None
        grown[title] = grown.get(title, 0) + 1

    return {
        "added": len(added),
        "removed": removed,
        "themes": [
            {"title": title, "added": count}
            for title, count in sorted(
                grown.items(), key=lambda item: (-item[1], item[0] or "")
            )
        ],
    }


def lesson_position(entry: LayoutEntry) -> dict:
    """Урок плана вместе с датой, на которую он попал."""
    return {
        "number": entry.lesson.number,
        "title": entry.lesson.node.title,
        "section_title": entry.lesson.section.title if entry.lesson.section else None,
        "date": entry.slot.date if entry.slot else None,
    }


def current_term(entries: Sequence[LayoutEntry], today, terms: Iterable = ()):
    """
    Терм, в котором курс сейчас, — или ближайший будущий.

    Год может сходиться, а четверть уже нет, поэтому запас считается прежде
    всего по ней. До начала года «сейчас» ещё нет, и тогда полезнее сказать
    про ту четверть, которая начнётся.
    """
    terms = sorted(terms, key=lambda term: term.start_date)
    term = find_term(today, terms) or next(
        (item for item in terms if item.start_date > today), None
    )
    if term is None:
        return None

    return next(
        (row for row in summary_by_term(entries, [term]) if row["id"] == term.pk),
        None,
    )


def structure_problems(*, course_id, parent, is_section) -> dict:
    """
    Tree rule violations as ``{field: (code, message)}``; empty means fine.

    One check for everybody: both ``PlanNode.clean`` and the serializers call
    it, so the admin and the API always agree.
    """
    if parent is None:
        return {}

    if is_section:
        return {
            "parent": (SECTION_INSIDE_SECTION, "A section can only live at the top level.")
        }

    if not parent.is_section:
        return {"parent": (PARENT_NOT_SECTION, "A node can only be nested into a section.")}

    if parent.course_id != course_id:
        return {"parent": (PARENT_OTHER_CLASS, "That section belongs to another course.")}

    return {}



# --- CSV: единственный формат, разбор и выгрузка, тоже без ORM ---
#
# Формат один: `id,Тема,Урок,Заметка`, шапка обязательна, одна строка — один
# урок. Тема повторяется в каждой строке; пустая ячейка темы значит «урок вне
# темы», пустой id — «урок новый». Отдельной строки-заголовка нет.
#
# Стилей было три, и разбор угадывал, какой перед ним. У догадки не бывает
# неправильного ответа — она всегда «удаётся», — и стоило это фантомных
# заголовков, уроков, молча уехавших на верхний уровень, и сдвига столбцов
# на файле, где столбец id не признался. Теперь непонятная строка отклоняет
# **весь** файл с номером строки: лучше отказ, чем принятый не тот план.

CSV_HEADER = ("id", "Тема", "Урок", "Заметка")
CSV_MAX_ROWS = 2000
TITLE_LIMIT = 200


def normalized_cell(cell: str) -> str:
    """Ячейка шапки без регистра и пробелов: « Тема » и «тема» — одно."""
    return "".join(cell.split()).lower()


HEADER_NORMALIZED = tuple(normalized_cell(cell) for cell in CSV_HEADER)
HEADER_TEXT = ",".join(CSV_HEADER)


class PlanImportError(Exception):
    """Файл целиком непригоден: пользователю показывается как есть."""


@dataclass(frozen=True)
class ImportedRow:
    """
    Строка файла, уже понятая: заголовок темы или урок.

    Та же форма служит и библиотеке, поэтому кроме названия она умеет нести
    содержание урока и его вложения. CSV ни того, ни другого не выражает и
    оставляет пустыми — способ заполнить план от этого не меняется.

    `attachments` — существующие объекты `files.Attachment`, а не их копии:
    перенос делает `files.services.copy_attachments`, и он не трогает байты.

    Заголовки в CSV не пишутся: их выводит разбор из смены значения в
    столбце «Тема», поэтому у такой строки `node_id` пуст всегда — id в
    файле принадлежит уроку. Кто из тем в плане соответствует блоку,
    решает `plan_sync` по уроками внутри него.
    """

    is_section: bool
    title: str
    note: str = ""
    content: dict | None = None
    attachments: Sequence = ()
    node_id: int | None = None
    # номер строки в файле — нужен, чтобы ошибка могла показать, где смотреть
    row_number: int = 0
    # «этот урок не внутри предыдущей темы»: в файле у него пустая тема
    at_top_level: bool = False


def decode_csv(data: bytes) -> str:
    """
    Текст файла независимо от того, чем его сохранили.

    UTF-8 (в том числе с BOM) пробуем первым: cp1251 «читает» почти любые
    байты и молча превратил бы кириллицу в кракозябры.
    """
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue

        # cp1251 «читает» и двоичный мусор: нулевые байты выдают его с головой
        # (Postgres такую строку всё равно не примет)
        if "\x00" in text:
            break

        return text

    raise PlanImportError(
        "The file could not be read: a plain CSV in UTF-8 or Windows-1251 "
        "is expected."
    )


def sniff_delimiter(text: str) -> str:
    """
    Запятая или точка с запятой — по тому, какой даёт ровные записи.

    Не по числу вхождений: запятые бывают внутри названий, и файл русского
    Excel («;» снаружи, запятые внутри) тогда читался бы одним столбцом.
    Считаем именно записи, а не строки: перевод строки внутри кавычек — это
    часть заметки, и, порезав текст по `\\n`, мы сравнивали бы обрывки.
    """

    def head(candidate):
        rows = []
        for row in csv.reader(io.StringIO(text), delimiter=candidate):
            if any(cell.strip() for cell in row):
                rows.append(row)
            if len(rows) == 5:
                break
        return rows

    def score(candidate):
        widths = [len(row) for row in head(candidate)]
        if not widths:
            return (False, 0)
        return (len(set(widths)) == 1 and min(widths) > 1, min(widths))

    return ";" if score(";") > score(",") else ","


def row_cells(raw: Sequence[str]) -> list | None:
    """
    Четыре ячейки строки — или None, если столбцов не четыре.

    Пустые столбцы справа Excel дописывает сам, и это не повод для отказа;
    заполненный пятый столбец — уже другой файл.
    """
    width = len(CSV_HEADER)
    if len(raw) < width:
        return None
    if any(cell.strip() for cell in raw[width:]):
        return None

    return [cell.strip() for cell in raw[:width]]


class ParsedPlan(NamedTuple):
    """Разобранный файл: строки и то, что помешало его принять."""

    rows: list
    errors: list
    # строк с данными в файле — всех, включая отклонённые. Рядом с числом
    # уроков это и говорит, сколько строк не прочиталось
    data_rows: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def lessons(self) -> int:
        return sum(1 for row in self.rows if not row.is_section)

    @property
    def sections(self) -> int:
        return sum(1 for row in self.rows if row.is_section)


def parse_plan_csv(text: str, *, max_rows: int = CSV_MAX_ROWS) -> ParsedPlan:
    """CSV → строки плана. Дальше файл ничем не отличается от таблицы."""
    return parse_plan_rows(
        csv.reader(io.StringIO(text), delimiter=sniff_delimiter(text)),
        max_rows=max_rows,
    )


def parse_plan_rows(
    raw_rows: Iterable[Sequence[str]], *, max_rows: int = CSV_MAX_ROWS
) -> ParsedPlan:
    """
    Разбор таблицы единственного формата — общий для CSV и xlsx.

    Форматы различаются только тем, как получить ячейки: у CSV это
    кодировка, разделитель и кавычки, у xlsx — openpyxl. Всё остальное —
    шапка, столбцы, id, темы, уроки — здесь, в одном месте, иначе два
    формата разошлись бы правилами уже на второй правке.

    Ошибки собираются все разом и ничего не пишут: показать человеку весь
    список полезнее, чем первую строку, на которой разбор сдался. Отказ
    всегда целиком — половина применённого файла хуже неприменённого.
    """
    rows_read = []
    for number, raw in enumerate(raw_rows, start=1):
        # шапка — не урок, поэтому предел считается по строкам данных
        if number > max_rows + 1:
            raise PlanImportError(
                f"The file has more than {max_rows} rows — split it into parts."
            )
        rows_read.append(list(raw))
    raw_rows = rows_read

    head = row_cells(raw_rows[0]) if raw_rows else None
    if head is None or tuple(normalized_cell(cell) for cell in head) != HEADER_NORMALIZED:
        # без шапки читать нечего: порядок столбцов больше не угадывается
        return ParsedPlan([], [
            error_payload(
                Codes.CSV_HEADER_INVALID,
                f"The first row must be the header «{HEADER_TEXT}».",
                expected=HEADER_TEXT,
                got=",".join(raw_rows[0]) if raw_rows else "",
            )
        ])

    rows: list[ImportedRow] = []
    errors: list[dict] = []
    current_theme: str | None = None
    data_rows = 0

    for number, raw in enumerate(raw_rows[1:], start=2):
        if not any(cell.strip() for cell in raw):
            # пустая строка в конце файла — обычное дело у Excel
            continue

        data_rows += 1

        cells = row_cells(raw)
        if cells is None:
            errors.append(
                error_payload(
                    Codes.CSV_BAD_COLUMNS,
                    f"Row {number}: the file must have exactly four columns.",
                    row=number, count=len(raw),
                )
            )
            continue

        id_cell, theme, lesson, note = cells

        if theme and not lesson:
            # раньше это был заголовок темы; сказать об этом прямо, иначе
            # человек будет искать опечатку там, где её нет
            errors.append(
                error_payload(
                    Codes.CSV_SECTION_ROW,
                    f"Row {number}: «{theme}» has no lesson. A theme is written "
                    f"on every lesson row, not on a row of its own.",
                    row=number, title=theme,
                )
            )
            continue

        if not theme and not lesson:
            errors.append(
                error_payload(
                    Codes.CSV_ROW_EMPTY,
                    f"Row {number}: neither a theme nor a lesson.",
                    row=number,
                )
            )
            continue

        if max(len(theme), len(lesson)) > TITLE_LIMIT:
            errors.append(
                error_payload(
                    Codes.CSV_ROW_TOO_LONG,
                    f"Row {number}: the title is longer than {TITLE_LIMIT} characters.",
                    row=number, limit=TITLE_LIMIT,
                )
            )
            continue

        node_id = None
        if id_cell:
            if not id_cell.isdigit() or int(id_cell) == 0:
                errors.append(
                    error_payload(
                        Codes.CSV_BAD_ID,
                        f"Row {number}: «{id_cell}» is not a row id.",
                        row=number, value=id_cell,
                    )
                )
                continue
            node_id = int(id_cell)

        if theme != current_theme:
            current_theme = theme
            if theme:
                rows.append(
                    ImportedRow(is_section=True, title=theme, row_number=number)
                )

        rows.append(
            ImportedRow(
                is_section=False, title=lesson, note=note,
                node_id=node_id, row_number=number,
                at_top_level=not theme,
            )
        )

    return ParsedPlan(rows, errors, data_rows)


def build_plan_csv(tree: Iterable[Branch]) -> str:
    """
    План в CSV: одна строка — один урок, тема повторяется в каждой.

    Формат тот же самый, что понимает импорт, и другого нет: круговой прогон
    экспорт → импорт в режиме sync не меняет ни строчки.

    Чего в файле нет: темы без уроков (строки для неё не существует) и
    заметки самой темы — заметка принадлежит уроку. Обратный импорт такую
    тему удалит, и предпросмотр это показывает.

    BOM в начале — чтобы Excel открыл файл как UTF-8, а не как cp1251.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=",", lineterminator="\r\n")
    writer.writerow(CSV_HEADER)

    def put(node, theme):
        writer.writerow([node.pk, theme, node.title, node.note])

    for branch in tree:
        if branch.node.is_section:
            for child in branch.children:
                put(child, branch.node.title)
        else:
            put(branch.node, "")

    # ﻿ — тот самый BOM, в исходнике он невидим, поэтому кодом
    return "﻿" + buffer.getvalue()




# --- from here on the database is involved: node order has to be stored ---


def _parent_id(parent):
    return parent.pk if hasattr(parent, "pk") else parent


def level(course_id, parent=None) -> list:
    """
    Соседи по уровню, в порядке следования.

    План принадлежит **курсу**: один курс — одно дерево, поэтому ключ
    уровня — курс и родитель, и больше ничего. Пока план был личным, ключей
    было два, и уровень нельзя было спрашивать, не назвав ещё и учителя.
    """
    from .models import PlanNode

    return sorted(
        PlanNode.objects.filter(
            course_id=course_id,
            parent_id=_parent_id(parent),
        ),
        key=_order_key,
    )


def reindex(course_id, parent=None) -> list:
    """Renumber a level without gaps: 0, 1, 2, …"""
    from .models import PlanNode

    nodes = level(course_id, parent)
    changed = []

    for position, node in enumerate(nodes):
        if node.position != position:
            node.position = position
            changed.append(node)

    if changed:
        PlanNode.objects.bulk_update(changed, ["position"])

    return nodes


def place(node, parent, index: int) -> None:
    """Put a node onto the given level at the given position."""
    from .models import PlanNode

    parent_id = _parent_id(parent)
    previous_parent_id = node.parent_id

    siblings = [item for item in level(node.course_id, parent_id) if item.pk != node.pk]
    index = max(0, min(index, len(siblings)))

    node.parent_id = parent_id
    siblings.insert(index, node)

    for position, item in enumerate(siblings):
        item.position = position

    PlanNode.objects.bulk_update(siblings, ["position", "parent"])

    if previous_parent_id != parent_id:
        # the level just left behind now has a gap
        reindex(node.course_id, previous_parent_id)


def move(node, direction: str) -> bool:
    """
    One step among siblings — entering sections and leaving them.

    A top-level lesson running into a section enters it as the outermost
    element; a lesson that reached the edge of a section comes out and stands
    next to it. Two buttons therefore walk a lesson through the whole tree.

    Returns False when there is nowhere to go: the edge of the tree.
    """
    step = -1 if direction == UP else 1
    siblings = level(node.course_id, node.parent_id)
    index = next(i for i, item in enumerate(siblings) if item.pk == node.pk)
    target = index + step

    if node.parent_id is None:
        if not 0 <= target < len(siblings):
            return False

        neighbour = siblings[target]
        if neighbour.is_section and not node.is_section:
            # from above we enter first, from below last
            inside = level(node.course_id, neighbour)
            place(node, neighbour, 0 if step > 0 else len(inside))
            return True

        place(node, None, target)
        return True

    if 0 <= target < len(siblings):
        place(node, node.parent, target)
        return True

    # the edge of a section — surface to the top level next to it
    top = level(node.course_id, None)
    section_index = next(i for i, item in enumerate(top) if item.pk == node.parent_id)
    place(node, None, section_index + (1 if step > 0 else 0))
    return True


def dissolve_section(section) -> None:
    """Delete a section, lifting its lessons to its place on the top level."""
    from .models import PlanNode

    children = level(section.course_id, section)
    top = level(section.course_id, None)

    order = []
    for item in top:
        if item.pk == section.pk:
            order.extend(children)
        else:
            order.append(item)

    for child in children:
        child.parent_id = None
    for position, item in enumerate(order):
        item.position = position

    PlanNode.objects.bulk_update(order, ["position", "parent"])
    # the children are detached already, the cascade will not reach them
    section.delete()


def apply_import(course_id: int, rows: Iterable[ImportedRow], *, append: bool) -> dict:
    """
    Create nodes from the parsed rows. Called inside a transaction.

    A lesson lands in the last header seen; until a header appears it stays
    on the top level.

    `pairs` in the result lines every row up with the node it became. The
    caller needs it to carry attachments across — those live in another app,
    and the plan does not have to know about it to write a plan.
    """
    from .models import PlanNode

    top_position = len(level(course_id, None)) if append else 0
    section = None
    section_position = 0
    created = {"headers": 0, "lessons": 0, "pairs": []}

    for row in rows:
        content = row.content or {}

        if row.at_top_level:
            # файл сказал прямо: этот урок не в теме
            section = None

        if row.is_section:
            section = PlanNode.objects.create(
                course_id=course_id,
                parent=None,
                position=top_position,
                is_section=True,
                title=row.title,
                note=row.note,
            )
            top_position += 1
            section_position = 0
            created["headers"] += 1
            created["pairs"].append((row, section))
            continue

        node = PlanNode.objects.create(
            course_id=course_id,
            parent=section,
            position=section_position if section else top_position,
            is_section=False,
            title=row.title,
            note=row.note,
            **{field: content.get(field, "") for field in CONTENT_FIELDS},
        )
        if section:
            section_position += 1
        else:
            top_position += 1
        created["lessons"] += 1
        created["pairs"].append((row, node))

    return created


# --- sync: the plan updated from a file rather than rebuilt from it ---------
#
# Replace and append both treat the file as the whole truth, and that costs
# the lesson content: a rewritten row is a new row, and a new row is empty.
# Sync reads the id column instead, so a row that was already there is
# *updated* — title, note and place in the tree — while everything the file
# cannot express (the four content fields, the attachments) is simply left
# alone.
#
# The whole file is checked before a single row is written. A half-applied
# plan is worse than a rejected one: the person would have to work out which
# half, and the file no longer matches either state.


class NewNode(NamedTuple):
    """A row that does not exist yet, named by its place in `SyncPlan.create`."""

    index: int


@dataclass(frozen=True)
class SyncPlan:
    """What sync would do, worked out before anything is written."""

    create: list          # ImportedRow without an id
    update: list          # (node, row, parent_id, position)
    delete: list          # nodes the file no longer mentions
    errors: list          # blocking: any one of these stops the import

    @property
    def ok(self) -> bool:
        return not self.errors


def _sync_errors(rows, known: dict) -> list:
    """Everything wrong with the file, all of it, before anything is written."""
    errors = []
    seen = set()

    for row in rows:
        if row.node_id is None:
            continue

        if row.node_id in seen:
            errors.append(
                error_payload(
                    Codes.CSV_ID_DUPLICATE,
                    f"Row {row.row_number}: id {row.node_id} is used twice.",
                    row=row.row_number, id=row.node_id,
                )
            )
            continue

        seen.add(row.node_id)
        node = known.get(row.node_id)

        if node is None:
            # чужой и несуществующий неразличимы намеренно: id чужого плана
            # не должен подтверждаться сообщением о том, что он существует
            errors.append(
                error_payload(
                    Codes.CSV_ID_UNKNOWN,
                    f"Row {row.row_number}: id {row.node_id} is not in this plan.",
                    row=row.row_number, id=row.node_id,
                )
            )
        elif node.is_section != row.is_section:
            # тема с уроками, ставшая уроком, осиротила бы своих детей;
            # разворачивать это молча нельзя, а угадывать нечего
            errors.append(
                error_payload(
                    Codes.CSV_ID_KIND_CHANGED,
                    f"Row {row.row_number}: id {row.node_id} is a "
                    f"{'section' if node.is_section else 'lesson'} in the plan.",
                    row=row.row_number, id=row.node_id, title=node.title,
                )
            )

    return errors


def blocks_of(rows: Iterable[ImportedRow]) -> list:
    """
    Строки файла как блоки: тема (или None у верхнего уровня) и её уроки.

    Заголовок в файле не написан, он выведен из смены темы, поэтому решать,
    какой теме плана он соответствует, приходится по урокам внутри блока —
    а для этого блок сначала нужно увидеть целиком.
    """
    blocks: list[tuple] = []
    section = None
    lessons: list[ImportedRow] = []

    def flush():
        if section is not None or lessons:
            blocks.append((section, lessons))

    for row in rows:
        if row.is_section:
            flush()
            section, lessons = row, []
        else:
            if row.at_top_level and section is not None:
                flush()
                section, lessons = None, []
            lessons.append(row)

    flush()
    return blocks


def adopt_section(lessons, known: dict, claimed: set):
    """
    Какая тема плана стоит за этим блоком файла.

    Отвечают уроки: у первого же знакомого id спрашиваем, в какой теме он
    сейчас лежит. Поэтому переименование темы **во всех** строках — это
    переименование заголовка, а не новая тема со старой на выброс.

    Если ту же тему уже забрал блок выше, второй получает свою новую: тема,
    переименованная в части строк, разделяется надвое — при протягивании
    иначе и быть не может, и предпросмотр это показывает числом созданных.
    """
    for row in lessons:
        if row.node_id is None:
            continue
        parent_id = known[row.node_id].parent_id
        if parent_id and parent_id not in claimed and parent_id in known:
            return known[parent_id]

    return None


def plan_sync(course_id: int, rows: Iterable[ImportedRow]) -> SyncPlan:
    """
    Работает без записи: тем же расчётом пользуются и предпросмотр, и импорт.

    Порядок строк в файле и есть новый порядок плана, поэтому позиции
    считаются здесь же — сначала по файлу, а не переписыванием уже
    сдвинутого дерева.
    """
    rows = list(rows)
    known = {node.pk: node for node in plan_nodes(course_id)}

    errors = _sync_errors(rows, known)
    if errors:
        # дальше считать нечего: план строится по id, а им нельзя верить
        return SyncPlan(create=[], update=[], delete=[], errors=errors)

    create, update, kept, claimed = [], [], set(), set()
    top_position = 0

    def schedule(row, parent_ref, position):
        """Строка в create или update, и чем на неё сослаться дальше."""
        if row.node_id is None:
            create.append((row, parent_ref, position))
            # у новой темы id появится только при записи, поэтому её уроки
            # ссылаются на место в списке создаваемых, а не на pk
            return NewNode(len(create) - 1)

        kept.add(row.node_id)
        update.append((known[row.node_id], row, parent_ref, position))
        return row.node_id

    for section_row, lessons in blocks_of(rows):
        section_ref = None

        if section_row is not None:
            node = adopt_section(lessons, known, claimed)
            if node is None:
                create.append((section_row, None, top_position))
                section_ref = NewNode(len(create) - 1)
            else:
                claimed.add(node.pk)
                kept.add(node.pk)
                update.append((node, section_row, None, top_position))
                section_ref = node.pk
            top_position += 1

        for position, row in enumerate(lessons):
            if section_ref is None:
                schedule(row, None, top_position)
                top_position += 1
            else:
                schedule(row, section_ref, position)

    delete = [node for pk, node in known.items() if pk not in kept]

    return SyncPlan(create=create, update=update, delete=delete, errors=[])


def apply_sync(course_id: int, plan: SyncPlan) -> dict:
    """Записать посчитанное. Вызывается внутри транзакции."""
    from .models import PlanNode

    if not plan.ok:
        raise ValueError("refusing to apply a sync plan with errors")

    fresh: dict[NewNode, int] = {}

    def pk_of(ref):
        """A parent reference into a real id: None, a pk, or a fresh section."""
        return fresh[ref] if isinstance(ref, NewNode) else ref

    def build(row, parent_ref, position):
        return PlanNode.objects.create(
            course_id=course_id,
            parent_id=pk_of(parent_ref),
            position=position,
            is_section=row.is_section,
            title=row.title,
            note=row.note,
        )

    # темы первыми: урок под новой темой должен знать её id
    for index, (row, parent_ref, position) in enumerate(plan.create):
        if row.is_section:
            fresh[NewNode(index)] = build(row, parent_ref, position).pk

    # обновляем до удаления: урок, ушедший из удаляемой темы, должен успеть
    # сменить родителя, иначе его унесёт каскадом
    changed = []
    for node, row, parent_ref, position in plan.update:
        node.title = row.title
        if not row.is_section:
            # заметка в файле принадлежит уроку; у темы её выражать нечем,
            # и стирать поэтому нечего — sync не трогает того, чего не видит
            node.note = row.note
        node.parent_id = pk_of(parent_ref)
        node.position = position
        changed.append(node)

    if changed:
        PlanNode.objects.bulk_update(changed, ["title", "note", "parent", "position"])

    for index, (row, parent_ref, position) in enumerate(plan.create):
        if not row.is_section:
            build(row, parent_ref, position)

    created = len(plan.create)
    deleted = len(plan.delete)
    if deleted:
        PlanNode.objects.filter(pk__in=[node.pk for node in plan.delete]).delete()

    return {"created": created, "updated": len(plan.update), "deleted": deleted}


def plan_nodes(course_id: int):
    """
    A teacher's nodes in a course, with the attachment count alongside.

    Counting here rather than per row: the plan page draws a paperclip on
    every lesson that has one, and asking the database once beats asking it
    two hundred times.
    """
    from .models import PlanNode

    return PlanNode.objects.filter(
        course_id=course_id
    ).annotate(attachment_count=Count("attachments"))


def get_tree(course_id: int) -> list[Branch]:
    return build_tree(plan_nodes(course_id))


def lessons_by_course(course_ids: Iterable[int]) -> dict:
    """
    Уроки плана сразу по нескольким курсам: `{course_id: [...]}`.

    Один запрос вместо запроса на курс. Правил здесь нет ни одного — выборка
    группируется по курсу и уходит в те же `build_tree` и `number_lessons`,
    что и одиночный `flatten_lessons`: ни «Мои курсы», ни экран методиста не
    должны считать план как-то по-своему.
    """
    from .models import PlanNode

    course_ids = list(course_ids)
    if not course_ids:
        return {}

    grouped = defaultdict(list)
    for node in PlanNode.objects.filter(course_id__in=course_ids).annotate(
        attachment_count=Count("attachments")
    ):
        grouped[node.course_id].append(node)

    return {
        course_id: number_lessons(build_tree(grouped.get(course_id, ())))
        for course_id in course_ids
    }


class SnapshotRow(NamedTuple):
    """Строка снимка плана: то, что уходит в эталон."""

    is_section: bool
    title: str
    node_id: int


def plan_snapshot(course_id: int) -> list[SnapshotRow]:
    """
    План плоским списком в порядке отображения — форма эталона.

    Та же форма, что у строк шаблона в библиотеке: дерево ровно
    двухуровневое, и плоский список с заголовками выражает его полностью.
    """
    rows = []
    for branch in get_tree(course_id):
        rows.append(SnapshotRow(True, branch.node.title, branch.node.pk)
                    if branch.node.is_section
                    else SnapshotRow(False, branch.node.title, branch.node.pk))
        rows.extend(
            SnapshotRow(False, child.title, child.pk) for child in branch.children
        )

    return rows


def flatten_lessons(course_id: int) -> list[Lesson]:
    """The flat lesson sequence — the one that later lands on the slots."""
    return number_lessons(get_tree(course_id))
