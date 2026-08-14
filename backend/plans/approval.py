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
from django.db.models import Q
from django.utils import timezone
from schedule.models import CourseMethodist

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
        "plan review: %s course=%s teacher=%s reviewer=%s",
        event,
        baseline.course_id,
        baseline.teacher_id,
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


def approved_baseline(teacher_id: int, course_id: int):
    """Утверждённый эталон — тот, относительно которого считают расхождение."""
    return (
        PlanBaseline.objects.filter(
            teacher_id=teacher_id,
            course_id=course_id,
            status=PlanBaseline.Status.APPROVED,
        )
        .order_by("-approved_at", "-id")
        .first()
    )


def _owned(owners) -> Q:
    """Условие «любая из этих пар (учитель, курс)» одним запросом."""
    condition = Q()
    for owner in owners:
        condition |= Q(teacher_id=owner.teacher_id, course_id=owner.course_id)
    return condition


def approved_baselines(owners) -> dict:
    """
    Утверждённые эталоны сразу по нескольким владельцам:
    `{(teacher_id, course_id): baseline}`.

    Порядок тот же, что у `approved_baseline`, и это важнее краткости:
    выборка идёт по возрастанию, а в словаре остаётся последний — то есть
    самый свежий, ровно тот, который вернул бы одиночный запрос.

    Ключ — пара, а не курс: у методиста один курс встречается столько раз,
    сколько человек его ведёт, и эталон у каждого свой.

    Строки снимка тянутся сразу: без них `baseline_diff` сходит за запросом
    на каждую пару.
    """
    owners = list(owners)
    if not owners:
        return {}

    return {
        (baseline.teacher_id, baseline.course_id): baseline
        for baseline in PlanBaseline.objects.filter(
            _owned(owners), status=PlanBaseline.Status.APPROVED
        )
        .order_by("approved_at", "id")
        .prefetch_related("rows")
    }


def open_requests(owners) -> dict:
    """Запросы в работе по нескольким владельцам — так же, как `open_request`."""
    owners = list(owners)
    if not owners:
        return {}

    return {
        (baseline.teacher_id, baseline.course_id): baseline
        for baseline in PlanBaseline.objects.filter(
            _owned(owners),
            status__in=(PlanBaseline.Status.PENDING, PlanBaseline.Status.RETURNED),
        )
        .select_related("reviewer")
        .order_by("created_at", "id")
    }


def open_request(teacher_id: int, course_id: int):
    """Запрос в работе: поданный или возвращённый с замечанием."""
    return (
        PlanBaseline.objects.filter(
            teacher_id=teacher_id,
            course_id=course_id,
            status__in=(PlanBaseline.Status.PENDING, PlanBaseline.Status.RETURNED),
        )
        .order_by("-created_at", "-id")
        .first()
    )


@transaction.atomic
def submit(owner: services.PlanOwner, course, reviewer) -> PlanBaseline:
    """
    Отправить план на утверждение.

    Строк у запроса нет: методист смотрит **текущий** план, а копия
    снимается при утверждении. Повторная отправка, пока запрос висит, не
    заводит второй — обновляет дату и адресата: у одного плана один запрос,
    иначе очередь методиста заполнилась бы одним и тем же курсом.

    Утверждённый эталон при этом остаётся: пока новый не принят,
    расхождение считается от него.
    """
    baseline = open_request(owner.teacher_id, owner.course_id)

    if baseline is None:
        baseline = PlanBaseline.objects.create(
            teacher_id=owner.teacher_id,
            course_id=owner.course_id,
            status=PlanBaseline.Status.PENDING,
            submitted_at=timezone.now(),
            reviewer=reviewer,
        )
    else:
        baseline.status = PlanBaseline.Status.PENDING
        baseline.submitted_at = timezone.now()
        baseline.reviewer = reviewer
        baseline.comment = ""
        baseline.save(update_fields=["status", "submitted_at", "reviewer", "comment"])

    notify(SUBMITTED, baseline)
    return baseline


@transaction.atomic
def approve(baseline: PlanBaseline, reviewer) -> PlanBaseline:
    """
    Утвердить — и в этот же момент снять копию плана.

    Эталоном становится ровно то, что приняли. План с момента отправки не
    менялся: правка отозвала бы запрос, и утверждать было бы нечего.
    """
    owner = services.PlanOwner(
        teacher_id=baseline.teacher_id, course_id=baseline.course_id
    )
    baseline.rows.all().delete()
    PlanBaselineRow.objects.bulk_create(
        PlanBaselineRow(
            baseline=baseline,
            position=position,
            is_section=row.is_section,
            title=row.title,
            node_id=row.node_id,
        )
        for position, row in enumerate(services.plan_snapshot(owner))
    )

    baseline.status = PlanBaseline.Status.APPROVED
    baseline.approved_at = timezone.now()
    baseline.reviewer = reviewer
    baseline.comment = ""
    baseline.save(update_fields=["status", "approved_at", "reviewer", "comment"])

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
        .select_related("course", "teacher", "course__subject")
        .order_by("submitted_at")
    )
