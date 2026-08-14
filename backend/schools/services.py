"""
Joining a school, and being enrolled into its courses.

The only way in is an invitation an administrator wrote down in advance,
matched against the address the provider itself verified.

**Приглашение расходуется однажды.** Оно отвечает на вопрос «кто этот
человек и куда его записать», и отвечает при первом появлении. Дальше
состав курса — прямое действие: если бы приглашение доносило курсы при
каждом входе, снятый с курса ученик возвращался бы туда сам, стоило ему
войти. Отсюда правило вставки: **есть учётка — зачисляем немедленно, нет —
записываем в приглашение и ждём**.
"""

from accounts.models import Kind
from config.errors import Codes, api_error
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import Invitation

User = get_user_model()


def pending_for(email: str):
    """
    The unused invitation for this address, if there is one.

    Addresses are compared case-insensitively: an administrator types
    «Ivan.Petrov@school.ru», Google reports «ivan.petrov@school.ru», and the
    same person should walk in either way.
    """
    if not email:
        return None

    return (
        Invitation.objects.filter(email__iexact=email.strip(), accepted_at__isnull=True)
        .select_related("school")
        .prefetch_related("courses")
        .order_by("created_at")
        .first()
    )


@transaction.atomic
def accept(user, invitation) -> bool:
    """
    Attach the user to the school and stamp the invitation.

    Someone who already belongs to a school is left alone: a second
    invitation must not silently move a teacher, with their whole schedule,
    into another building.

    Вид пользователя проставляется здесь и только здесь: адрес становится
    учительским или ученическим в момент, когда за него поручились
    приглашением, и больше не меняется.
    """
    if user.school_id is not None:
        return False

    user.school = invitation.school
    user.kind = invitation.kind
    user.is_school_admin = invitation.is_school_admin
    user.save(update_fields=["school", "kind", "is_school_admin"])

    if invitation.kind == Kind.STUDENT:
        enrol_all(user, invitation.courses.all(), by=invitation.created_by)

    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    return True


def accept_for(user, verified_emails) -> bool:
    """
    Try every address the provider vouched for.

    The addresses come from the provider, never from a form: matching what a
    person typed about themselves would let anyone claim a colleague's
    invitation by writing their address in a profile field.
    """
    for email in verified_emails:
        invitation = pending_for(email)
        if invitation is not None and accept(user, invitation):
            return True
    return False


# --- зачисление на курс ---------------------------------------------------------


def enrol(student, course, *, by=None):
    """
    Записать ученика на курс — или вернуть снятого.

    Строка на пару одна и та же навсегда: возврат снимает `removed_at`, а не
    заводит вторую. Иначе «сколько раз его записывали» стало бы вопросом, на
    который никто не хотел отвечать.
    """
    from schedule.models import CourseStudent

    row, created = CourseStudent.objects.get_or_create(
        course=course, student=student, defaults={"added_by": by}
    )
    if not created and row.removed_at is not None:
        row.removed_at = None
        row.save(update_fields=["removed_at"])

    return row


def enrol_all(student, courses, *, by=None) -> int:
    return sum(1 for course in courses if enrol(student, course, by=by))


def remove_from_course(row) -> None:
    """
    Снять с курса, не удаляя строку.

    Строка — это право видеть сделанное: ответы и результаты остаются, и
    ученик продолжает их читать. Работать в курсе он перестаёт.
    """
    if row.removed_at is None:
        row.removed_at = timezone.now()
        row.save(update_fields=["removed_at"])


# --- кому можно писать приглашение ----------------------------------------------


def check_address(email: str, kind: str) -> None:
    """
    Годится ли адрес для приглашения такого вида. Молчит или отказывает.

    Проверка ровно одна: **один адрес — один вид учётки**. Учитель и ученик
    на одной почте невозможны, и сказать об этом надо на вводе, а не молчать
    при входе: приглашение, которое никогда не сработает, хуже отказа, потому
    что администратор считает, что пригласил.

    «Уже состоит в школе» проверяет вызывающий код своим кодом
    (`already_member`) — это другой вопрос и другой ответ, и он же закрывает
    ученика в двух школах: `User.school` один, и второе приглашение его не
    перенесёт.
    """
    person = User.objects.filter(email__iexact=email).first()
    if person is None or person.school_id is None:
        return

    if person.kind != kind:
        api_error(
            Codes.EMAIL_OTHER_KIND,
            f"«{email}» is already used by a "
            f"{'student' if person.is_student else 'teacher'}; one address is "
            "one kind of account.",
            field="email",
            email=email,
            kind=person.kind,
        )
