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
from django.db.models.functions import Lower
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


def member_problem(person, kind: str, school=None):
    """
    То же, что `address_problem`, но учётку приносит вызывающий.

    Массовый ввод спрашивает про тридцать адресов разом и уже держит их
    учётки в памяти: тридцать одинаковых запросов ради одного и того же
    правила — не то, ради чего правило собрано в одном месте.
    """
    if person is None or person.school_id is None:
        return None

    if person.kind != kind:
        return (
            Codes.EMAIL_OTHER_KIND,
            f"«{person.email}» is already used by a "
            f"{'student' if person.is_student else 'teacher'}; one address is "
            "one kind of account.",
        )

    if school is None or person.school_id != school.pk:
        return (
            Codes.ALREADY_MEMBER,
            f"«{person.email}» already belongs to a school.",
        )

    return None


def address_problem(email: str, kind: str, school=None):
    """
    Что не так с адресом — или `None`, если всё в порядке.

    Два правила, и оба про уже существующие учётки. **Один адрес — один вид
    учётки**: учитель и ученик на одной почте невозможны. И **один человек —
    одна школа**: `User.school` единственный, второе приглашение его не
    перенесёт.

    `school` разделяет два вопроса, которые задают разные места. Без неё
    вопрос «кого можно пригласить»: человек, уже состоящий в школе — хоть бы
    и в этой, — приглашения не ждёт, он уже вошёл. Со школой вопрос «кого
    можно записать на курс»: ученик **этой** школы как раз и есть тот, кого
    записывают, а всё остальное — отказ.

    Отвечать надо на вводе, а не молчать при входе: приглашение, которое
    никогда не сработает, хуже отказа, потому что администратор считает,
    что пригласил.
    """
    return member_problem(
        User.objects.filter(email__iexact=email).first(), kind, school
    )


def conflicting_addresses(invitations) -> dict:
    """
    Приглашения, которые уже никогда не сработают: адрес → код причины.

    Проверка на вводе закрывает всё, кроме одного случая: два приглашения в
    разные школы, написанные до того, как человек впервые вошёл. Побеждает
    первый вход, второе приглашение висит вечно — и молча. Поэтому оно
    помечается на чтении, тем же правилом и в один запрос.
    """
    rows = list(invitations)
    people = {
        user.email.lower(): user
        for user in User.objects.annotate(key=Lower("email")).filter(
            key__in=[row.email.lower() for row in rows]
        )
    }

    marks = {}
    for row in rows:
        if row.accepted_at is not None:
            continue
        problem = member_problem(people.get(row.email.lower()), row.kind)
        if problem is not None:
            marks[row.email] = problem[0]

    return marks


def check_address(email: str, kind: str) -> None:
    """`address_problem` для тех, кому нужен отказ, а не ответ."""
    problem = address_problem(email, kind)
    if problem is not None:
        code, detail = problem
        api_error(code, detail, field="email", email=email)
