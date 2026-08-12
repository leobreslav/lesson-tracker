"""
Copying the school timetable into one teacher's own schedule.

A one-way, one-time operation. What lands in `LessonSlot` is an ordinary
lesson of that teacher's, with no link back: editing the timetable afterwards
does not reach it, and editing the copy does not reach the timetable. That is
the whole point — a schedule somebody has already annotated must not be
rewritten under them by an edit made elsewhere.

The preview and the import itself run the same planning code, so what the
teacher is shown and what they get cannot disagree.
"""

from collections import defaultdict

from django.db import transaction

from . import services
from .models import LessonSlot, MasterSlot

MERGE = "merge"
REPLACE = "replace"


def master_rows(*, teacher, year, courses=None, start, end):
    """
    The teacher's own rows of the school timetable over a period.

    Rows with nobody assigned are not here by construction: the filter is on
    this teacher, and a row without a teacher belongs to no one.
    """
    rows = MasterSlot.objects.filter(
        school_id=teacher.school_id,
        year=year,
        teacher=teacher,
        date__range=(start, end),
    )
    if courses:
        rows = rows.filter(course__in=courses)

    return rows.select_related("course").order_by("date", "lesson_number")


def plan_import(*, teacher, year, courses=None, start, end, mode=MERGE):
    """
    Work out what an import would do, without doing any of it.

    Course by course, because that is how occupancy works: a number is either
    already used by this course (silently skipped) or by another course of
    the same teacher (skipped and reported — nobody teaches two at once).
    Lessons planned earlier in this very run count as taken too, or two
    courses would be handed the same hour.

    In `replace` mode the teacher's existing lessons in those courses are
    treated as gone, because that is what the import will do to them.
    """
    rows = list(master_rows(teacher=teacher, year=year, courses=courses, start=start, end=end))

    by_course = defaultdict(list)
    for row in rows:
        by_course[row.course].append(row)

    course_ids = {course.pk for course in by_course}
    mine = LessonSlot.objects.filter(
        teacher=teacher, date__range=(start, end)
    ).select_related("course")

    doomed = {slot.pk for slot in mine if slot.course_id in course_ids} if mode == REPLACE else set()

    # numbers this teacher already spends, mapped to whoever holds them
    busy = {
        (slot.date, slot.lesson_number): slot.course.name
        for slot in mine
        if slot.pk not in doomed and not slot.is_cancelled
    }

    planned, conflicts, skipped = [], [], 0
    per_course = []

    for course, course_rows in sorted(by_course.items(), key=lambda pair: pair[0].name):
        occupied = {
            (slot.date, slot.lesson_number)
            for slot in mine
            if slot.course_id == course.pk and slot.pk not in doomed
        }
        # this course's own numbers are not a conflict, only a skip
        others = {key: name for key, name in busy.items() if name != course.name}

        result = services.place_copies(
            plan=[(row.date, row.lesson_number) for row in course_rows],
            skipped=0,
            occupied=occupied,
            busy=others,
            make=lambda day, number, course=course: LessonSlot(
                year=year,
                teacher=teacher,
                course=course,
                date=day,
                lesson_number=number,
            ),
        )

        planned.extend(result["created"])
        conflicts.extend(result["conflicts"])
        skipped += result["skipped"]
        per_course.append(
            {
                "id": course.pk,
                "name": course.name,
                "available": len(course_rows),
                "created": len(result["created"]),
            }
        )

        # what we just planned occupies those hours for the next course
        for slot in result["created"]:
            busy[(slot.date, slot.lesson_number)] = course.name

    return {
        "slots": planned,
        "courses": per_course,
        "conflicts": conflicts,
        "skipped": skipped,
        "replaced": len(doomed),
        "doomed": doomed,
    }


@transaction.atomic
def run_import(*, teacher, year, courses=None, start, end, mode=MERGE):
    """
    Do it. One transaction: a half-imported week is worse than none.

    The plan is recomputed here rather than taken from the preview — the
    preview may be minutes old, and the database is the only thing that
    knows what is true now.
    """
    plan = plan_import(
        teacher=teacher, year=year, courses=courses, start=start, end=end, mode=mode
    )

    deleted = 0
    if plan["doomed"]:
        deleted, _ = LessonSlot.objects.filter(pk__in=plan["doomed"]).delete()

    LessonSlot.objects.bulk_create(plan["slots"])

    return {
        "created": len(plan["slots"]),
        "skipped": plan["skipped"],
        "deleted": deleted,
        "courses": plan["courses"],
        "conflicts": plan["conflicts"],
    }
