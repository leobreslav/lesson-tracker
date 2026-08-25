"""
Журнал курса: ученики по строкам, занятия по столбцам.

Проверяется здесь то, из чего журнал и состоит: столбец — это занятие, а не
работа; оценка попадает в тот столбец, к занятию которого работа привязана;
работа без занятия не пропадает; посещаемость стоит в той же клетке. И
отдельно — что семье видна одна строка и ровно то, что ей уже открыто.
"""

from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from schedule.models import Attendance
from schools.services import enrol
from schools.testing import (
    SchoolTestMixin,
    assign,
    make_course,
    make_node,
    make_slot,
    make_term,
    make_user,
    make_work,
    make_year,
)

from . import services
from .models import StudentWork

MONDAY = date(2026, 9, 7)


class JournalTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.term = make_term(self.year, "1 четверть", start=self.year.start_date)
        self.course = make_course(self.school, self.year)
        assign(self.user, self.course)

        self.student.first_name, self.student.last_name = "Фил", "Бурмов"
        self.student.save()
        enrol(self.student, self.course, by=self.admin)

        self.first = make_slot(self.user, self.course, day=MONDAY, number=1)
        self.second = make_slot(
            self.user, self.course, day=MONDAY + timedelta(days=2), number=1
        )

        self.client.force_authenticate(self.user)

    def journal(self, **params):
        return self.client.get(
            reverse("course-journal"), {"course": self.course.pk, **params}
        ).json()

    def graded(self, *, slot=None, title="Проверочная", value=4, opens=None):
        """Работа с выставленной руками отметкой — самый короткий путь к клетке."""
        work = make_work(self.user, self.course, title=title, opens=opens)
        if slot is not None:
            work.slot = slot
            work.save(update_fields=["slot"])
        row, _ = StudentWork.objects.get_or_create(work=work, student=self.student)
        row.grade = str(value)
        row.save(update_fields=["grade"])
        return work

    def test_columns_are_lessons_and_they_keep_the_order_of_the_year(self):
        """
        Столбец — занятие, а не работа.

        Работ на занятии бывает несколько, а бывает ни одной — и тогда столбец
        всё равно нужен: в нём стоит посещаемость. Сделай столбцом работу, и
        журнал потерял бы дни, в которые ничего не задавали, то есть большую
        часть года.
        """
        body = self.journal()

        self.assertEqual(
            [column["slot"] for column in body["columns"]],
            [self.first.pk, self.second.pk],
        )
        self.assertEqual(body["columns"][0]["date"], str(MONDAY))

    def test_a_mark_lands_in_the_column_of_the_lesson_it_was_set_at(self):
        work = self.graded(slot=self.second)

        body = self.journal()
        row = body["students"][0]

        self.assertEqual(row["cells"][0]["marks"], [])
        self.assertEqual(
            [mark["label"] for mark in row["cells"][1]["marks"]], ["4"]
        )
        self.assertEqual(
            [head["id"] for head in body["columns"][1]["works"]], [work.pk]
        )

    def test_one_lesson_carries_as_many_marks_as_there_were_works(self):
        """Проверочная и домашняя в один день — это две оценки в одной клетке."""
        self.graded(slot=self.first, title="Проверочная", value=5)
        self.graded(slot=self.first, title="Домашняя", value=3)

        row = self.journal()["students"][0]

        self.assertEqual(
            sorted(mark["label"] for mark in row["cells"][0]["marks"]), ["3", "5"]
        )

    def test_a_work_without_a_lesson_gets_a_column_of_its_own(self):
        """
        Потерять оценку потому, что учитель не указал занятие, нельзя.

        Привязка необязательна намеренно — контрольная за четверть, пересдача,
        работа «на неделю», — и такие идут своими столбцами в конце. Даты у
        них нет: она была бы выдумкой.
        """
        work = self.graded(
            slot=None,
            title="Зачёт за четверть",
            opens=timezone.make_aware(
                timezone.datetime(MONDAY.year, MONDAY.month, MONDAY.day, 9, 0)
            ),
        )

        body = self.journal()
        last = body["columns"][-1]

        self.assertIsNone(last["slot"])
        self.assertIsNone(last["date"])
        self.assertEqual([head["id"] for head in last["works"]], [work.pk])
        self.assertEqual(
            [mark["label"] for mark in body["students"][0]["cells"][-1]["marks"]], ["4"]
        )

    def test_attendance_stands_in_the_same_cell(self):
        """
        Посещаемость — про то же занятие, что и оценка, и место у них одно.

        Врозь это были бы две таблицы с одинаковой шапкой, и читать их
        пришлось бы, ведя пальцем по двум экранам сразу.
        """
        Attendance.objects.create(
            slot=self.first, student=self.student, status="absent", note="болел"
        )

        cells = self.journal()["students"][0]["cells"]

        self.assertEqual(cells[0]["attendance"], "absent")
        self.assertEqual(cells[0]["note"], "болел")
        self.assertIsNone(cells[1]["attendance"], "не отмечено — это не «был»")

    def test_the_lesson_of_the_plan_names_the_column(self):
        """Шапка ведёт на занятие, а название объясняет, зачем туда идти."""
        node = make_node(self.user, self.course, "Теорема Пифагора")
        self.first.lesson = node
        self.first.save(update_fields=["lesson"])

        column = self.journal()["columns"][0]

        self.assertEqual(column["lesson"], {"id": node.pk, "title": "Теорема Пифагора"})

    def test_a_term_shows_its_own_lessons_and_the_year_shows_all(self):
        """
        Умолчание — терм, и это про читаемость: за год столбцов до семидесяти.

        Год целиком остаётся доступен явной просьбой: «весь год» отвечает на
        другой вопрос — не «как идёт четверть», а «как прошёл год».
        """
        beyond = make_slot(
            self.user, self.course, day=self.term.end_date + timedelta(days=7), number=1
        )

        inside = self.journal(term=self.term.pk)
        whole = self.journal(term="all")

        self.assertNotIn(beyond.pk, [column["slot"] for column in inside["columns"]])
        self.assertIn(beyond.pk, [column["slot"] for column in whole["columns"]])

    def test_somebody_else_s_course_does_not_exist(self):
        """Журнал чужого класса — сведение, которого учителю знать неоткуда."""
        other = make_course(self.school, self.year, name="10А")

        answer = self.client.get(reverse("course-journal"), {"course": other.pk})

        self.assertEqual(answer.status_code, 404)


class FamilyJournalTests(SchoolTestMixin, APITestCase):
    """
    Тот же журнал глазами семьи: строка одна и ровно то, что уже открыто.

    Расчёт общий с учительским намеренно. Разойдись он — и родитель на
    собрании увидел бы не то, что учитель у себя, а объяснить это было бы
    некому.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.term = make_term(self.year, "1 четверть", start=self.year.start_date)
        self.course = make_course(self.school, self.year)
        assign(self.user, self.course)

        self.classmate = make_user(self.school, "mate@example.com", student=True)
        self.classmate.first_name, self.classmate.last_name = "Пётр", "Тиборов"
        self.classmate.save()
        enrol(self.student, self.course, by=self.admin)
        enrol(self.classmate, self.course, by=self.admin)

        self.slot = make_slot(self.user, self.course, day=MONDAY, number=1)

    def graded(self, person, value, **fields):
        work = make_work(self.user, self.course, **fields)
        work.slot = self.slot
        work.save(update_fields=["slot"])
        row, _ = StudentWork.objects.get_or_create(work=work, student=person)
        row.grade = str(value)
        row.save(update_fields=["grade"])
        return work

    def test_the_family_sees_one_row_and_it_is_its_own(self):
        self.graded(self.student, 5)
        self.graded(self.classmate, 2)

        self.client.force_authenticate(self.student)
        body = self.client.get(
            reverse("student-journal"), {"course": self.course.pk}
        ).json()

        self.assertEqual([row["id"] for row in body["students"]], [self.student.pk])
        self.assertEqual(
            sorted(mark["label"] for mark in body["students"][0]["cells"][0]["marks"]),
            ["5"],
        )

    def test_a_result_the_class_has_not_been_told_yet_is_not_told_here(self):
        """
        `show_result` решает, разошлась ли отметка по классу, и журнал не
        может быть дверью в обход него: зелёная галочка у соседа — это и есть
        ответ, разошедшийся по классу.
        """
        self.graded(self.student, 5, show_result=False)

        self.client.force_authenticate(self.student)
        body = self.client.get(
            reverse("student-journal"), {"course": self.course.pk}
        ).json()

        self.assertEqual(body["students"][0]["cells"][0]["marks"], [])

    def test_the_teacher_sees_it_anyway(self):
        """Он её и поставил: прятать от него собственную отметку незачем."""
        self.graded(self.student, 5, show_result=False)

        self.client.force_authenticate(self.user)
        body = self.client.get(
            reverse("course-journal"), {"course": self.course.pk}
        ).json()
        mine = next(row for row in body["students"] if row["id"] == self.student.pk)

        self.assertEqual([mark["label"] for mark in mine["cells"][0]["marks"]], ["5"])

    def test_a_course_the_child_does_not_study_does_not_exist(self):
        other = make_course(self.school, self.year, name="10А")

        self.client.force_authenticate(self.student)
        answer = self.client.get(reverse("student-journal"), {"course": other.pk})

        self.assertEqual(answer.status_code, 404)


class CurrentTermTests(SchoolTestMixin, APITestCase):
    """
    Какой терм открывается сам.

    Каникулы не входят ни в один терм, и «сегодня ни в одном» — обычное
    состояние, а не край. Пустой экран в этот день был бы неправдой о курсе:
    четверть кончилась, а оценки за неё никуда не делись.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.first = make_term(
            self.year, "1 четверть", start=date(2026, 9, 1), end=date(2026, 10, 25)
        )
        self.second = make_term(
            self.year, "2 четверть", start=date(2026, 11, 5), end=date(2026, 12, 28)
        )

    def test_the_term_of_today_wins(self):
        from .journal import current_term

        chosen = current_term([self.first, self.second], date(2026, 11, 20))

        self.assertEqual(chosen, self.second)

    def test_the_holidays_open_the_term_that_just_ended(self):
        from .journal import current_term

        chosen = current_term([self.first, self.second], date(2026, 10, 30))

        self.assertEqual(chosen, self.first)

    def test_before_the_year_starts_the_first_one_opens(self):
        from .journal import current_term

        chosen = current_term([self.first, self.second], date(2026, 8, 20))

        self.assertEqual(chosen, self.first)

    def test_a_year_without_terms_shows_everything(self):
        from .journal import current_term

        self.assertIsNone(current_term([], date(2026, 9, 1)))
