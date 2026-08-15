"""
Экран «Сегодня»: один урок со всем, что к нему относится.

День учителя выглядит так: выбрал класс, попал в текущий урок, ведёт его
глядя в план, объявляет практику, задаёт домашнее. Ответ этого эндпоинта —
ровно этот экран, и своего расчёта в нём нет ни одного: содержание из плана,
подсказка из раскладки, работы из своих же связей.

Проверяется главным образом одно: **записанное сильнее подсказанного**.
Раскладка позиционная и съезжает от любой правки плана, а отметка «прошли»
держится за дату — иначе история переписывалась бы задним числом.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from schools.testing import (
    MONDAY,
    SchoolTestMixin,
    assign,
    make_course,
    make_node,
    make_slot,
    make_work,
    make_year,
)


class DayTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        assign(self.user, self.course)

        self.first = make_node(self.user, self.course, "Синус суммы", position=0)
        self.second = make_node(self.user, self.course, "Косинус суммы", position=1)

        self.monday = make_slot(self.user, self.course, MONDAY, 1)
        self.tuesday = make_slot(self.user, self.course, MONDAY + timedelta(days=1), 1)

    def day(self, when=None, course=None):
        return self.client.get(
            reverse("slot-day"),
            {"course": (course or self.course).pk, "date": (when or MONDAY).isoformat()},
        )


class TopicTests(DayTestCase):
    def test_the_layout_suggests_what_is_being_covered(self):
        body = self.day().json()

        lesson = body["lessons"][0]
        self.assertEqual(lesson["topic"]["title"], "Синус суммы")
        self.assertFalse(lesson["confirmed"], "подсказка — ещё не запись")

    def test_a_recorded_topic_wins_over_the_suggestion(self):
        self.monday.lesson = self.second
        self.monday.save(update_fields=["lesson"])

        lesson = self.day().json()["lessons"][0]

        self.assertEqual(lesson["topic"]["title"], "Косинус суммы")
        self.assertTrue(lesson["confirmed"])

    def insert_first(self):
        """Урок в начало плана: остальные сдвигаются, как это делает `place`."""
        for node, position in ((self.first, 1), (self.second, 2)):
            node.position = position
            node.save(update_fields=["position"])

        return make_node(self.user, self.course, "Вводный", position=0)

    def test_a_recorded_topic_does_not_move_when_the_plan_does(self):
        """
        Ради этого «что прошли» и записывается: раскладка позиционная, и
        вставленный в начало урок сдвинул бы всю ленту вместе с историей.
        """
        self.monday.lesson = self.first
        self.monday.save(update_fields=["lesson"])
        self.insert_first()

        self.assertEqual(self.day().json()["lessons"][0]["topic"]["title"], "Синус суммы")

    def test_the_suggestion_does_move(self):
        """И это честно: подсказка — свойство сегодняшней раскладки."""
        self.insert_first()

        self.assertEqual(self.day().json()["lessons"][0]["topic"]["title"], "Вводный")

    def test_the_content_of_the_plan_comes_along(self):
        self.first.objectives = "Понять формулу"
        self.first.homework = "Параграф 12"
        self.first.save(update_fields=["objectives", "homework"])

        topic = self.day().json()["lessons"][0]["topic"]

        self.assertEqual(topic["objectives"], "Понять формулу")
        self.assertEqual(topic["homework"], "Параграф 12")

    def test_a_day_with_no_lesson_is_empty_and_says_where_the_next_one_is(self):
        body = self.day(MONDAY + timedelta(days=4)).json()

        self.assertEqual(body["lessons"], [])
        self.assertEqual(body["previous"], str(MONDAY + timedelta(days=1)))
        self.assertIsNone(body["next"])

    def test_it_leafs_through_the_days_that_have_lessons(self):
        body = self.day().json()

        self.assertIsNone(body["previous"])
        self.assertEqual(body["next"], str(MONDAY + timedelta(days=1)))


class WorkTests(DayTestCase):
    def test_the_works_of_this_lesson_are_listed(self):
        mine = make_work(self.user, self.course, title="Практика", slot=self.monday)
        make_work(self.user, self.course, title="Чужая", slot=self.tuesday)

        works = self.day().json()["lessons"][0]["works"]

        self.assertEqual([item["title"] for item in works], ["Практика"])
        self.assertEqual(works[0]["id"], mine.pk)

    def test_a_work_with_no_lesson_belongs_to_no_day(self):
        make_work(self.user, self.course, title="Четвертная")

        self.assertEqual(self.day().json()["lessons"][0]["works"], [])


class AccessTests(DayTestCase):
    def test_a_course_of_another_school_is_not_found(self):
        alien = make_course(self.alien_school, name="Чужой")

        self.assertEqual(self.day(course=alien).status_code, 404)

    def test_a_colleague_of_the_same_school_may_look(self):
        """Расписание общее: по нему живут все, и день курса — его часть."""
        self.sign_in(self.colleague)

        self.assertEqual(self.day().status_code, 200)

    def test_a_student_has_no_teachers_day(self):
        self.sign_in(self.student)

        response = self.day()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "teachers_only")

    def test_without_a_date_it_answers_about_today(self):
        response = self.client.get(reverse("slot-day"), {"course": self.course.pk})

        self.assertEqual(response.json()["date"], str(timezone.localdate()))
