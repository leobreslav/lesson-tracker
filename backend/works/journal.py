"""
Журнал курса: ученики по строкам, занятия по столбцам.

Экран, которого не хватало всему остальному. Оценка живёт у работы, работа —
у курса, посещаемость — у занятия, и до сих пор каждая из трёх отвечала на
свой вопрос со своего экрана. Вопрос «как идёт курс у этого класса» не
задавался нигде, хотя задают его чаще всех прочих — на родительском собрании,
на педсовете и просто в конце четверти.

**Столбец — это занятие, а не работа**, и вот почему именно так. Работ на
одном занятии бывает несколько (проверочная и домашняя разом), а бывает ни
одной — и тогда столбец всё равно нужен: в нём стоит посещаемость. Сделай
столбцом работу, и журнал перестал бы быть журналом: он потерял бы дни, в
которые ничего не задавали, то есть большую часть года.

Отсюда же следует, что **работа цепляется за занятие** (`Work.slot`), и связь
эта необязательна: контрольная за четверть, пересдача, работа «на неделю».
Такие не пропадают — они идут своими столбцами в конце, и стоит там не дата, а
только имя работы. Потерять оценку потому, что учитель не указал занятие, было
бы худшим видом чистоты.

**Считается всё одним проходом.** Тридцать учеников на семьдесят занятий — это
две тысячи клеток, и запрос на клетку не открыл бы экран вовсе. Поэтому
выборок ровно четыре — занятия, работы, строки учеников, посещаемость, — а
складывает их питон.

Право живёт в вызывающем: учитель отдаёт сюда весь состав курса, семья —
одного человека. Расчёт от этого не меняется ни на строку, и это то же
решение, что у `files_of(staff=...)`: пока вопрос один, ответов должно быть
два, но расчёт один.
"""

from collections import defaultdict

from schedule.models import Attendance, Slot

from .models import CLOSED, StudentWork, Work


def terms_of(course) -> list:
    """Термы года, к которому привязан курс. Пустой список — год без разметки."""
    from calendars.models import Term

    return list(Term.objects.filter(year_id=course.year_id).order_by("start_date", "id"))


def current_term(terms, today):
    """
    Терм, в котором идёт сегодняшний день, а иначе ближайший прошедший.

    Каникулы в терм не входят вовсе (`calendars`), и «сегодня ни в одном» —
    обычное состояние, а не край. Показывать в этот день пустой экран было бы
    неправдой о курсе: четверть кончилась, а оценки за неё никуда не делись.
    Поэтому в каникулы открывается **прошедшая** четверть, а до начала года —
    первая.
    """
    if not terms:
        return None

    for term in terms:
        if term.start_date <= today <= term.end_date:
            return term

    passed = [term for term in terms if term.end_date < today]
    return passed[-1] if passed else terms[0]


def slots_of(course, term):
    """Занятия курса — все или внутри терма, в порядке, в котором они идут."""
    slots = Slot.objects.filter(course=course).select_related("lesson")
    if term is not None:
        slots = slots.filter(date__gte=term.start_date, date__lte=term.end_date)
    return list(slots.order_by("date", "lesson_number", "id"))


def works_of(course, term, slot_ids):
    """
    Работы, попадающие в этот вид журнала.

    Две дороги, и обе нужны. Привязанная к занятию попадает вместе с ним — по
    занятию, а не по своим датам: «задали на этом уроке» и есть её место в
    журнале. Не привязанная попадает **по дате открытия**: другого признака
    времени у неё нет вовсе, а без него она либо повторялась бы в каждой
    четверти, либо не показывалась ни в одной.
    """
    works = (
        Work.objects.filter(course=course)
        # вид берётся тем же запросом: столбцов до семидесяти, и запрос на
        # значок был бы тем самым запросом на клетку, только в шапке
        .select_related("grading_system", "kind")
        .prefetch_related("tasks", "criteria", "grading_system__bands")
    )

    attached, loose = [], []
    for work in works.order_by("opens_at", "id"):
        if work.slot_id is not None:
            if work.slot_id in slot_ids:
                attached.append(work)
            continue
        if term is None or term.start_date <= work.opens_at.date() <= term.end_date:
            loose.append(work)

    return attached, loose


def build(course, *, term, students, family=False, today=None, active=None) -> dict:
    """
    Журнал целиком: столбцы, строки и клетки.

    `students` — те, чьи строки спрашивают: весь состав у учителя, один
    человек у семьи. `family=True` вдобавок уважает `show_result`: работа,
    результаты которой ещё не разосланы классу, показывает семье пустую
    клетку, а не отметку. Учителю она видна всегда — он её и поставил.
    """
    from django.utils import timezone

    from . import services

    today = today or timezone.localdate()
    slots = slots_of(course, term)
    slot_ids = {slot.pk for slot in slots}
    attached, loose = works_of(course, term, slot_ids)

    by_slot = defaultdict(list)
    for work in attached:
        by_slot[work.slot_id].append(work)

    columns = []
    for slot in slots:
        columns.append(
            {
                "slot": slot.pk,
                "date": slot.date,
                "lesson_number": slot.lesson_number,
                # «состоялось ли» — не то же, что «прошло ли»: отменённый час
                # тоже в прошлом, и клетки в нём быть не должно
                "is_cancelled": slot.is_cancelled,
                "is_extra": slot.is_extra,
                "past": slot.date <= today,
                # тема урока — то, чем этот час занят по программе. Шапка ведёт
                # на занятие, а название объясняет, зачем туда идти
                "lesson": (
                    {"id": slot.lesson_id, "title": slot.lesson.title}
                    if slot.lesson_id
                    else None
                ),
                "works": [_work_head(work) for work in by_slot.get(slot.pk, ())],
            }
        )

    # Работы без занятия — своими столбцами в конце, и даты у них нет: она
    # была бы выдумкой. Порядок между собой — по открытию окна.
    for work in loose:
        columns.append(
            {
                "slot": None,
                "date": None,
                "lesson_number": None,
                "is_cancelled": False,
                "is_extra": False,
                "past": work.opens_at.date() <= today,
                "lesson": None,
                "works": [_work_head(work)],
            }
        )

    people = list(students)
    everyone = [person.pk for person in people]
    works_here = attached + loose
    # работа по номеру: клеток две тысячи, и поиск по списку в каждой из них
    # был бы тем самым запросом на клетку, только в питоне
    by_id = {work.pk: work for work in works_here}

    rows = {
        (row.work_id, row.student_id): row
        for row in StudentWork.objects.filter(
            work__in=works_here, student__in=everyone
        ).prefetch_related("marks")
    }
    presence = {
        (row.slot_id, row.student_id): row
        for row in Attendance.objects.filter(slot__in=slot_ids, student__in=everyone)
    }

    # Отметка, которую семье ещё рано видеть, не считается вовсе: `show_result`
    # решает, разошлась ли она по классу, и обходить его журналом нельзя.
    shown = {
        work.pk: (not family) or work.show_result or work.state() == CLOSED
        for work in works_here
    }

    students_out = []
    for person in people:
        cells = []
        for column in columns:
            marks = []
            for head in column["works"]:
                work = by_id[head["id"]]
                if not shown[work.pk]:
                    continue
                row = rows.get((work.pk, person.pk))
                grade = services.final_grade(work, row) if row else None
                if grade is None:
                    continue
                marks.append(
                    {
                        "work": work.pk,
                        "label": grade["label"],
                        "by_teacher": grade["by_teacher"],
                        "earned": grade["earned"],
                        "top": grade["top"],
                    }
                )

            seen = presence.get((column["slot"], person.pk)) if column["slot"] else None
            cells.append(
                {
                    "marks": marks,
                    "attendance": seen.status if seen else None,
                    "note": seen.note if seen else "",
                }
            )

        students_out.append(
            {
                "id": person.pk,
                "name": services.full_name(person),
                # Снятый с курса остаётся строкой и помечен — то же решение,
                # что в сводной таблице работы: оценки его никуда не делись, а
                # спрашивать «почему у него пусто в декабре» будут о нём же.
                "active": active is None or person.pk in active,
                "cells": cells,
            }
        )

    return {
        "course": {"id": course.pk, "name": course.name},
        "term": term.pk if term else None,
        "columns": columns,
        "students": students_out,
    }


def _work_head(work) -> dict:
    """
    Работа глазами шапки столбца: имя, вид и по чему её оценивают.

    Полосы системы едут сюда затем, что оценку ставят **в клетке**: меню
    выбора наполняется ими, и брать их вторым запросом на каждый столбец
    значило бы семьдесят запросов на открытие журнала. Пустой список —
    законное состояние: у работы без системы отметка свободная, и предлагать
    в меню нечего.
    """
    return {
        "id": work.pk,
        "title": work.title,
        "bands": (
            [band.label for band in work.grading_system.bands.all()]
            if work.grading_system_id
            else []
        ),
        # Вид работы из справочника школы: им подписан значок в шапке и им же
        # выбран его цвет. Пусто — законно и у школы без справочника обычно:
        # тогда значок падает на прежний расчёт, «итоговая или нет».
        "kind": (
            {
                "id": work.kind_id,
                "name": work.kind.name,
                "label": work.kind.label,
                "color": work.kind.color,
            }
            if work.kind_id
            else None
        ),
        # итоговая ли она: в шапке это единственное, что отличает контрольную
        # от домашней, а вес у них разный
        "is_summative": work.is_summative,
        "is_homework": work.is_homework,
        "state": work.state(),
    }
