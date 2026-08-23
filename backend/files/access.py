"""
Who may see and change an attachment.

The rule is about the **attachment**, not about the file behind it. One
`StoredFile` can serve a template on the school's shelf and a dozen personal
plans; a teacher may reach it through their own lesson and through the
published template, and not through a colleague's plan — even though all
three point at the very same object in the bucket. Asking "may you read this
file" would have no single answer; asking "may you read this reference" has.

Two refusals, as everywhere else in the project, but drawn slightly
differently here:

* another school — **404**. The attachment is out of the queryset and a
  stranger learns nothing;
* one's own school, someone else's lesson — **403** with a code. Inside a
  school people already know their colleagues exist, and "not yours" is a
  more useful answer than pretending the id is free.
"""

from django.db.models import Q
from library.models import PlanTemplateRow
from library.serializers import visible_templates
from plans.models import PlanNode

from .models import Attachment


def school_attachments(user):
    """Everything hanging off a lesson row of this person's school."""
    if user is None or not user.is_authenticated or user.school_id is None:
        return Attachment.objects.none()

    if getattr(user, "is_student", False):
        # у ученика «школьные вложения» это его собственные: остальные для
        # него не существуют, и разница «нет такого» / «не ваше» тут ни к
        # чему — он и не должен знать, что у одноклассника что-то есть
        return Attachment.objects.filter(student_work__student=user)

    return Attachment.objects.filter(
        Q(plan_row__course__school_id=user.school_id)
        | Q(template_row__template__school_id=user.school_id)
        | Q(student_work__work__course__school_id=user.school_id)
    )


def readable_attachments(user):
    """
    What may appear in a list: one's own lessons, and templates open to one.

    A colleague's draft is absent here for the same reason it is absent from
    the library list — not hidden, not there.
    """
    from schedule.models import Course

    if user is None or not user.is_authenticated or user.school_id is None:
        return Attachment.objects.none()

    if getattr(user, "is_student", False):
        # ученику виден ровно один вид вложений — сканы его собственных
        # работ. Ни плана, ни полки он не читает вовсе
        return Attachment.objects.filter(student_work__student=user)

    return Attachment.objects.filter(
        # вложения строки плана и сканы работ — часть содержания курса,
        # значит и право на них то же: ведущий или администратор школы
        Q(plan_row__course__in=Course.objects.writable_by(user))
        | Q(template_row__template__in=visible_templates(user))
        | Q(student_work__work__course__in=Course.objects.writable_by(user))
    )


def readable_stored_file(user, file_id: int):
    """
    Объект в бакете, который этому человеку **есть чем** открыть.

    Картинка в содержании урока называет файл, а не вложение (см.
    `plans.content.IMAGE_REF`): id вложения у каждой копии свой, и разметка,
    пережившая перенос плана с полки, назвала бы чужой номер.

    Право от этого не размывается. Спрашивается по-прежнему про ссылку:
    показать можно тот файл, на который у спрашивающего есть **своя**
    читаемая ссылка. Чужой урок, где стоит та же картинка, ответа не даёт —
    и наоборот, свой урок даёт его независимо от того, чей файл был первым.
    """
    from .models import StoredFile

    if user is None or not user.is_authenticated:
        return None

    return StoredFile.objects.filter(
        pk=file_id, attachments__in=readable_attachments(user)
    ).first()


def can_read(user, attachment) -> bool:
    from schedule.models import Course

    if attachment.student_work_id is not None:
        # скан работы: свой ученик и ведущий курса, и больше никто. Ошибка
        # здесь — не «показали лишнее», а чужая контрольная с отметками
        row = attachment.student_work
        if row.student_id == user.pk:
            return True
        return (
            Course.objects.writable_by(user).filter(pk=row.work.course_id).exists()
        )

    if attachment.plan_row_id is not None:
        return (
            Course.objects.writable_by(user)
            .filter(pk=attachment.plan_row.course_id)
            .exists()
        )

    template = attachment.template_row.template
    return template.school_id == user.school_id and (
        template.is_published or template.author_id == user.pk
    )


def can_write(user, attachment) -> bool:
    """
    Changing a reference is changing the lesson it hangs off.

    A school administrator may throw a whole template off the shelf, but not
    edit somebody's lesson line by line — so authorship, not the role, is
    what counts here.
    """
    from schedule.models import CourseAssignment

    if attachment.student_work_id is not None:
        # ученик свою работу не правит: скан — запись учителя о ней, а не
        # его слова. Читает всегда, меняет никогда
        return CourseAssignment.objects.filter(
            course_id=attachment.student_work.work.course_id, teacher=user
        ).exists()

    if attachment.plan_row_id is not None:
        return CourseAssignment.objects.filter(
            course_id=attachment.plan_row.course_id, teacher=user
        ).exists()

    return attachment.template_row.template.author_id == user.pk


def writable_student_works(user):
    """Работы учеников, к которым этот человек может приложить скан."""
    from schedule.models import Course
    from works.models import StudentWork

    if user is None or not user.is_authenticated:
        return StudentWork.objects.none()

    return StudentWork.objects.filter(
        work__course__in=Course.objects.writable_by(user)
    )


def writable_plan_rows(user):
    """
    Уроки плана, к которым этот человек может приложить файл.

    Планы курсов, где он назначен ведущим: план принадлежит курсу, и правит
    его назначенный — то же правило, что у самих строк.
    """
    if user is None or not user.is_authenticated:
        return PlanNode.objects.none()
    return PlanNode.objects.filter(
        course__assignments__teacher=user, is_section=False
    )


def writable_template_rows(user):
    if user is None or not user.is_authenticated or user.school_id is None:
        return PlanTemplateRow.objects.none()

    return PlanTemplateRow.objects.filter(
        template__author=user,
        template__school_id=user.school_id,
        is_header=False,
    )
