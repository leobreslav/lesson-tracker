"""
Состав курса, вставленный списком.

Администратор копирует класс из таблицы или письма и вставляет его целиком.
Разбор устроен по тем же правилам, что разбор учебного плана: **вместо
угадывания — отказ**. Строка, которую не удалось прочитать, называет свой
номер и не даёт применить вставку; иначе единственным следом непонятой
строки был бы отсутствующий ученик, которого никто не хватится до первой
контрольной.

Три формата, потому что именно так люди и приносят списки:

    ivanov@school.ru
    Иванов Пётр, ivanov@school.ru
    Иванов<TAB>Пётр<TAB>ivanov@school.ru

Правило одно на все три: **ровно один столбец с собакой — это адрес,
остальные вместе — имя**. Ни порядок столбцов, ни их число заранее не
заданы: в выгрузке из журнала адрес бывает и первым, и последним.

Имя — ярлык для администратора, а не имя учётки: в учётку оно приезжает из
Google при первом входе, и разбирать «Иванов Пётр» на имя и фамилию мы не
беремся — порядок у этой пары не определён ни в русском списке, ни в
английском.
"""

from dataclasses import dataclass, field

from accounts.models import Kind
from config.errors import Codes
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models.functions import Lower

from . import services
from .models import Invitation

User = get_user_model()

# сколько столбцов имени терпим: «Фамилия Имя Отчество» тремя ячейками —
# обычная выгрузка, а четвёртый столбец это уже класс, телефон или оценка,
# и молча склеивать их в имя нельзя
MAX_COLUMNS = 4

# что вставили: одна строка, не более
MAX_ROWS = 500


@dataclass
class Person:
    """Одна разобранная строка вставки."""

    line: int
    email: str
    name: str = ""


@dataclass
class Parsed:
    people: list[Person] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    rows: int = 0
    duplicates: int = 0


def problem(code: str, detail: str, **params) -> dict:
    """Ошибка разбора в том же виде, в каком их отдаёт импорт плана."""
    return {"code": code, "detail": detail, "params": params}


def parse_roster(text: str) -> Parsed:
    """
    Текст → люди и ошибки. Ничего не спрашивает у базы.

    Пустые строки пропускаются молча: их даёт любая вставка из таблицы.
    Повторённый адрес схлопывается — список класса, скопированный дважды,
    это не ошибка, а лишнее движение мышью.
    """
    result = Parsed()
    seen: set[str] = set()

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or not line.strip("\t,; "):
            continue

        result.rows += 1
        if result.rows > MAX_ROWS:
            result.errors.append(
                problem(
                    Codes.ROSTER_TOO_MANY_ROWS,
                    f"Not more than {MAX_ROWS} lines at a time.",
                    limit=MAX_ROWS,
                )
            )
            break

        person = read_line(number, line, result.errors)
        if person is None:
            continue

        if person.email in seen:
            result.duplicates += 1
            continue

        seen.add(person.email)
        result.people.append(person)

    return result


def read_line(number: int, line: str, errors: list[dict]) -> Person | None:
    """Одна строка: адрес и, может быть, имя. Или запись в список ошибок."""
    parts = [part.strip() for part in split_columns(line)]
    parts = [part for part in parts if part]

    if len(parts) > MAX_COLUMNS:
        errors.append(
            problem(
                Codes.ROSTER_TOO_MANY_COLUMNS,
                f"Line {number}: {len(parts)} columns, and no more than "
                f"{MAX_COLUMNS} are expected — a name and an address.",
                line=number,
                columns=len(parts),
            )
        )
        return None

    addresses = [part for part in parts if "@" in part]

    if not addresses:
        errors.append(
            problem(
                Codes.ROSTER_NO_EMAIL,
                f"Line {number}: no email address.",
                line=number,
                text=line,
            )
        )
        return None

    if len(addresses) > 1:
        errors.append(
            problem(
                Codes.ROSTER_TWO_EMAILS,
                f"Line {number}: two addresses in one line.",
                line=number,
                text=line,
            )
        )
        return None

    email = addresses[0].strip("<>").lower()
    try:
        validate_email(email)
    except ValidationError:
        errors.append(
            problem(
                Codes.ROSTER_BAD_EMAIL,
                f"Line {number}: «{email}» is not an email address.",
                line=number,
                email=email,
            )
        )
        return None

    name = " ".join(part for part in parts if part not in addresses)
    return Person(line=number, email=email, name=" ".join(name.split()))


def split_columns(line: str) -> list[str]:
    """
    Чем разделены столбцы — решает сама строка.

    Табуляция сильнее запятой: из таблицы приезжает именно она, а запятая
    в такой строке бывает частью имени («Иванов, Пётр» одной ячейкой).
    Точка с запятой — то же самое для тех, у кого системный разделитель
    списка такой.

    Разделителя нет вовсе — режем по пробелам: так приезжает почтовая
    строка «Пётр <petrov@school.ru>», и так же видно, что в строке два
    адреса, а не один странный.
    """
    for separator in ("\t", ";", ","):
        if separator in line:
            return line.split(separator)

    return line.split()


# --- что с этим сделает база ----------------------------------------------------

# что будет с человеком: одно из пяти
ENROL = "enrol"  # учётка есть — запишем
RESTORE = "restore"  # снят с курса — вернём той же строкой
ALREADY = "already"  # уже учится — ничего не делаем
NEW = "new"  # человека ещё нет — заведём и запишем
BLOCKED = "blocked"  # адрес занят: чужая школа или учительская учётка


@dataclass
class Decision:
    person: Person
    action: str
    code: str = ""
    detail: str = ""
    account: object = None  # учётка, если она уже есть

    @property
    def who(self) -> str:
        """Как человек зовётся в базе — или как его назвали при вводе."""
        if self.account is not None:
            return full_name(self.account)
        return self.person.name


def plan_roster(people: list[Person], course) -> list[Decision]:
    """
    Что произойдёт с каждым адресом — без единой записи.

    Тем же расчётом пользуются предпросмотр и сама вставка, поэтому
    показанное и полученное разойтись не могут. Все выборки сделаны разом:
    список класса — это тридцать адресов, и тридцати запросов на них быть
    не должно.
    """
    school = course.school
    emails = [person.email for person in people]

    # адреса из вставки приведены к нижнему регистру, а в базе адрес мог
    # завестись как угодно: сравниваем приведёнными с обеих сторон
    accounts = {
        user.email.lower(): user
        for user in User.objects.annotate(key=Lower("email")).filter(key__in=emails)
    }
    enrolled = {
        row.student.email.lower(): row
        for row in course.students.select_related("student")
        .annotate(key=Lower("student__email"))
        .filter(key__in=emails)
    }
    invited = {
        invitation.email.lower(): invitation
        for invitation in Invitation.objects.annotate(key=Lower("email")).filter(
            school=school, key__in=emails, accepted_at__isnull=True
        )
    }

    decisions = []
    for person in people:
        account = accounts.get(person.email)
        row = enrolled.get(person.email)

        if row is not None and row.removed_at is None:
            decisions.append(Decision(person, ALREADY, account=account))
            continue

        trouble = services.member_problem(account, Kind.STUDENT, school)
        if trouble is not None:
            code, detail = trouble
            decisions.append(
                Decision(person, BLOCKED, code=code, detail=detail, account=account)
            )
            continue

        if row is not None:
            decisions.append(Decision(person, RESTORE, account=account))
        elif account is not None and account.school_id == school.pk:
            decisions.append(Decision(person, ENROL, account=account))
        else:
            # учётки нет вовсе, либо она есть, но ни в какой школе: и в том и
            # в другом случае записать некого — ждём первого входа
            waiting = invited.get(person.email)
            if not person.name and waiting is not None:
                person.name = waiting.name
            decisions.append(Decision(person, NEW, account=account))

    return decisions


def full_name(user) -> str:
    return " ".join(filter(None, (user.first_name, user.last_name))) or user.email


def counts(decisions: list[Decision]) -> dict:
    """Числа предпросмотра — по одному на каждый исход."""
    return {
        action: sum(1 for item in decisions if item.action == action)
        for action in (ENROL, RESTORE, ALREADY, NEW, BLOCKED)
    }


def payload(parsed: Parsed, decisions: list[Decision]) -> dict:
    """
    Ответ обоих эндпоинтов — предпросмотра и самой вставки.

    Он один на двоих намеренно: числа, которые обещали, и числа, которые
    получились, должны быть одной и той же формы, иначе сравнивать их
    придётся глазами.
    """
    return {
        "rows": parsed.rows,
        "duplicates": parsed.duplicates,
        **counts(decisions),
        "people": [
            {
                "line": item.person.line,
                "email": item.person.email,
                "name": item.who,
                "action": item.action,
                "code": item.code,
                "detail": item.detail,
            }
            for item in decisions
        ],
        "errors": parsed.errors,
    }


@transaction.atomic
def apply_roster(decisions: list[Decision], course, *, by) -> dict:
    """
    Записать то, что показал предпросмотр. Одной транзакцией.

    Занятый адрес вставку **не отменяет**: про него сказано и в
    предпросмотре, и в ответе поимённо, а остальные двадцать девять человек
    ни в чём не виноваты. Отказ целиком остаётся за ошибками разбора — там
    непонятно, что имел в виду администратор, а здесь понятно совершенно.
    """
    for item in decisions:
        if item.action == NEW:
            item.account = welcome(item.person, course, by=by)
        if item.action in (ENROL, RESTORE, NEW):
            services.enrol(item.account, course, by=by)

    return counts(decisions)


def welcome(person: Person, course, *, by):
    """
    Завести человека, которого ещё нет, и выписать ему приглашение.

    Раньше здесь писался только адрес, а зачисление ждало первого входа —
    и «пригласим» было отдельным исходом вставки, отличным от «зачислим».
    Теперь учётка появляется сразу, зачисление обычное, и различать эти два
    случая на экране незачем: с точки зрения администратора он в обоих
    записал человека на курс.

    Приглашение при этом остаётся: оно билет и след в истории — кто кого
    позвал и забрал ли тот свою учётку.
    """
    Invitation.objects.get_or_create(
        school=course.school,
        email=person.email,
        defaults={
            "kind": Kind.STUDENT,
            "name": person.name,
            "created_by": by,
        },
    )

    return services.provision(
        course.school, person.email, kind=Kind.STUDENT, name=person.name
    )
