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


def watched_students(user):
    """
    Чьи работы этот человек смотрит как семья: свои или своих детей.

    Один ответ на два вида, и живёт он здесь, а не в двух выборках ниже:
    родитель появился позже ученика, и место, где про него забыли бы,
    показало бы ему пустой список вместо работ ребёнка — или, что хуже,
    чужие работы, если бы забыли в другую сторону.
    """
    from families.viewing import children_of

    if getattr(user, "is_student", False):
        return [user]
    if getattr(user, "is_parent", False):
        return children_of(user)
    return []


def family_attachments(user):
    """
    Что семья видит вообще: сданное своим учеником и заданное ему.

    Два владельца, и они отвечают на разные вопросы. `student_work` — «что
    сдал этот человек», то есть его тетрадь; `work` — «что здесь задано»,
    общее на весь класс: условия одним pdf'ом, картинка в пояснениях.
    Первое личное, второе одинаковое у всех, и не показать второе значило бы
    отдать ученику задание, из которого вырезаны условия.

    Видимость работы при этом не изобретается заново: `visible_works_for` —
    то же правило, по которому работа вообще попадает ученику на экран.
    Ненаступившая работа не существует для него целиком, вместе с
    приложенным.
    """
    from works.services import visible_works_for

    people = watched_students(user)
    return Attachment.objects.filter(
        Q(student_work__student__in=people)
        # `staff_only` снимает у вложения работы одну вещь — класс. Приложенная
        # к работе отсканированная пачка это работы всех учеников разом, и
        # видеть её вправе только тот, кто её и принёс
        | Q(work__in=visible_works_for(people), staff_only=False)
    )


def school_attachments(user):
    """Everything hanging off a lesson row of this person's school."""
    if user is None or not user.is_authenticated or user.school_id is None:
        return Attachment.objects.none()

    if getattr(user, "is_family", False):
        # у семьи «школьные вложения» это её работы: остальные для неё не
        # существуют, и разница «нет такого» / «не ваше» тут ни к чему —
        # знать, что у одноклассника что-то лежит, ей тоже незачем
        return family_attachments(user)

    return Attachment.objects.filter(
        Q(plan_row__course__school_id=user.school_id)
        | Q(template_row__template__school_id=user.school_id)
        | Q(student_work__work__course__school_id=user.school_id)
        | Q(work__course__school_id=user.school_id)
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

    if getattr(user, "is_family", False):
        # семье видны два вида вложений — то, что лежит на работах ученика
        # (скан от учителя и его собственные фотографии), и то, что приложено
        # к самой работе, то есть к заданию. Ни плана, ни полки она не читает
        # вовсе
        return family_attachments(user)

    return Attachment.objects.filter(
        # вложения строки плана и сканы работ — часть содержания курса,
        # значит и право на них то же: ведущий или администратор школы
        Q(plan_row__course__in=Course.objects.writable_by(user))
        | Q(template_row__template__in=visible_templates(user))
        | Q(student_work__work__course__in=Course.objects.writable_by(user))
        | Q(work__course__in=Course.objects.writable_by(user))
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
    from works.services import visible_works_for

    if attachment.work_id is not None:
        # приложенное к заданию: ведущий курса и весь класс, которому эта
        # работа уже открыта. До открытия работы не существует ни для кого из
        # них, и вложение исчезает вместе с ней
        people = watched_students(user)
        if (
            people
            and not attachment.staff_only
            and visible_works_for(people).filter(pk=attachment.work_id).exists()
        ):
            return True
        return (
            Course.objects.writable_by(user)
            .filter(pk=attachment.work.course_id)
            .exists()
        )

    if attachment.student_work_id is not None:
        # работа ученика: он сам, его родитель и ведущий курса, и больше
        # никто. Ошибка здесь — не «показали лишнее», а чужая контрольная с
        # отметками
        row = attachment.student_work
        if row.student_id in {person.pk for person in watched_students(user)}:
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

    if attachment.work_id is not None:
        # задание правит тот, кто его задал: ведущий курса. Ученику сюда
        # нельзя вовсе — его дело сдать, а не переписать условие
        return CourseAssignment.objects.filter(
            course_id=attachment.work.course_id, teacher=user
        ).exists()

    if attachment.student_work_id is not None:
        # Учительская дверь, и в неё семья не проходит **вовсе** — даже за
        # своей же фотографией. Своё она снимает своей дверью
        # (`/api/student/photos/<id>/`, `works.photos.may_remove`), где
        # спрашивается ещё и открыто ли окно: снять присланное после
        # закрытия — это правка сданной работы, а не передумал.
        #
        # Две двери здесь не дублирование, а разные вопросы: тут «чей это
        # урок», там «ваше ли это и не поздно ли».
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


def writable_works(user):
    """Работы, к которым этот человек может приложить условия и картинки."""
    from schedule.models import Course
    from works.models import Work

    if user is None or not user.is_authenticated:
        return Work.objects.none()

    return Work.objects.filter(course__in=Course.objects.writable_by(user))


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
