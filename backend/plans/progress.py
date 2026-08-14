"""
Как идут планы — для любого набора владельцев.

Два экрана задают один и тот же вопрос. Учитель на главной спрашивает про
свои курсы; методист в разделе «На утверждение» — про планы, которые он
ведёт: чужие, по нескольким курсам, иногда по нескольку человек на курс.
Ответ обоим нужен одинаковый — где идёт план, помещается ли он в год, как
разошёлся с эталоном, — и считать его дважды значило бы завести два ответа
на один вопрос.

Поэтому здесь одна функция: на вход пары «учитель и курс», на выход
готовые строки. Кто эти пары собрал — дело вызывающего: у учителя это его
курсы, у методиста — курсы, где он назначен.

Запросы делаются **до** цикла: раньше каждый курс стоил шести, и экран,
который открывают из бара, обходился в тридцать семь. Расчёт при этом не
свой — это те же `build_layout` и `count_layout`, что и во всех остальных
ответах про раскладку.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from django.contrib.auth import get_user_model
from django.db.models import Q
from schedule.models import Course, CourseAssignment, CourseMethodist, LessonSlot

from . import approval, services
from .models import PlanNode
from .serializers import person, request_payload

User = get_user_model()


def own_pairs(user) -> list[tuple]:
    """Свои курсы: пары «я и курс», в порядке года и названия."""
    courses = (
        Course.objects.for_teacher(user)
        .select_related("year")
        .prefetch_related("year__terms")
        .order_by("year__start_date", "name")
    )
    return [(user, course) for course in courses]


def supervised_pairs(user) -> list[tuple]:
    """
    Планы, которые ведёт методист: пары «учитель и курс».

    Курс общий, а план внутри него у каждого свой, поэтому единицей здесь
    служит пара, а не курс: методист «9Б Алгебры», которую ведут двое,
    отвечает за два плана.

    Кто считается ведущим курс — то же правило, что и в списке курсов
    учителя (`Course.objects.for_teacher`): назначенные плюс те, у кого в
    курсе уже есть план. Вторая половина нужна, потому что назначение
    можно снять, а работа остаётся, и пропадать из-под надзора она не
    должна.

    Назначенный без плана в списке всё равно есть, и это не оплошность:
    «ещё не начал» — то, что методисту как раз нужно видеть.
    """
    courses = list(
        Course.objects.filter(methodists__user=user)
        .select_related("year")
        .prefetch_related("year__terms")
        .order_by("year__start_date", "name")
    )
    if not courses:
        return []

    people = defaultdict(dict)
    assignments = CourseAssignment.objects.filter(
        course__in=courses
    ).select_related("teacher")
    for row in assignments:
        people[row.course_id][row.teacher_id] = row.teacher

    # `values_list` вместо `distinct(...)`: у модели свой `ordering`, а
    # Postgres требует, чтобы DISTINCT ON совпадал с началом ORDER BY
    authors = (
        PlanNode.objects.filter(course__in=courses)
        .values_list("course_id", "teacher_id")
        .distinct()
    )
    missing = {teacher_id for _, teacher_id in authors} - {
        teacher.pk for row in people.values() for teacher in row.values()
    }
    known = {user.pk: user for user in User.objects.filter(pk__in=missing)}
    for course_id, teacher_id in authors:
        if teacher_id in known:
            people[course_id].setdefault(teacher_id, known[teacher_id])

    pairs = []
    for course in courses:
        for teacher in sorted(
            people[course.pk].values(), key=lambda item: (item.first_name, item.email)
        ):
            pairs.append((teacher, course))

    return pairs


def rows_for(pairs, today, ahead: int = 2) -> list[dict]:
    """
    Строка состояния на каждую пару — то, из чего собраны обе страницы.

    Поля одни и те же, включая `teacher`: у себя на главной учитель его не
    показывает, но два ответа с разными наборами полей развели бы и два
    компонента, которые сейчас один.
    """
    pairs = list(pairs)
    if not pairs:
        return []

    owners = [
        services.PlanOwner(teacher_id=teacher.pk, course_id=course.pk)
        for teacher, course in pairs
    ]
    lessons_by_owner = services.lessons_by_owner(owners)
    baselines = approval.approved_baselines(owners)
    requests = approval.open_requests(owners)

    condition = Q()
    for owner in owners:
        condition |= Q(teacher_id=owner.teacher_id, course_id=owner.course_id)

    slots_by_owner = defaultdict(list)
    cancelled_by_owner = Counter()
    for slot in LessonSlot.objects.filter(condition).order_by(
        "date", "lesson_number"
    ):
        key = (slot.teacher_id, slot.course_id)
        if slot.is_cancelled:
            cancelled_by_owner[key] += 1
        else:
            slots_by_owner[key].append(slot)

    rows = []
    for (teacher, course), owner in zip(pairs, owners):
        key = tuple(owner)
        lessons = lessons_by_owner[owner]
        entries = services.build_layout(
            lessons, slots_by_owner[key], course.year.terms.all()
        )
        baseline = baselines.get(key)

        rows.append(
            {
                "id": course.pk,
                "name": course.name,
                "year": course.year.name,
                "year_end": course.year.end_date,
                "teacher": person(teacher),
                # метрики считаются только от **утверждённого** эталона:
                # пока план не приняли, сравнивать не с чем
                "baseline": (
                    {
                        "created_at": baseline.created_at,
                        "approved_at": baseline.approved_at,
                        "self_approved": baseline.self_approved,
                        **services.baseline_diff(baseline.rows.all(), lessons),
                    }
                    if baseline
                    else None
                ),
                "review": request_payload(requests.get(key)),
                **services.course_progress(
                    entries, today, cancelled_by_owner[key], ahead=ahead
                ),
            }
        )

    return rows


def is_methodist(user) -> bool:
    return CourseMethodist.objects.filter(user=user).exists()
