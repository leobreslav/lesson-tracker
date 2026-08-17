"""
`seed_demo` invents data and can delete it, so the guards matter more than
the data itself.

The test runner turns DEBUG off, which is why the refusal is checked without
any setup and everything else runs under `override_settings(DEBUG=True)`.
"""

from datetime import timedelta
from io import StringIO

from calendars.models import DayException, SchoolYear, Term
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db.models import F
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from plans.models import PlanNode
from schedule.models import Course, CourseStudent, Slot
from collections import defaultdict

from django.db.models import Count
from django.utils import timezone

from schools import rich_demo

from works.models import Submission, Work


def state_of(history):
    """Состояние клетки по её журналу — как его считает сводная таблица."""
    last = history[-1]
    if last.is_correct is None:
        checked_before = any(row.is_correct is not None for row in history[:-1])
        return "redone" if checked_before else "unchecked"
    return "correct" if last.is_correct else "wrong"

from .models import Invitation, School

User = get_user_model()


def seed(*args):
    out = StringIO()
    call_command("seed_demo", *args, stdout=out)
    return out.getvalue()


class DebugGuardTests(TestCase):
    def test_it_refuses_to_run_with_debug_off(self):
        """The one thing standing between invented data and the live база."""
        with self.assertRaises(CommandError) as caught:
            seed()

        self.assertIn("DEBUG=True", str(caught.exception))
        self.assertFalse(School.objects.exists())

    @override_settings(DEBUG=True)
    def test_with_debug_on_it_runs(self):
        seed()

        self.assertTrue(School.objects.exists())


@override_settings(DEBUG=True)
class SeedTests(TestCase):
    def test_an_empty_database_gets_a_whole_school(self):
        seed()

        school = School.objects.get()
        self.assertEqual(school.name, "Тестовая школа")

        year = SchoolYear.objects.get(school=school)
        self.assertEqual(year.name, "2026/2027")
        self.assertEqual(Term.objects.filter(year=year).count(), 4)
        self.assertEqual(Course.objects.filter(school=school).count(), 4)
        self.assertEqual(User.objects.filter(school=school, kind="teacher").count(), 3)
        self.assertEqual(User.objects.filter(is_school_admin=True).count(), 1)

    def test_the_students_come_with_their_three_states(self):
        """
        Демо показывает не ровный список, а состояния, на которых экраны и
        расходятся: обычный ученик, снятый с курса и ещё не входивший.
        """
        seed()

        # число берётся из самого списка: класс в демо должен быть
        # похож на класс, и подгонять тест под каждого нового ученика — не
        # то же самое, что проверять три состояния
        from schools.management.commands.seed_demo import STUDENTS

        enrolments = CourseStudent.objects.all()
        self.assertEqual(
            enrolments.filter(removed_at__isnull=True).count(), len(STUDENTS) - 1
        )
        self.assertEqual(enrolments.filter(removed_at__isnull=False).count(), 1)
        self.assertGreater(len(STUDENTS), 10, "класс из пяти человек — не класс")
        self.assertEqual(
            Invitation.objects.filter(kind="student", accepted_at__isnull=True).count(),
            1,
        )
        # у ученика есть учётка со своим видом, а не «учитель без курсов»
        self.assertTrue(
            User.objects.get(email="stepanov@example.com").is_student
        )

    def test_the_markup_has_breaks_and_holidays(self):
        seed()

        markup = DayException.objects.all()
        self.assertEqual(markup.filter(kind="vacation").count(), 3)
        self.assertEqual(markup.filter(kind="holiday").count(), 4)

    def test_the_schedule_avoids_non_study_days(self):
        """The seeder asks the calendar rather than guessing."""
        seed()

        year = SchoolYear.objects.get()
        study = {day.date for day in year.build_days() if day.is_study}
        # extra lessons are put next to a regular one on purpose and may
        # legitimately land on a day off — the regular ones may not
        regular = Slot.objects.filter(is_extra=False)

        self.assertTrue(regular.exists())
        self.assertEqual(
            [slot.date for slot in regular if slot.date not in study], []
        )

    def test_the_interface_states_are_all_present(self):
        """
        The point of the whole command: something to look at for each state.

        A course with a full plan, one with a plan that runs out, one with
        neither plan nor timetable, plus cancellations and extra lessons.
        """
        seed()

        courses = {course.name: course for course in Course.objects.all()}

        full = PlanNode.objects.filter(
            course=courses["Grade 6 Algebra"], is_section=False
        ).count()
        partial = PlanNode.objects.filter(
            course=courses["Grade 9 Algebra"], is_section=False
        ).count()

        self.assertGreater(full, 35)
        self.assertLess(partial, full)
        self.assertFalse(
            PlanNode.objects.filter(course=courses["Grade 6 Geometry"]).exists()
        )
        self.assertFalse(
            Slot.objects.filter(course=courses["Grade 9 Geometry"]).exists()
        )
        self.assertTrue(Slot.objects.filter(is_cancelled=True).exists())
        self.assertTrue(Slot.objects.filter(is_extra=True).exists())

    def test_the_plans_are_split_into_blocks(self):
        seed()

        sections = PlanNode.objects.filter(is_section=True)
        self.assertGreater(sections.count(), 3)
        self.assertTrue(
            PlanNode.objects.filter(is_section=False, parent__isnull=False).exists()
        )

    def test_the_summary_says_what_was_made(self):
        output = seed()

        self.assertIn("Тестовая школа", output)
        self.assertIn("2026/2027", output)
        self.assertIn("Grade 6 Algebra", output)


@override_settings(DEBUG=True)
class RepeatTests(TestCase):
    def counts(self):
        return {
            "schools": School.objects.count(),
            "years": SchoolYear.objects.count(),
            "terms": Term.objects.count(),
            "markup": DayException.objects.count(),
            "courses": Course.objects.count(),
            "users": User.objects.count(),
            "slots": Slot.objects.count(),
            "cancelled": Slot.objects.filter(is_cancelled=True).count(),
            "extra": Slot.objects.filter(is_extra=True).count(),
            "plan": PlanNode.objects.count(),
        }

    def test_a_second_run_changes_nothing(self):
        seed()
        after_one = self.counts()

        seed()

        self.assertEqual(self.counts(), after_one)

    def test_three_runs_change_nothing_either(self):
        """
        Marking lessons by hand is the part that used to drift.

        Picking «the twelfth lesson» over a set the command itself grows
        made the second run cancel a different one, so the count crept up.
        """
        seed()
        after_one = self.counts()

        seed()
        seed()

        self.assertEqual(self.counts(), after_one)


@override_settings(DEBUG=True)
class WorksTests(TestCase):
    def test_the_works_come_in_their_three_states(self):
        """
        Открытая, закрытая и запланированная — те же три состояния, что у
        остального seed'а, и расходятся экраны как раз на них: закрытая не
        принимает ответы, запланированной ученик не видит вовсе.
        """
        seed()

        states = sorted(work.state() for work in Work.objects.all())

        self.assertEqual(states, ["closed", "open", "planned"])

    def test_the_answers_show_every_state_a_cell_can_have(self):
        """
        Пустая сетка не проверяет ничего, а ровная — проверяет только один
        случай из пяти. В демо есть все: пусто, отправлено, верно, неверно
        и переделано после проверки.
        """
        seed()

        closed = Work.objects.get(title__startswith="Контрольная")
        cells = defaultdict(list)
        for row in Submission.objects.filter(task__work=closed).order_by(
            "created_at", "id"
        ):
            cells[(row.task_id, row.student_id)].append(row)

        states = {state_of(history) for history in cells.values()}
        self.assertEqual(states, {"correct", "wrong", "unchecked", "redone"})
        # и пустые клетки: не у всех есть ответ на каждую задачу
        self.assertLess(len(cells), closed.tasks.count() * CourseStudent.objects.count())

    def test_running_it_twice_does_not_double_the_answers(self):
        seed()
        before = Submission.objects.count()

        seed()

        self.assertEqual(Submission.objects.count(), before)


@override_settings(DEBUG=True)
class FlushTests(TestCase):
    def test_flush_clears_what_was_there_and_builds_again(self):
        seed()
        stale = Course.objects.create(
            school=School.objects.get(),
            year=SchoolYear.objects.get(),
            name="Лишний курс",
        )

        seed("--flush")

        self.assertFalse(Course.objects.filter(pk=stale.pk).exists())
        self.assertEqual(Course.objects.count(), 4)
        self.assertEqual(School.objects.count(), 1)

    def test_flush_keeps_superusers(self):
        """Wiping the account you administer the box with is never meant."""
        root = User.objects.create_superuser(
            email="root@example.com", password="S3cret-pass-123"
        )

        seed("--flush")

        root.refresh_from_db()
        self.assertTrue(root.is_superuser)
        self.assertIsNone(root.school)


@override_settings(DEBUG=True)
class MinimalTests(TestCase):
    def test_minimal_stops_after_the_courses(self):
        seed("--minimal")

        self.assertEqual(Course.objects.count(), 4)
        self.assertEqual(Term.objects.count(), 4)
        self.assertFalse(Slot.objects.exists())
        self.assertFalse(PlanNode.objects.exists())


@override_settings(DEBUG=True)
class AttachTests(TestCase):
    def test_an_existing_account_joins_as_an_administrator(self):
        me = User.objects.create_user(email="me@example.com")

        output = seed("--email=me@example.com")

        me.refresh_from_db()
        self.assertEqual(me.school, School.objects.get())
        self.assertTrue(me.is_school_admin)
        self.assertIn("me@example.com", output)

    def test_the_address_is_matched_case_insensitively(self):
        me = User.objects.create_user(email="me@example.com")

        seed("--email=Me@Example.com")

        me.refresh_from_db()
        self.assertTrue(me.is_school_admin)

    def test_an_unknown_address_gets_an_invitation_instead(self):
        """They have not signed in yet — the first Google login lands them."""
        output = seed("--email=stranger@example.com")

        invitation = Invitation.objects.get(email="stranger@example.com")
        self.assertTrue(invitation.is_school_admin)
        self.assertEqual(invitation.school, School.objects.get())
        self.assertIn("приглашение", output)

    def test_without_the_flag_nobody_is_attached(self):
        me = User.objects.create_user(email="me@example.com")

        seed()

        me.refresh_from_db()
        self.assertIsNone(me.school)


@override_settings(DEBUG=True)
class RichSeedTests(TestCase):
    """
    Крупный набор: школа в рабочем размере.

    Проверяется не содержимое (оно выдуманное и меняется), а три свойства,
    без которых набором нельзя пользоваться: год содержит сегодня, данные
    возможны, второй прогон ничего не удваивает.
    """

    def test_the_year_always_holds_today(self):
        """
        Иначе в наборе нет ни одного проведённого занятия.

        А без прошлого не видно ни связи «занятие проведено», ни долгов, ни
        разложения резерва — то есть половины того, ради чего он и нужен.
        """
        seed("--rich")

        today = timezone.localdate()
        year = SchoolYear.objects.order_by("-start_date").first()

        self.assertLessEqual(year.start_date, today)
        self.assertLess(today, year.end_date)
        self.assertTrue(
            Slot.objects.filter(date__lt=today).exists(), "прошедших занятий нет"
        )

    def test_every_teacher_has_three_big_plans(self):
        seed("--rich")

        for email in ("sidorova@example.com", "kovalev@example.com",
                      "nikitina@example.com"):
            teacher = User.objects.get(email=email)
            courses = Course.objects.for_teacher(teacher)
            with self.subTest(email):
                self.assertEqual(courses.count(), 3)
                for course in courses:
                    self.assertGreaterEqual(
                        PlanNode.objects.filter(
                            course=course, is_section=False
                        ).count(),
                        40,
                    )

    def test_nobody_teaches_two_lessons_at_once(self):
        """
        Набор, выражающий невозможное, хуже отсутствия набора.

        Через интерфейс такого расписания не построить, а `bulk_create`
        проходит мимо валидации — поэтому сборка сама себя и проверяет
        (`rich_demo.check_conflicts`), а этот тест следит, что проверка на
        месте и что данные её проходят.
        """
        seed("--rich")

        clashes = (
            Slot.objects.filter(
                is_cancelled=False, course__assignments__teacher__isnull=False
            )
            .values("course__assignments__teacher", "date", "lesson_number")
            .annotate(times=Count("id"))
            .filter(times__gt=1)
        )

        self.assertEqual(list(clashes), [])

    def test_the_guard_catches_an_impossible_timetable(self):
        """Проверено поломкой: иначе сторож — просто вызов без последствий."""
        seed("--rich")
        first = Slot.objects.filter(is_cancelled=False).first()
        twin = (
            Course.objects.filter(
                assignments__teacher__in=first.course.assignments.values("teacher")
            )
            .exclude(pk=first.course_id)
            .first()
        )
        Slot.objects.create(
            year=first.year,
            course=twin,
            date=first.date,
            lesson_number=first.lesson_number,
        )

        with self.assertRaises(ValueError):
            rich_demo.check_conflicts()

    def test_running_twice_does_not_double_anything(self):
        seed("--rich")
        before = (
            Course.objects.count(),
            PlanNode.objects.count(),
            Slot.objects.count(),
            Work.objects.count(),
            Submission.objects.count(),
            User.objects.count(),
        )

        seed("--rich")

        self.assertEqual(
            (
                Course.objects.count(),
                PlanNode.objects.count(),
                Slot.objects.count(),
                Work.objects.count(),
                Submission.objects.count(),
                User.objects.count(),
            ),
            before,
        )

    def test_records_leave_no_gap_behind_them(self):
        """
        Записи идут подряд: незакрытых часов **до последней записи** нет.

        Сторож заведён по следам живой базы. Дырка там появилась не от
        кривой раскладки, а от времени: набор сеют повторно, между посевами
        проходят дни, и вчерашнее будущее становится прошлым. Пока `record`
        выходил рано («у курса уже есть записи»), такие часы оставались
        незакрытыми **позади** записанных, а строгая очередь этого не
        прощает — следующую запись такая дырка держит навсегда.
        """
        seed("--rich")
        today = timezone.localdate()

        # Между посевами проходят дни, и вчерашнее будущее становится
        # прошлым: запись, поставленная в прошлый раз, оказывается **за**
        # сегодняшней границей «закрываем всё, кроме хвоста». Двигать даты
        # нечем — недельная сетка ляжет сама на себя, — но состояние то же:
        # записанный час позади границы. Ставим его руками и сеем снова.
        # курс, у которого набор намеренно оставляет хвост незакрытым:
        # именно за этой границей и оказывается запись из прошлого посева
        course = Course.objects.get(name="Grade 8 Algebra")
        last = (
            Slot.objects.filter(
                course=course, date__lt=today, is_cancelled=False, lesson__isnull=True
            )
            .order_by("-date", "-lesson_number")
            .first()
        )
        self.assertIsNotNone(last, "у курса нет незакрытого хвоста")
        taken = set(
            Slot.objects.filter(course=course, lesson__isnull=False).values_list(
                "lesson_id", flat=True
            )
        )
        free = (
            PlanNode.objects.filter(course=course, is_section=False)
            .exclude(pk__in=taken)
            .order_by("-position")
            .first()
        )
        self.assertIsNotNone(free, "в плане не осталось свободной строки")
        last.lesson = free
        last.save(update_fields=["lesson"])

        seed("--rich")

        holes = {}
        for course in Course.objects.all():
            past = list(
                Slot.objects.filter(
                    course=course, date__lte=today, is_cancelled=False
                ).order_by("date", "lesson_number")
            )
            recorded = [i for i, slot in enumerate(past) if slot.lesson_id]
            if not recorded:
                continue
            gap = sum(1 for slot in past[: recorded[-1]] if slot.lesson_id is None)
            if gap:
                holes[course.name] = gap

        self.assertEqual(holes, {}, "перед записанными часами остались незакрытые")

    def test_make_ups_land_on_study_days_bar_one(self):
        """
        Отработка в выходной — настоящее состояние, но не в шестнадцати
        экземплярах.

        «Ближайшую субботу» получали все девятнадцать курсов сразу, и набор
        показывал шестнадцать занятий в один неучебный день — то есть учил
        читать предупреждение как фон.
        """
        seed("--rich")
        year = SchoolYear.objects.order_by("-start_date").first()
        study = {day.date for day in year.build_days() if day.status == "study"}

        stray = [
            slot
            for slot in Slot.objects.filter(year=year, is_cancelled=False)
            if slot.date not in study
        ]

        self.assertLessEqual(len(stray), 1, [str(slot.date) for slot in stray])

    def test_recording_shows_all_three_states(self):
        """
        Закрыто всё, закрыто не всё, не начинали.

        Ровный набор — один из этих трёх — показывал бы долги неправильно и
        выглядел бы правильно: «ноль» одинаково честен и когда закрывать
        нечего, и когда никто не начинал.
        """
        seed("--rich")
        today = timezone.localdate()

        states = set()
        for course in Course.objects.all():
            past = Slot.objects.filter(
                course=course, date__lt=today, is_cancelled=False
            )
            if not past.exists():
                continue
            bound = past.filter(lesson__isnull=False).count()
            if bound == 0:
                states.add("не начинали")
            elif bound == past.count():
                states.add("закрыто всё")
            else:
                states.add("есть долги")

        self.assertEqual(states, {"не начинали", "закрыто всё", "есть долги"})

    def test_the_plain_seed_keeps_its_fixed_year(self):
        """
        Браузерные тесты знают эти даты наизусть.

        Живой год нужен крупному набору и только ему: на маленьком стоят
        сто с лишним проверок, в которых «первый понедельник» написан
        числом.
        """
        seed()

        year = SchoolYear.objects.get()
        self.assertEqual(str(year.start_date), "2026-09-01")
        self.assertEqual(str(year.end_date), "2027-05-31")
