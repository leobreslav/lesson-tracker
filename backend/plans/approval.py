"""
Утверждение учебного плана методистом.

Состояния у самого плана нет — учитель правит его свободно. Состояние есть
у **запроса**: план отправляют на утверждение, методист открывает
**текущую** версию плана, и копия структуры снимается в момент утверждения —
эталоном становится ровно то, что приняли.

Правки после отправки ничего не отзывают: запрос висит, пока методист его
не обработает, а утверждает он то, что видит сейчас. Так у процедуры ровно
одно место, где план фиксируется, и ровно одно, где он оценивается.

Здесь же живёт единственное место, откуда позже пойдут письма: `notify`
вызывается на каждом переходе, и рассылку добавят в него, а не в четыре
вьюхи по отдельности.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from schedule.models import CourseMethodist, Slot

from . import services
from .models import PlanBaseline, PlanBaselineRow

logger = logging.getLogger(__name__)

SUBMITTED = "submitted"
APPROVED = "approved"
RETURNED = "returned"


def notify(event: str, baseline: PlanBaseline) -> None:
    """
    Событие процедуры: отправили, утвердили, вернули.

    Писем пока нет — хватает счётчика в интерфейсе, — но событие есть, и
    когда рассылка понадобится, добавлять её придётся в одно место, а не
    искать все переходы по вьюхам.
    """
    logger.info(
        "plan review: %s course=%s submitted_by=%s reviewer=%s",
        event,
        baseline.course_id,
        baseline.submitted_by_id,
        baseline.reviewer_id,
    )


def methodists_for(course) -> list:
    """
    Кому можно отправить план этого курса.

    Методист назначается на курс, а не на предмет: отвечают за конкретный
    «9Б Алгебра», и назначают там же, где раздают сам курс. Никого не
    назначили — плану некуда идти, и это отдельный внятный отказ.
    """
    return list(
        CourseMethodist.objects.filter(course=course).select_related("user")
    )


def approved_baseline(course_id: int):
    """Утверждённый эталон — тот, относительно которого считают расхождение."""
    return (
        PlanBaseline.objects.filter(
            course_id=course_id, status=PlanBaseline.Status.APPROVED
        )
        .order_by("-approved_at", "-id")
        .first()
    )


def approved_baselines(course_ids) -> dict:
    """
    Утверждённые эталоны сразу по нескольким курсам: `{course_id: baseline}`.

    Порядок тот же, что у `approved_baseline`, и это важнее краткости:
    выборка идёт по возрастанию, а в словаре остаётся последний — то есть
    самый свежий, ровно тот, который вернул бы одиночный запрос.

    Строки снимка тянутся сразу: без них `baseline_diff` сходит за запросом
    на каждый курс.
    """
    course_ids = list(course_ids)
    if not course_ids:
        return {}

    return {
        baseline.course_id: baseline
        for baseline in PlanBaseline.objects.filter(
            course_id__in=course_ids, status=PlanBaseline.Status.APPROVED
        )
        .order_by("approved_at", "id")
        .prefetch_related("rows")
    }


def open_requests(course_ids) -> dict:
    """Запросы в работе по нескольким курсам — так же, как `open_request`."""
    course_ids = list(course_ids)
    if not course_ids:
        return {}

    return {
        baseline.course_id: baseline
        for baseline in PlanBaseline.objects.filter(
            course_id__in=course_ids,
            status__in=(PlanBaseline.Status.PENDING, PlanBaseline.Status.RETURNED),
        )
        .select_related("reviewer")
        .order_by("created_at", "id")
    }


def open_request(course_id: int):
    """Запрос в работе: поданный или возвращённый с замечанием."""
    return (
        PlanBaseline.objects.filter(
            course_id=course_id,
            status__in=(PlanBaseline.Status.PENDING, PlanBaseline.Status.RETURNED),
        )
        .order_by("-created_at", "-id")
        .first()
    )


@transaction.atomic
def submit(course, reviewer, sender) -> PlanBaseline:
    """
    Отправить план на утверждение.

    Строк у запроса нет: методист смотрит **текущий** план, а копия
    снимается при утверждении. Повторная отправка, пока запрос висит, не
    заводит второй — обновляет дату и адресата: у одного плана один запрос,
    иначе очередь методиста заполнилась бы одним и тем же курсом.

    Утверждённый эталон при этом остаётся: пока новый не принят,
    расхождение считается от него.

    Кто отправил, запоминается — но владельцем не делает: план и эталон
    принадлежат курсу, и смена ведущего учителя ничего здесь не отзывает.
    """
    baseline = open_request(course.pk)

    if baseline is None:
        baseline = PlanBaseline.objects.create(
            course=course,
            status=PlanBaseline.Status.PENDING,
            submitted_at=timezone.now(),
            submitted_by=sender,
            reviewer=reviewer,
        )
    else:
        baseline.status = PlanBaseline.Status.PENDING
        baseline.submitted_at = timezone.now()
        baseline.submitted_by = sender
        baseline.reviewer = reviewer
        baseline.comment = ""
        baseline.save(
            update_fields=[
                "status",
                "submitted_at",
                "submitted_by",
                "reviewer",
                "comment",
            ]
        )

    notify(SUBMITTED, baseline)
    return baseline


@transaction.atomic
def approve(baseline: PlanBaseline, reviewer) -> PlanBaseline:
    """
    Утвердить — и в этот же момент снять копию плана.

    Эталоном становится ровно то, что приняли. Правки после отправки запрос
    не отзывают: он висит, пока его не обработают, а методист смотрит
    текущую версию плана — значит и снимать надо её, а не то, что было
    отправлено.
    """
    baseline.rows.all().delete()
    PlanBaselineRow.objects.bulk_create(
        PlanBaselineRow(
            baseline=baseline,
            position=position,
            is_section=row.is_section,
            title=row.title,
            node_id=row.node_id,
            content_hash=row.content_hash,
        )
        for position, row in enumerate(services.plan_snapshot(baseline.course_id))
    )

    baseline.status = PlanBaseline.Status.APPROVED
    baseline.approved_at = timezone.now()
    baseline.reviewer = reviewer
    baseline.comment = ""
    # точка отсчёта для резерва: сколько часов было у курса в этот момент
    baseline.slots_total = Slot.objects.filter(
        course_id=baseline.course_id, is_cancelled=False
    ).count()
    baseline.save(
        update_fields=[
            "status",
            "approved_at",
            "reviewer",
            "comment",
            "slots_total",
        ]
    )

    notify(APPROVED, baseline)
    return baseline


def send_back(baseline: PlanBaseline, reviewer, comment: str) -> PlanBaseline:
    baseline.status = PlanBaseline.Status.RETURNED
    baseline.reviewer = reviewer
    baseline.comment = comment
    baseline.save(update_fields=["status", "reviewer", "comment"])

    notify(RETURNED, baseline)
    return baseline


def review_queue(user):
    """
    Что видит методист: запросы по **его** курсам.

    Не «присланные лично ему»: методистов у курса может быть несколько, и
    запрос, отправленный коллеге, всё равно про этот курс — прятать его
    значило бы делать вид, что курс поделён между людьми.
    """
    courses = CourseMethodist.objects.filter(user=user).values_list(
        "course_id", flat=True
    )
    if not courses:
        return PlanBaseline.objects.none()

    return (
        PlanBaseline.objects.filter(
            status=PlanBaseline.Status.PENDING,
            course_id__in=list(courses),
        )
        .select_related("course", "submitted_by", "course__subject")
        .order_by("submitted_at")
    )
