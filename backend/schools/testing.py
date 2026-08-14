"""
Fixtures every app's tests need: a school, the people in it, and their work.

Since everything is scoped by school, almost every test starts the same way —
one school, one teacher, and usually a second person to prove they cannot see
the first one's work. Repeating that in each setUp invited copies that slowly
drifted apart, so it lives here.

The builders below keep the invariants the API enforces. A slot takes its year
from its course rather than accepting one, because a slot whose year differs
from its course's year is refused by the serializer (`slot_year_mismatch`) —
a fixture that can express it would be testing a state the product cannot
reach.
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.authtoken.models import Token

from .models import School

User = get_user_model()

# the school year every test uses unless it needs its own dates
YEAR_START = date(2026, 9, 1)
YEAR_END = date(2027, 5, 31)
# the first full Monday inside it: the usual starting point for a week
MONDAY = date(2026, 9, 7)


# --- people ------------------------------------------------------------------


def make_school(name="Test school") -> School:
    return School.objects.create(name=name)


def make_user(
    school=None, email="teacher@example.com", *, admin=False, root=False, student=False
):
    """
    A member of the school; `school=None` gives somebody nobody invited.

    `root` is a Django superuser — the only role that means anything outside
    a school, and only in the section that creates them.

    `student` — второй вид пользователя. Он тоже в школе, но учительские
    разделы ему закрыты, и проверяет это матрица прав.
    """
    return User.objects.create_user(
        email=email,
        school=school,
        kind=User.Kind.STUDENT if student else User.Kind.TEACHER,
        is_school_admin=admin,
        is_superuser=root,
        is_staff=root,
    )


def token_for(user) -> str:
    return Token.objects.get_or_create(user=user)[0].key


def sign_in(client, user):
    """Point an APIClient at this user for the rest of the test."""
    client.credentials(HTTP_AUTHORIZATION=f"Token {token_for(user)}")
    return user


# --- what the school owns ----------------------------------------------------


def make_year(school, name="2026/2027", start=YEAR_START, end=YEAR_END):
    from calendars.models import SchoolYear

    return SchoolYear.objects.create(
        school=school, name=name, start_date=start, end_date=end
    )


def make_course(school, year=None, name="9Б", grade=None, subject=None):
    """A course of the school. Without a year, one is made to hold it."""
    from schedule.models import Course

    return Course.objects.create(
        school=school,
        year=year or make_year(school),
        name=name,
        grade=grade,
        subject=subject,
    )


def make_grade(school, level=9, name=None):
    """
    A year group of the school.

    `get_or_create` because a test may ask for «the ninth» twice: that is the
    same row, and the unique constraint agrees. New schools start with no
    year groups at all — eleven guessed rows were worse than an empty list.
    """
    from schedule.models import GradeLevel
    from schedule.services import grade_name

    grade, _ = GradeLevel.objects.get_or_create(
        school=school, level=level, defaults={"name": name or grade_name(level)}
    )
    # имя, названное здесь для уже существующего уровня, — это
    # переименование: «MYP 4» поверх умолчания «Grade 9»
    if name and grade.name != name:
        grade.name = name
        grade.save(update_fields=["name"])
    return grade


def assign(teacher, course):
    """
    Поставить учителя на курс — связь, на которой висит всё личное.

    Ведущий у курса один, поэтому назначение **заменяет** прежнее, а не
    добавляется рядом: фикстура, обходящая уникальность, выражала бы
    состояние, недостижимое через приложение.
    """
    from schedule.models import CourseAssignment

    CourseAssignment.objects.filter(course=course).exclude(teacher=teacher).delete()
    return CourseAssignment.objects.get_or_create(course=course, teacher=teacher)[0]


def make_work(teacher, course, *, title="Контрольная", opens=None, closes=None, **fields):
    """
    Работа курса. Окно по умолчанию — открытое прямо сейчас.

    Открытое, потому что закрытая работа не даёт отправить ответ, а именно
    отправка — то, вокруг чего крутятся правила; тест про закрытое окно
    двигает даты сам.

    Учитель здесь остался, хотя работа ему больше не принадлежит: как и у
    `make_node`, он назначается на курс — правит работы назначенный, и
    тесты прав спрашивают именно про это.
    """
    from django.utils import timezone
    from works.models import Work

    assign(teacher, course)
    now = timezone.now()

    return Work.objects.create(
        created_by=teacher,
        course=course,
        title=title,
        opens_at=opens or now - timedelta(hours=1),
        closes_at=closes or now + timedelta(days=7),
        **fields,
    )


def make_task(work, question="Сколько будет 2+2?", answers=("4",), position=0):
    from works.models import Task

    return Task.objects.create(
        work=work, question=question, answers=list(answers), position=position
    )


def make_term(year, name="1 четверть", start=None, end=None):
    from calendars.models import Term

    return Term.objects.create(
        year=year,
        name=name,
        start_date=start or year.start_date,
        end_date=end or date(2026, 10, 25),
    )


def make_exception(year, day=date(2026, 11, 4), kind="holiday", title="Праздник"):
    from calendars.models import DayException

    return DayException.objects.create(
        year=year, start_date=day, end_date=day, kind=kind, title=title
    )


# --- what a teacher owns inside it -------------------------------------------


def make_slot(teacher, course, day=MONDAY, number=1, **flags):
    """
    Один урок. Год берётся у курса — отдельно он не передаётся никогда.

    Учитель здесь остался, хотя у слота его больше нет: расписание
    принадлежит курсу, а по дороге фикстура назначает человека ведущим —
    урок в курсе, который никому не поручен, API так же не даёт завести.
    """
    from schedule.models import LessonSlot

    assign(teacher, course)

    return LessonSlot.objects.create(
        year=course.year,
        course=course,
        date=day,
        lesson_number=number,
        **flags,
    )


def make_node(teacher, course, title="Урок", *, parent=None, position=0, section=False):
    """
    Строка плана. Как и `make_slot`, назначает учителя на курс.

    Учитель здесь остался, хотя у самой строки его больше нет: план
    принадлежит курсу, а править его может только назначенный — и тесты
    прав спрашивают именно про это.
    """
    from plans.models import PlanNode

    assign(teacher, course)

    return PlanNode.objects.create(
        course=course,
        parent=parent,
        position=position,
        is_section=section,
        title=title,
    )


def make_subject(school, name="Алгебра"):
    """
    A subject of the school. Reused rather than duplicated.

    get_or_create because a subject is reference data: a test that asks for
    «Алгебра» twice means the same one, and the model's unique constraint
    agrees.
    """
    from schedule.models import Subject

    return Subject.objects.get_or_create(school=school, name=name)[0]


def make_template(school, author, *, subject=None, grade=9, title="Шаблон",
                  published=True, rows=()):
    """
    A shelf entry. `rows` are (is_header, title) pairs in display order.

    Published by default: a draft is the special case worth spelling out at
    the call site, since «who can see it» is what most of these tests are
    about.
    """
    from library.models import PlanTemplate, PlanTemplateRow

    template = PlanTemplate.objects.create(
        school=school,
        subject=subject or make_subject(school),
        grade=grade,
        title=title,
        author=author,
        is_published=published,
    )
    PlanTemplateRow.objects.bulk_create(
        PlanTemplateRow(
            template=template, position=position, is_header=header, title=name
        )
        for position, (header, name) in enumerate(rows)
    )
    return template


# --- files ---------------------------------------------------------------------

# Nothing here swaps the storage: `config.testing.Runner` does it for the
# whole run, so a test that uploads without meaning to (running `seed_demo`,
# say) cannot reach R2 either.


def make_upload(name="worksheet.pdf", content=b"%PDF-1.4 demo", kind="application/pdf"):
    return SimpleUploadedFile(name, content, content_type=kind)


def make_stored_file(school, uploader=None, **kwargs):
    """
    A file that is really in the store, put there the way the API puts it.

    Going through `store_upload` rather than `objects.create` on purpose: a
    row whose object does not exist is a state the product cannot reach, and
    a fixture that can express it would quietly make the deletion tests pass
    for the wrong reason.
    """
    from files.services import store_upload

    return store_upload(upload=make_upload(**kwargs), school=school, user=uploader)[0]


def make_attachment(row, stored=None, *, title="Worksheet", url=""):
    """A reference from a plan lesson or a template row. Files are not copied."""
    from files.models import KIND_FILE, KIND_LINK, Attachment

    owner = "template_row" if hasattr(row, "is_header") else "plan_row"

    return Attachment.objects.create(
        **{owner: row},
        kind=KIND_LINK if stored is None else KIND_FILE,
        stored_file=stored,
        url=url,
        title=title,
        position=0,
    )


class SchoolTestMixin:
    """
    One school, one teacher signed in, and the cast for the access tests.

    The names say what each person is for:

    * `user` — a teacher of this school, signed in by default;
    * `admin` — an administrator of the same school;
    * `colleague` — another plain teacher here, for "not mine" checks;
    * `stranger` / `alien_admin` — the same two roles in another school;
    * `outsider` — signed in, invited by nobody;
    * `root` — a Django superuser, built on demand by `make_root()`.
    * `student` — ученик своей школы: в школе состоит, учителем не является.
    """

    def setUp(self):
        super().setUp()
        self.school = make_school("Test school")
        self.alien_school = make_school("Another school")

        self.user = make_user(self.school, "teacher@example.com")
        self.admin = make_user(self.school, "admin@example.com", admin=True)
        self.colleague = make_user(self.school, "colleague@example.com")
        self.stranger = make_user(self.alien_school, "stranger@example.com")
        self.alien_admin = make_user(
            self.alien_school, "alien-admin@example.com", admin=True
        )
        self.outsider = make_user(None, "nobody@example.com")
        # ученик своей школы: членство есть, учительские разделы закрыты
        self.student = make_user(self.school, "student@example.com", student=True)

        sign_in(self.client, self.user)

    def sign_in(self, user):
        return sign_in(self.client, user)

    def make_root(self, email="root@example.com", school=None):
        """A superuser. Not in the default cast — most tests do not need one."""
        return make_user(school if school is not None else self.school, email, root=True)
