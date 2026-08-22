"""
Курс глазами ученика: учебный план с датами.

Проверяется здесь ровно то, из-за чего этот экран и опасно было делать
раньше: **план у курса один**. Пока он был личным, «учебный план курса» не
имел определения — у двух ведущих было два разных, и ученику пришлось бы
показывать чей-то один, не умея объяснить чей.

Второе — граница показа: ученик видит названия и даты, но не содержание.
Цели, ход урока, домашнее задание и вложения остаются учительскими, и
проглядеть это легко: они лежат в тех же строках.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from schedule.models import Slot
from schools.services import enrol, remove_from_course
from schools.testing import (
    MONDAY,
    SchoolTestMixin,
    assign,
    make_course,
    make_node,
    make_year,
)

from .models import PlanNode


class StudentCourseTestCase(SchoolTestMixin, APITestCase):
    """Курс с планом из двух тем, расписанием и зачисленным учеником."""

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year, name="9Б Алгебра")
        assign(self.user, self.course)

        trig = make_node(self.user, self.course, "Тригонометрия", section=True)
        make_node(self.user, self.course, "Синус суммы", parent=trig, position=0)
        make_node(self.user, self.course, "Косинус суммы", parent=trig, position=1)
        make_node(self.user, self.course, "Повторение", position=1)

        self.enrolment = enrol(self.student, self.course, by=self.admin)
        self.sign_in(self.student)

    def lessons(self, count, start=MONDAY):
        for index in range(count):
            Slot.objects.create(
                year=self.year,
                course=self.course,
                date=start + timedelta(days=index),
                lesson_number=1,
            )

    def open(self, course=None):
        return self.client.get(
            reverse("student-course", args=[(course or self.course).pk])
        )


class ContentTests(StudentCourseTestCase):
    def test_the_plan_comes_in_display_order_with_its_sections(self):
        body = self.open().json()

        self.assertEqual(
            [(row["is_section"], row["title"]) for row in body["lessons"]],
            [
                (True, "Тригонометрия"),
                (False, "Синус суммы"),
                (False, "Косинус суммы"),
                (False, "Повторение"),
            ],
        )

    def test_lessons_carry_the_dates_the_teacher_sees(self):
        """
        Раскладка одна на всех: план принадлежит курсу, слоты берутся по
        курсу, и второго ответа про «когда это будет» просто нет.
        """
        self.lessons(3)

        rows = [row for row in self.open().json()["lessons"] if not row["is_section"]]

        self.assertEqual(
            [(row["number"], str(row["date"])) for row in rows[:3]],
            [(1, "2026-09-07"), (2, "2026-09-08"), (3, "2026-09-09")],
        )

    def test_a_lesson_without_a_slot_simply_has_no_date(self):
        """«Не помещается в год» — разговор учителя с методистом, не с ним."""
        self.lessons(2)

        rows = [row for row in self.open().json()["lessons"] if not row["is_section"]]

        self.assertEqual(str(rows[1]["date"]), "2026-09-08")
        self.assertIsNone(rows[2]["date"])

    def test_past_lessons_are_marked(self):
        self.lessons(2, start=timezone.localdate() - timedelta(days=1))

        rows = [row for row in self.open().json()["lessons"] if not row["is_section"]]

        self.assertTrue(rows[0]["past"])
        self.assertFalse(rows[1]["past"])

    def test_the_content_of_a_lesson_never_leaves_the_teacher(self):
        """Показываем название и дату; цели, ход и домашнее — нет."""
        lesson = PlanNode.objects.get(title="Синус суммы")
        lesson.objectives = "Секретные цели MYP"
        lesson.homework = "Параграф 12"
        lesson.save(update_fields=["objectives", "homework"])

        payload = self.client.get(
            reverse("student-course", args=[self.course.pk])
        ).content.decode()

        self.assertNotIn("Секретные цели", payload)
        self.assertNotIn("Параграф 12", payload)

    def test_the_card_names_the_lead_teacher(self):
        self.assertEqual(self.open().json()["course"]["teacher"], self.user.email)

    def test_a_course_nobody_leads_says_so_with_a_null(self):
        self.course.assignments.all().delete()

        self.assertIsNone(self.open().json()["course"]["teacher"])


class AccessTests(StudentCourseTestCase):
    def test_a_course_i_was_removed_from_is_still_readable(self):
        """
        Строка зачисления и есть право читать сделанное — она не удаляется.

        Курс уезжает вниз и теряет кнопки, но план в нём остаётся открытым:
        год, который человек отучился, не должен пропадать с экрана.
        """
        remove_from_course(self.enrolment)

        body = self.open()

        self.assertEqual(body.status_code, 200)
        self.assertFalse(body.json()["course"]["active"])

    def test_a_course_i_was_never_on_is_not_found(self):
        other = make_course(self.school, self.year, name="9Б Геометрия")

        self.assertEqual(self.open(other).status_code, 404)

    def test_a_course_of_another_school_is_not_found(self):
        alien = make_course(self.alien_school, name="Чужой")

        self.assertEqual(self.open(alien).status_code, 404)

    def test_a_teacher_has_no_student_view_of_the_course(self):
        self.sign_in(self.user)

        response = self.open()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "students_only")
