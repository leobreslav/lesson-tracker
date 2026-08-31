"""
Как идут планы — для любого набора владельцев.

Два экрана задают один и тот же вопрос. Учитель на главной спрашивает про
свои курсы; методист в разделе «На утверждение» — про планы, которые он
ведёт: чужие, по нескольким курсам, иногда по нескольку человек на курс.
Ответ обоим нужен одинаковый — где идёт план, помещается ли он в год, как
разошёлся с эталоном, — и считать его дважды значило бы завести два ответа
на один вопрос.

Поэтому здесь одна функция: на вход курсы, на выход готовые строки. Кто
эти курсы собрал — дело вызывающего: у учителя это его курсы, у методиста
— курсы, где он назначен.

Единица — курс, а не пара «учитель и курс»: план принадлежит курсу, и
ведущий учитель у курса один. Пока их могло быть двое, у одного курса
было два плана и две строки — и это как раз то состояние, ради которого
`CourseAssignment` теперь уникален по курсу.

Запросы делаются **до** цикла: раньше каждый курс стоил шести, и экран,
который открывают из бара, обходился в тридцать семь. Расчёт при этом не
свой — это те же `build_layout` и `count_layout`, что и во всех остальных
ответах про раскладку.
"""

from __future__ import annotations

from collections import defaultdict

from django.contrib.auth import get_user_model
from schedule.models import Course, CourseAssignment, CourseMethodist, Slot

from . import approval, services
from .serializers import person, request_payload

User = get_user_model()


def own_courses(user) -> list:
    """Свои курсы, в порядке года и названия."""
    return list(
        Course.objects.for_teacher(user)
        .select_related("year", "subject", "grade")
        .prefetch_related("year__terms")
        .order_by("year__start_date", "name")
    )


def supervised_courses(user) -> list:
    """
    Курсы, планы которых ведёт методист.

    Курс без назначенного учителя в списке всё равно есть, и это не
    оплошность: «нагрузку ещё не раздали» — то, что методисту как раз
    нужно видеть, как и «назначили, но план не начат».
    """
    return list(
        approval.supervised(user)
        # `grade` тут не украшение: строка несёт год обучения, и без него
        # каждый курс стоил бы отдельного запроса за параллелью
        .select_related("year", "subject", "grade")
        .prefetch_related("year__terms")
        .order_by("year__start_date", "name")
    )


def teachers_of(courses) -> dict:
    """Ведущий учитель по каждому курсу: `{course_id: user | None}`."""
    courses = list(courses)
    if not courses:
        return {}

    return {
        row.course_id: row.teacher
        for row in CourseAssignment.objects.filter(
            course__in=courses
        ).select_related("teacher")
    }


def rows_for(courses, today, ahead: int = 2) -> list[dict]:
    """
    Строка состояния на каждый курс — то, из чего собраны обе страницы.

    Поля одни и те же, включая `teacher` и `subject`: у себя на главной
    учитель их не показывает, но два ответа с разными наборами полей развели
    бы и два компонента, которые сейчас один.
    """
    courses = list(courses)
    if not courses:
        return []

    course_ids = [course.pk for course in courses]
    lessons_by_course = services.lessons_by_course(course_ids)
    baselines = approval.approved_baselines(course_ids)
    requests = approval.open_requests(course_ids)
    teachers = teachers_of(courses)

    slots_by_course = defaultdict(list)
    for slot in Slot.objects.filter(
        course_id__in=course_ids, is_cancelled=False
    ).order_by("date", "lesson_number"):
        slots_by_course[slot.course_id].append(slot)

    rows = []
    for course in courses:
        key = course.pk
        lessons = lessons_by_course[key]
        entries = services.build_layout(
            lessons, slots_by_course[key], course.year.terms.all()
        )
        baseline = baselines.get(key)
        teacher = teachers.get(key)

        rows.append(
            {
                "id": course.pk,
                "name": course.name,
                "year": course.year.name,
                "year_end": course.year.end_date,
                # предмет — рядом с учителем и по той же причине: в чужом
                # списке курсов сужают именно по этим двум, а у методиста
                # школы в списке их несколько десятков
                "subject": course.subject.name if course.subject else None,
                # год обучения — ради витрины планов: она сужает все четыре
                # свои области одними и теми же предметом и параллелью, а
                # поднадзорный курс приезжает сюда, а не сериализатором
                # курса. Без него сужение молча врало бы ровно в одной
                # области из четырёх — то есть выглядело бы как «у коллеги
                # нет планов по этому году», а не как нехватка поля.
                "grade_level": course.grade.level if course.grade else None,
                "teacher": person(teacher) if teacher else None,
                # метрики считаются только от **утверждённого** эталона:
                # пока план не приняли, сравнивать не с чем
                # Утверждённый эталон — состояние, а не разбор: когда
                # подписали и кто. Чем план с тех пор разошёлся, отвечает
                # сравнение (`plans/diff.py`) — точное, построчное и общее
                # с автором плана. Второй ответ на тот же вопрос жил тут
                # («+3 добавлено, 1 удалено») и разошёлся бы с первым молча:
                # тот считает переименование правкой, этот — ничем
                "baseline": (
                    {
                        "created_at": baseline.created_at,
                        "approved_at": baseline.approved_at,
                        "self_approved": baseline.self_approved,
                        "reviewer": person(baseline.reviewer),
                        # почему резерв стал таким: часы против программы
                        "reserve": services.reserve_since(
                            baseline.slots_total,
                            sum(
                                1
                                for row in baseline.rows.all()
                                if not row.is_section
                            ),
                            len(slots_by_course[key]),
                            len(lessons),
                        ),
                    }
                    if baseline
                    else None
                ),
                "review": request_payload(requests.get(key)),
                # долги по записи: сколько занятий закрыто и сколько ждёт.
                # Считаются по тем же слотам, из которых собрана раскладка
                "records": services.record_state(slots_by_course[key], today),
                **services.course_progress(entries, today, ahead=ahead),
            }
        )

    return rows


def is_methodist(user) -> bool:
    return CourseMethodist.objects.filter(user=user).exists()
