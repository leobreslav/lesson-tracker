"""
Приём в школу и зачисление на курсы.

**Приглашение заводит учётку сразу.** Раньше оно было записанным адресом,
который ждал первого входа, — и всё, что администратор хотел сделать с
человеком до его появления, приходилось выражать в самом приглашении:
курсы ученика оно уже носило, за курсами учителя пришлось бы носить и
роли, и замены, и всё остальное. Это второй вид личности, протянутый через
весь домен, — ровно то, от чего проект уходил, когда план был личным.

Поэтому теперь «пригласить» значит «завести человека»: строка `User`
появляется в момент ввода адреса, со школой, видом и ролью, и с этой
минуты её можно назначать, зачислять и ставить методистом обычными
таблицами. Пароля у неё нет, войти в неё нельзя ничем, кроме Google с
**этим** адресом: замок остался тот же — `SocialAccountAdapter` пускает
только адреса, подтверждённые провайдером.

Само приглашение остаётся билетом и следом в истории: кто кого позвал,
когда и забрал ли человек учётку (`accepted_at`).

Проверено разведкой на живом allauth: заготовку подхватывает вход и при
отсутствии `EmailAddress`, и при неподтверждённой записи — учётка остаётся
одна, школа цела. Поэтому подтверждённую запись адреса мы себе **не
выписываем**: это было бы наше утверждение о проверке, которой не было.
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
        .order_by("created_at")
        .first()
    )


def provision(school, email: str, *, kind: str, name: str = "", is_admin: bool = False):
    """
    Завести человека, которого ещё не было.

    Учётка полноценная с первой минуты: её видно в списках, ей можно
    поручить курс, записать на курс и назначить методистом — то есть
    подготовить всё до того, как человек впервые войдёт.

    Пароля нет и быть не может: `set_unusable_password` плюс отсутствие
    формы входа по паролю в интерфейсе. Единственная дверь — Google с этим
    же адресом, и открывает её `SocialAccountAdapter`, который принимает
    только подтверждённые провайдером адреса. Заготовку заберёт тот, кто
    действительно владеет почтой, и никто другой.

    **`EmailAddress` мы не заводим.** Менеджер (`UserManager._create_user`)
    делает такую запись подтверждённой, и оправдано это тем, что учётки из
    командной строки вписывает человек с доступом к шеллу. Здесь адрес
    вводит администратор в веб-форму, и подтверждать его нам нечем; вход
    от этого не страдает — проверено.

    Имя из ввода кладётся ярлыком в `first_name` целиком, а не разбирается
    на имя и фамилию: порядок этой пары не определён ни в русском списке,
    ни в английском. При первом входе Google его перезаписывает — см.
    `accept`.
    """
    user = User(
        email=email.strip().lower(),
        school=school,
        kind=kind,
        is_school_admin=is_admin,
        first_name=(name or "")[:150],
    )
    user.set_unusable_password()
    user.save()
    return user


@transaction.atomic
def accept(user, invitation, names=None) -> bool:
    """
    Отметить, что человек забрал свою учётку.

    Раньше здесь делалась вся работа: приём в школу, вид, роль и курсы из
    приглашения. Теперь всё это уже сделано — приглашение завело учётку в
    момент ввода адреса, — и на первый вход остаётся пометка и имя.

    Учётку, которая уже в **другой** школе, приглашение не трогает: второе
    приглашение не должно молча переносить учителя со всем расписанием в
    чужое здание. Это тот же запрет, что стоял тут всегда, только теперь
    он сравнивает школы, а не проверяет, есть ли школа вообще.

    Человека, у которого школы нет вовсе (вошёл сам, приглашения ему не
    писали, а потом написали), приглашение принимает: это и есть случай
    «администратор вписал адрес после того, как человек уже пытался войти».

    `names` — то, что отдал Google. Имя перезаписывается **только здесь**,
    в момент забирания: до него в полях лежит ярлык, которым администратор
    назвал человека при вводе, и настоящее имя должно его вытеснить.
    Обычный сигнал этого сделать не может — он дополняет только пустые
    поля, — а порядок сигналов нам не подвластен, поэтому решение принято
    там, где точно известно, что вход первый.
    """
    if user.school_id is not None and user.school_id != invitation.school_id:
        return False

    changed = []
    if user.school_id is None:
        user.school = invitation.school
        user.kind = invitation.kind
        user.is_school_admin = invitation.is_school_admin
        changed += ["school", "kind", "is_school_admin"]

    for field, value in (names or {}).items():
        if value:
            setattr(user, field, value[:150])
            changed.append(field)

    if changed:
        user.save(update_fields=changed)

    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    return True


def accept_for(user, verified_emails, names=None) -> bool:
    """
    Try every address the provider vouched for.

    The addresses come from the provider, never from a form: matching what a
    person typed about themselves would let anyone claim a colleague's
    invitation by writing their address in a profile field.
    """
    for email in verified_emails:
        invitation = pending_for(email)
        if invitation is not None and accept(user, invitation, names):
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


def check_address(email: str, kind: str) -> None:
    """`address_problem` для тех, кому нужен отказ, а не ответ."""
    problem = address_problem(email, kind)
    if problem is not None:
        code, detail = problem
        api_error(code, detail, field="email", email=email)
