"""
Выгрузка ManageBac по курсу: ученики вместе с родителями.

ManageBac отдаёт по каждой группе xlsx одного вида: две строки шапки — школа
и название группы, — строка с полосами «Students Information» и «Parents
Information», строка заголовков и дальше по ученику на строку. У ученика
одиннадцать столбцов, у каждого из трёх родителей по четыре, и родители идут
**той же строкой**, что ребёнок. Файл этот и есть связь «родитель — ребёнок»,
записанная школой, и подтверждать её никому не нужно.

Читаем шесть вещей: имя, фамилию и адрес ученика, то же по каждому родителю,
и Student ID как ключ сопоставления. Телефон, пол, дату рождения и National ID
**не читаем вовсе** — они проекту не нужны ни для чего, и в предпросмотр не
попадают. Соблазн «сохраним, пригодится» появится в первую же неделю; правило
области говорит, что нет.

Столбцы ищутся **по заголовкам**, а не по позициям: шапка не в первой строке,
а число родительских слотов сегодня три и завтра может быть другим.

Правила те же, что у вставки состава (`roster.py`): вместо угадывания — отказ,
строка называет свой номер. Отличие одно, и оно намеренное: **беда с
родителем не блокирует ученика.** Родитель без адреса, с адресом ученика или с
адресом учителя — это предупреждение и пропуск родителя, а ребёнок
зачисляется. Отказывать всей строке из-за папы-учителя значило бы держать
ребёнка вне курса до решения вопроса, к нему не относящегося.
"""

import re
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
from .roster import (
    ALREADY,
    BLOCKED,
    ENROL,
    MAX_ROWS,
    NEW,
    RESTORE,
    full_name,
    problem,
)

User = get_user_model()

# файл по группе весит десятки килобайт; мегабайт — это уже не он
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

# полосы над заголовками — не название группы, а разметка таблицы
BANDS = ("students information", "parents information")


def key(text: str) -> str:
    """Заголовок к виду, не зависящему от регистра, пробелов и дефисов."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


STUDENT_COLUMNS = {
    "studentid": "external_id",
    "firstname": "first",
    "lastname": "last",
    "emailaddress": "email",
}
PARENT_COLUMN = re.compile(r"^parent(\d+)(firstname|lastname|emailaddress)$")
PARENT_FIELDS = {"firstname": "first", "lastname": "last", "emailaddress": "email"}


@dataclass
class Adult:
    """Один родитель из строки ученика."""

    slot: int
    email: str = ""
    first: str = ""
    last: str = ""

    @property
    def name(self) -> str:
        return " ".join(filter(None, (self.first, self.last)))


@dataclass
class Pupil:
    """Одна строка выгрузки: ученик и его взрослые."""

    line: int
    email: str
    first: str = ""
    last: str = ""
    external_id: str = ""
    parents: list[Adult] = field(default_factory=list)

    @property
    def name(self) -> str:
        return " ".join(filter(None, (self.first, self.last)))


@dataclass
class Parsed:
    group: str = ""
    pupils: list[Pupil] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    rows: int = 0
    duplicates: int = 0


# --- чтение ------------------------------------------------------------------


class UnreadableFile(Exception):
    """Не книга xlsx. Текст — для человека, код подставит вьюха."""


def read_rows(data: bytes, *, filename: str = "") -> list[list[str]]:
    """Байты → строки ячеек первого листа. Чтение общее с импортом плана."""
    from plans import xlsx
    from plans.services import PlanImportError

    try:
        return xlsx.read_plan_xlsx(data, filename=filename).rows
    except PlanImportError as error:
        raise UnreadableFile(str(error)) from error


def find_header(rows: list[list[str]]):
    """
    Строка заголовков и раскладка столбцов.

    Заголовком считается первая строка, где есть «E-mail Address» ученика —
    это единственный столбец, без которого файл бесполезен. Возвращает номер
    строки (с единицы), столбцы ученика и столбцы родителей по слотам.
    """
    for index, row in enumerate(rows):
        keys = [key(cell) for cell in row]
        if "emailaddress" not in keys:
            continue

        student = {}
        parents: dict[int, dict] = {}
        for column, name in enumerate(keys):
            if name in STUDENT_COLUMNS:
                student.setdefault(STUDENT_COLUMNS[name], column)
                continue
            match = PARENT_COLUMN.match(name)
            if match:
                slot = int(match.group(1))
                parents.setdefault(slot, {})[PARENT_FIELDS[match.group(2)]] = column

        return index + 1, student, dict(sorted(parents.items()))

    return None, {}, {}


def group_name(rows: list[list[str]], header_line: int) -> str:
    """
    Как ManageBac назвал группу: последняя содержательная строка над шапкой.

    Первая строка — школа, вторая — группа, третья пустая, четвёртая — полосы
    «Students Information / Parents Information». Полосы — разметка, а не
    название, поэтому отбрасываются; из оставшегося берётся последнее.
    """
    names = []
    for row in rows[: header_line - 1]:
        cells = [cell.strip() for cell in row if cell and cell.strip()]
        if not cells:
            continue
        if all(cell.lower() in BANDS for cell in cells):
            continue
        names.append(cells[0])

    return names[-1] if names else ""


def cell(row: list[str], column: int | None) -> str:
    if column is None or column >= len(row) or row[column] is None:
        return ""
    # из книги ячейки приходят строками (`cell_text`), а из тестов и вставки
    # могут прийти числами — номер ученика и есть число
    return " ".join(str(row[column]).split())


def clean_email(raw: str) -> str:
    return raw.strip().strip("<>").lower()


def parse_rows(rows: list[list[str]]) -> Parsed:
    """
    Строки ячеек → ученики с родителями, ошибки и предупреждения.

    Ошибка — то, из-за чего файл нельзя применить: нет шапки, у ученика нет
    адреса или он не читается. Предупреждение — то, что применить можно, но
    не целиком: родитель без адреса или с адресом, который родительским быть
    не может. Ученик при предупреждении зачисляется, родитель пропускается.
    """
    result = Parsed()
    header_line, student, parents = find_header(rows)

    if header_line is None or "email" not in student:
        result.errors.append(
            problem(
                Codes.ROSTER_HEADER_MISSING,
                "The header row with «E-mail Address» was not found — "
                "a ManageBac class export is expected.",
            )
        )
        return result

    result.group = group_name(rows, header_line)
    seen: set[str] = set()

    for offset, row in enumerate(rows[header_line:], start=header_line + 1):
        if not any(cell(row, column) for column in range(len(row))):
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

        pupil = read_pupil(offset, row, student, result.errors)
        if pupil is None:
            continue

        if pupil.email in seen:
            result.duplicates += 1
            continue
        seen.add(pupil.email)

        pupil.parents = read_parents(offset, row, parents, pupil, result.warnings)
        result.pupils.append(pupil)

    return result


def read_pupil(line: int, row: list[str], columns: dict, errors: list[dict]):
    email = clean_email(cell(row, columns.get("email")))
    first = cell(row, columns.get("first"))
    last = cell(row, columns.get("last"))

    if not email:
        errors.append(
            problem(
                Codes.ROSTER_NO_EMAIL,
                f"Line {line}: no email address.",
                line=line,
                text=" ".join(filter(None, (first, last))),
            )
        )
        return None

    try:
        validate_email(email)
    except ValidationError:
        errors.append(
            problem(
                Codes.ROSTER_BAD_EMAIL,
                f"Line {line}: «{email}» is not an email address.",
                line=line,
                email=email,
            )
        )
        return None

    return Pupil(
        line=line,
        email=email,
        first=first,
        last=last,
        external_id=cell(row, columns.get("external_id"))[:64],
    )


def read_parents(line, row, slots: dict, pupil: Pupil, warnings: list[dict]):
    """
    Взрослые из той же строки. Пустой слот — обычное дело, а не ошибка.

    Один и тот же адрес в двух слотах схлопывается молча: так бывает, когда
    школа записала одного человека дважды.
    """
    adults = []
    seen: set[str] = set()

    for slot, columns in slots.items():
        adult = Adult(
            slot=slot,
            email=clean_email(cell(row, columns.get("email"))),
            first=cell(row, columns.get("first")),
            last=cell(row, columns.get("last")),
        )
        if not adult.email and not adult.first and not adult.last:
            continue

        if not adult.email:
            warnings.append(
                problem(
                    Codes.ROSTER_PARENT_NO_EMAIL,
                    f"Line {line}: parent «{adult.name}» has no email address "
                    "and is skipped.",
                    line=line,
                    name=adult.name,
                )
            )
            continue

        try:
            validate_email(adult.email)
        except ValidationError:
            warnings.append(
                problem(
                    Codes.ROSTER_PARENT_BAD_EMAIL,
                    f"Line {line}: «{adult.email}» is not an email address; "
                    "the parent is skipped.",
                    line=line,
                    email=adult.email,
                )
            )
            continue

        if adult.email == pupil.email:
            warnings.append(
                problem(
                    Codes.ROSTER_PARENT_IS_STUDENT,
                    f"Line {line}: the parent's address «{adult.email}» is the "
                    "student's own; the parent is skipped.",
                    line=line,
                    email=adult.email,
                )
            )
            continue

        if adult.email in seen:
            continue
        seen.add(adult.email)
        adults.append(adult)

    return adults


def parse_workbook(data: bytes, *, filename: str = "") -> Parsed:
    """Файл целиком: нечитаемая книга — одна ошибка в списке, как у плана."""
    try:
        rows = read_rows(data, filename=filename)
    except UnreadableFile as error:
        result = Parsed()
        result.errors.append(problem(Codes.FILE_NOT_XLSX, str(error)))
        return result

    return parse_rows(rows)


# --- что с этим сделает база ------------------------------------------------------

# исходы родителя: заведём и свяжем, свяжем с уже заведённым, уже связан,
# адрес занят не родителем, ребёнок не зачисляется — и связывать не с кем
PARENT_NEW = "new"
PARENT_LINK = "link"
PARENT_LINKED = "linked"
PARENT_BLOCKED = "blocked"
PARENT_SKIPPED = "skipped"


@dataclass
class ParentDecision:
    adult: Adult
    action: str
    code: str = ""
    detail: str = ""
    account: object = None

    @property
    def who(self) -> str:
        if self.account is not None:
            return full_name(self.account)
        return self.adult.name


@dataclass
class PupilDecision:
    pupil: Pupil
    action: str
    code: str = ""
    detail: str = ""
    account: object = None
    # адрес учётки до импорта, если номер тот же, а адрес другой
    previous_email: str = ""
    parents: list[ParentDecision] = field(default_factory=list)

    @property
    def who(self) -> str:
        if self.account is not None and self.account.last_login is not None:
            return full_name(self.account)
        return self.pupil.name or (
            full_name(self.account) if self.account is not None else ""
        )


@dataclass
class Plan:
    pupils: list[PupilDecision] = field(default_factory=list)
    # действующие зачисления, которых в файле нет
    leaving: list = field(default_factory=list)


def match_pupil(pupil: Pupil, by_email: dict, by_id: dict, school):
    """
    Кто это в базе — по номеру, потом по адресу.

    | нашли                                | что это                         |
    |--------------------------------------|---------------------------------|
    | номер и адрес указывают на одного    | тот же человек                  |
    | номер нашёлся, адрес — нет           | тот же человек, адрес изменился |
    | адрес нашёлся, номера у него нет     | тот же человек, номер запишем   |
    | адрес нашёлся с **другим** номером   | конфликт: два номера на адрес   |
    | номер и адрес — два разных человека  | конфликт: источник ошибся       |
    | ничего                               | новый человек                   |

    Номер — школьный, поэтому ищется только среди своей школы; чужая школа с
    тем же номером — совпадение, а не тот же ученик.
    """
    by_number = by_id.get(pupil.external_id) if pupil.external_id else None
    by_address = by_email.get(pupil.email)

    if by_number is not None and by_address is not None and by_number != by_address:
        return None, (
            Codes.ROSTER_ID_CONFLICT,
            f"Student ID {pupil.external_id} belongs to «{by_number.email}», "
            f"while «{pupil.email}» is another account.",
        )

    if by_number is not None:
        return by_number, None

    if (
        by_address is not None
        and pupil.external_id
        and by_address.external_id
        and by_address.external_id != pupil.external_id
        and by_address.school_id == school.pk
    ):
        return None, (
            Codes.ROSTER_ID_CONFLICT,
            f"«{pupil.email}» is recorded with Student ID "
            f"{by_address.external_id}, and the file says {pupil.external_id}.",
        )

    return by_address, None


def plan_import(parsed: Parsed, course) -> Plan:
    """
    Что произойдёт с каждой строкой — без единой записи.

    Тем же расчётом пользуются предпросмотр и само применение, поэтому
    показанное и полученное разойтись не могут. Выборки сделаны разом — на
    класс из тридцати строк с шестьюдесятью родителями запросов не сто.
    """
    from families.models import Guardianship

    school = course.school
    emails = {pupil.email for pupil in parsed.pupils}
    for pupil in parsed.pupils:
        emails.update(adult.email for adult in pupil.parents)
    numbers = {pupil.external_id for pupil in parsed.pupils if pupil.external_id}

    by_email = {
        user.email.lower(): user
        for user in User.objects.annotate(key=Lower("email")).filter(key__in=emails)
    }
    by_id = {
        user.external_id: user
        for user in User.objects.filter(school=school, external_id__in=numbers)
    }
    enrolled = {
        row.student_id: row
        for row in course.students.select_related("student")
    }
    invited = {
        invitation.email.lower(): invitation
        for invitation in Invitation.objects.annotate(key=Lower("email")).filter(
            school=school, key__in=emails, accepted_at__isnull=True
        )
    }
    known_ids = {
        user.pk for user in list(by_email.values()) + list(by_id.values())
    }
    links = set(
        Guardianship.objects.filter(
            parent_id__in=known_ids, child_id__in=known_ids
        ).values_list("parent_id", "child_id")
    )

    plan = Plan()
    # кого файл упоминает хоть как-то — по адресу или по номеру. Снимать с
    # курса можно только тех, о ком файл молчит: строка с конфликтом номера
    # называет двоих, и ни одного из них снимать по ней нельзя
    mentioned = {user.pk for user in by_email.values()}
    mentioned.update(user.pk for user in by_id.values())
    # родитель у братьев и сестёр стоит в двух строках: заводится он по
    # первой, а по второй — только связывается
    fresh: set[str] = set()

    for pupil in parsed.pupils:
        account, conflict = match_pupil(pupil, by_email, by_id, school)
        decision = PupilDecision(pupil, NEW, account=account)

        if conflict is not None:
            decision.action = BLOCKED
            decision.code, decision.detail = conflict
        else:
            trouble = services.member_problem(account, Kind.STUDENT, school)
            row = enrolled.get(account.pk) if account is not None else None
            if trouble is not None:
                decision.action = BLOCKED
                decision.code, decision.detail = trouble
            elif row is not None and row.removed_at is None:
                decision.action = ALREADY
            elif row is not None:
                decision.action = RESTORE
            elif account is not None and account.school_id == school.pk:
                decision.action = ENROL
            else:
                waiting = invited.get(pupil.email)
                if not pupil.name and waiting is not None:
                    pupil.first = waiting.name

        if account is not None and decision.action != BLOCKED:
            if account.email.lower() != pupil.email:
                decision.previous_email = account.email

        for adult in pupil.parents:
            item = plan_parent(adult, decision, by_email, links, school)
            if item.action == PARENT_NEW:
                if adult.email in fresh:
                    item.action = PARENT_LINK
                fresh.add(adult.email)
            decision.parents.append(item)
        plan.pupils.append(decision)

    plan.leaving = [
        row
        for row in enrolled.values()
        if row.removed_at is None and row.student_id not in mentioned
    ]

    return plan


def plan_parent(adult: Adult, child: PupilDecision, by_email, links, school):
    """Родитель сопоставляется только по адресу: номера у него в файле нет."""
    if child.action == BLOCKED:
        return ParentDecision(adult, PARENT_SKIPPED)

    account = by_email.get(adult.email)
    trouble = services.member_problem(account, Kind.PARENT, school)
    if trouble is not None:
        code, detail = trouble
        return ParentDecision(adult, PARENT_BLOCKED, code=code, detail=detail, account=account)

    if account is None or account.school_id != school.pk:
        return ParentDecision(adult, PARENT_NEW, account=account)

    if child.account is not None and (account.pk, child.account.pk) in links:
        return ParentDecision(adult, PARENT_LINKED, account=account)

    return ParentDecision(adult, PARENT_LINK, account=account)


def counts(plan: Plan) -> dict:
    parents = [item for decision in plan.pupils for item in decision.parents]
    return {
        **{
            action: sum(1 for item in plan.pupils if item.action == action)
            for action in (ENROL, RESTORE, ALREADY, NEW, BLOCKED)
        },
        "renamed": sum(1 for item in plan.pupils if item.previous_email),
        "parents": {
            action: sum(1 for item in parents if item.action == action)
            for action in (
                PARENT_NEW,
                PARENT_LINK,
                PARENT_LINKED,
                PARENT_BLOCKED,
                PARENT_SKIPPED,
            )
        },
        "leaving": len(plan.leaving),
    }


def payload(parsed: Parsed, plan: Plan) -> dict:
    """Ответ предпросмотра и применения — одной формы, как у вставки."""
    return {
        "group": parsed.group,
        "rows": parsed.rows,
        "duplicates": parsed.duplicates,
        **counts(plan),
        "people": [
            {
                "line": item.pupil.line,
                "email": item.pupil.email,
                "name": item.who,
                "external_id": item.pupil.external_id,
                "previous_email": item.previous_email,
                "action": item.action,
                "code": item.code,
                "detail": item.detail,
                "parents": [
                    {
                        "email": adult.adult.email,
                        "name": adult.who,
                        "action": adult.action,
                        "code": adult.code,
                        "detail": adult.detail,
                    }
                    for adult in item.parents
                ],
            }
            for item in plan.pupils
        ],
        "leaving_people": [
            {
                "row": row.pk,
                "email": row.student.email,
                "name": full_name(row.student),
            }
            for row in plan.leaving
        ],
        "errors": parsed.errors,
        "warnings": parsed.warnings,
    }


@transaction.atomic
def apply_import(plan: Plan, course, *, by, remove_missing: bool) -> dict:
    """
    Записать то, что показал предпросмотр. Одной транзакцией.

    Занятый адрес применение не отменяет — про него сказано поимённо и
    заранее. Снятие с курса тех, кого в файле нет, — по явной галочке: файл
    это полный состав группы на момент выгрузки, и по умолчанию она
    включена, но выключить её можно — например, когда выгружены не все.
    """
    from families.models import link

    school = course.school
    # заведённые этим же применением: вторая строка того же родителя
    made: dict[str, object] = {}

    for decision in plan.pupils:
        if decision.action == BLOCKED:
            continue

        pupil = decision.pupil
        if decision.action == NEW:
            decision.account = welcome(
                pupil.email,
                Kind.STUDENT,
                first=pupil.first,
                last=pupil.last,
                school=school,
                by=by,
            )
        student = decision.account
        refresh(student, pupil.email, pupil.first, pupil.last, pupil.external_id)
        services.enrol(student, course, by=by)

        for item in decision.parents:
            if item.action not in (PARENT_NEW, PARENT_LINK):
                continue
            if item.action == PARENT_NEW:
                item.account = welcome(
                    item.adult.email,
                    Kind.PARENT,
                    first=item.adult.first,
                    last=item.adult.last,
                    school=school,
                    by=by,
                )
                made[item.adult.email] = item.account
            elif item.adult.email in made:
                # заведён этой же загрузкой по строке брата или сестры: экземпляр
                # из выборки плана этого не знает — у учётки без школы, принятой
                # первой строкой, там ещё старые вид и школа
                item.account = made[item.adult.email]
            else:
                refresh(item.account, item.adult.email, item.adult.first, item.adult.last)
            link(item.account, student)

    if remove_missing:
        for row in plan.leaving:
            services.remove_from_course(row)

    return counts(plan)


def welcome(email: str, kind: str, *, first: str, last: str, school, by):
    """
    Завести человека, которого ещё нет, и выписать ему приглашение.

    То же, что делает вставка состава, только имя и фамилия приезжают
    отдельно — файл их и хранит порознь.
    """
    label = " ".join(filter(None, (first, last)))
    Invitation.objects.get_or_create(
        school=school,
        email=email,
        defaults={"kind": kind, "name": label, "created_by": by},
    )
    return services.provision(school, email, kind=kind, name=first, last_name=last)


def refresh(user, email: str, first: str, last: str, external_id: str = ""):
    """
    Подтянуть у заведённого человека то, что говорит источник.

    Адрес и номер — ключи, и обновляются всегда: адрес поменяли в источнике,
    номер записали впервые. Имя — только у того, кто ещё не входил: до
    первого входа в полях лежит ярлык из файла, а после — то, что человек
    принёс с собой, и файлу оно не подчиняется.
    """
    changed = []
    if user.email.lower() != email:
        user.email = email
        changed.append("email")
    if external_id and user.external_id != external_id:
        user.external_id = external_id
        changed.append("external_id")
    if user.last_login is None:
        if first and user.first_name != first:
            user.first_name = first[:150]
            changed.append("first_name")
        if last and user.last_name != last:
            user.last_name = last[:150]
            changed.append("last_name")
    if changed:
        user.save(update_fields=changed)
