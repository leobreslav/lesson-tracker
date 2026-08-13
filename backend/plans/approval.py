"""
Утверждение учебного плана методистом.

Состояния у самого плана нет — учитель правит его свободно. Состояние есть
у **снимка**: план отправляют на утверждение, и в этот момент с него
снимается копия структуры. Дальше методист смотрит именно её, а учитель
может продолжать править план: правка отзовёт запрос, но того, что уже
прислали, не изменит.

Здесь же живёт единственное место, откуда позже пойдут письма: `notify`
вызывается на каждом переходе, и рассылку добавят в него, а не в четыре
вьюхи по отдельности.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from schools.models import SubjectMethodist

from . import services
from .models import PlanBaseline, PlanBaselineRow

logger = logging.getLogger(__name__)

SUBMITTED = "submitted"
APPROVED = "approved"
RETURNED = "returned"
WITHDRAWN = "withdrawn"


def notify(event: str, baseline: PlanBaseline) -> None:
    """
    Событие процедуры: отправили, утвердили, вернули, отозвали.

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

    По предмету курса и внутри его школы: методист чужой школы не увидит
    ни плана, ни того, что он существует. Курс без предмета отправить
    некому — это и есть случай «методист не назначен».
    """
    if course.subject_id is None:
        return []

    return list(
        SubjectMethodist.objects.filter(
            school=course.school, subject_id=course.subject_id
        ).select_related("user")
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


def open_request(teacher_id: int, course_id: int):
    """
    Последний неутверждённый запрос: поданный, возвращённый или отозванный.

    Отозванный тоже показывается, и это важно: учитель, поправивший план,
    должен увидеть, что запрос больше никого не ждёт, — иначе он будет
    думать, что план на утверждении, а тот лежит у него же в черновиках.
    """
    return (
        PlanBaseline.objects.filter(
            teacher_id=teacher_id,
            course_id=course_id,
            status__in=(
                PlanBaseline.Status.PENDING,
                PlanBaseline.Status.RETURNED,
                PlanBaseline.Status.DRAFT,
            ),
        )
        .order_by("-created_at", "-id")
        .first()
    )


@transaction.atomic
def submit(owner: services.PlanOwner, course, reviewer) -> PlanBaseline:
    """
    Снять копию плана и отправить её на утверждение.

    Копия снимается **сейчас**, а не при утверждении: методист смотрит то,
    что ему прислали. Прежние неутверждённые снимки этого плана уходят —
    висеть двум запросам разом незачем, — а утверждённый остаётся: пока
    новый не принят, расхождение считается от него.
    """
    PlanBaseline.objects.filter(
        teacher_id=owner.teacher_id,
        course_id=owner.course_id,
        status__in=(
            PlanBaseline.Status.PENDING,
            PlanBaseline.Status.RETURNED,
            PlanBaseline.Status.DRAFT,
        ),
    ).delete()

    baseline = PlanBaseline.objects.create(
        teacher_id=owner.teacher_id,
        course_id=owner.course_id,
        status=PlanBaseline.Status.PENDING,
        submitted_at=timezone.now(),
        reviewer=reviewer,
    )
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

    notify(SUBMITTED, baseline)
    return baseline


def approve(baseline: PlanBaseline, reviewer) -> PlanBaseline:
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


def withdraw(teacher_id: int, course_id: int) -> int:
    """
    Правка плана отзывает поданный запрос.

    Иначе методист утверждал бы одно, а в силе оказывалось другое. Снимок
    при этом остаётся: он и есть свидетельство того, что присылали, — но
    больше никого не ждёт.

    Возвращает число отозванных запросов: ноль в подавляющем большинстве
    правок, и по нему видно, что звать `notify` не за чем.
    """
    pending = list(
        PlanBaseline.objects.filter(
            teacher_id=teacher_id,
            course_id=course_id,
            status=PlanBaseline.Status.PENDING,
        )
    )
    if not pending:
        return 0

    PlanBaseline.objects.filter(pk__in=[item.pk for item in pending]).update(
        status=PlanBaseline.Status.DRAFT
    )
    for baseline in pending:
        notify(WITHDRAWN, baseline)

    return len(pending)


def review_queue(user):
    """
    Что видит методист: запросы по **его** предметам, в его школе.

    Не «присланные лично ему»: методистов по предмету может быть несколько,
    и запрос, отправленный коллеге, всё равно про его предмет — прятать его
    значило бы делать вид, что предмет поделён между людьми.
    """
    subjects = SubjectMethodist.objects.filter(user=user).values_list(
        "subject_id", flat=True
    )
    if not subjects:
        return PlanBaseline.objects.none()

    return (
        PlanBaseline.objects.filter(
            status=PlanBaseline.Status.PENDING,
            course__school=user.school,
            course__subject_id__in=list(subjects),
        )
        .select_related("course", "teacher", "course__subject")
        .order_by("submitted_at")
    )
