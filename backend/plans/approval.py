"""
Утверждение учебного плана методистом.

Состояния у самого плана нет — учитель правит его свободно. Состояние есть
у **запроса**: план отправляют на утверждение, методист смотрит его как
есть, и копия структуры снимается в момент **утверждения** — эталоном
становится ровно то, что приняли.

Правка отзывает поданный запрос, и это то, что делает схему безопасной:
утвердить можно только план, не менявшийся с момента отправки. Иначе
методист читал бы одно, а утверждал другое.

Здесь же живёт единственное место, откуда позже пойдут письма: `notify`
вызывается на каждом переходе, и рассылку добавят в него, а не в четыре
вьюхи по отдельности.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from schedule.models import CourseMethodist

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
    Отправить план на утверждение.

    Строк у запроса пока нет: методист смотрит живой план, а копия
    снимается при утверждении. Читать он при этом будет именно то, что ему
    прислали, — любая правка отзывает запрос, так что утверждать
    изменившийся план попросту не из чего.

    Прежние неутверждённые запросы уходят — висеть двум разом незачем, — а
    утверждённый эталон остаётся: пока новый не принят, расхождение
    считается от него.
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
