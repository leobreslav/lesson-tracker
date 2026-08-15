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


class WholeDayTests(DayTestCase):
    """
    Без курса — весь день целиком, все занятия подряд.

    Утро начинается с вопроса «что у меня сегодня», а это четыре занятия
    трёх разных курсов. Экран, устроенный курсом вперёд, заставлял бы
    переключать их по одному и каждый раз вспоминать, где ты; вечером, когда
    закрывают день, то же самое ещё и умножается на число курсов.
    """

    def setUp(self):
        super().setUp()
        self.other = make_course(self.school, self.year, "8А Геометрия")
        assign(self.user, self.other)
        self.their_slot = make_slot(self.user, self.other, MONDAY, 2)

    def whole(self, when=None):
        return self.client.get(
            reverse("slot-day"), {"date": (when or MONDAY).isoformat()}
        ).json()

    def test_the_day_holds_every_course(self):
        numbers = [
            (item["lesson_number"], item["course"]["name"])
            for item in self.whole()["lessons"]
        ]

        self.assertEqual(numbers, [(1, "9Б Алгебра"), (2, "8А Геометрия")])

    def test_each_lesson_says_whose_course_it_is(self):
        """Иначе четыре карточки подряд неразличимы."""
        first = self.whole()["lessons"][0]

        self.assertEqual(first["course"]["id"], self.course.pk)

    def test_the_topic_is_suggested_for_every_course_at_once(self):
        make_node(self.user, self.other, "Признаки равенства", position=0)

        topics = {
            item["course"]["name"]: item["topic"]["title"]
            for item in self.whole()["lessons"]
        }

        self.assertEqual(topics["9Б Алгебра"], "Синус суммы")
        self.assertEqual(topics["8А Геометрия"], "Признаки равенства")

    def test_leafing_goes_by_days_that_have_anything_at_all(self):
        """Пустой день пропускается, чей бы курс ни стоял следующим."""
        far = make_course(self.school, self.year, "7В Алгебра")
        assign(self.user, far)
        make_slot(self.user, far, MONDAY + timedelta(days=3), 1)

        self.assertEqual(
            self.whole(MONDAY + timedelta(days=1))["next"],
            str(MONDAY + timedelta(days=3)),
        )

    def test_a_course_of_somebody_else_is_not_in_my_day(self):
        alien = make_course(self.school, self.year, "11А Алгебра")
        assign(self.colleague, alien)
        make_slot(self.colleague, alien, MONDAY, 5)

        names = {item["course"]["name"] for item in self.whole()["lessons"]}

        self.assertNotIn("11А Алгебра", names)

    def test_asking_about_one_course_still_narrows_it(self):
        body = self.client.get(
            reverse("slot-day"),
            {"course": self.course.pk, "date": MONDAY.isoformat()},
        ).json()

        self.assertEqual(
            [item["course"]["name"] for item in body["lessons"]], ["9Б Алгебра"]
        )


class CardTests(DayTestCase):
    """
    Экран работы с уроком: одно занятие целиком.

    Отличается от дня двумя вещами, и обе — про то, о чём человек думает,
    когда сюда пришёл. Соседи здесь **по курсу**, а не по дню: «что было на
    прошлом» это вопрос про этот же класс, а не про то, что стояло
    следующим часом у другого. И право на правку приезжает ответом, потому
    что правило сложнее роли: ведущий курса или администратор школы.
    """

    def card(self, slot=None):
        return self.client.get(reverse("slot-card", args=[(slot or self.monday).pk]))

    def test_the_card_carries_the_topic_and_the_day(self):
        body = self.card().json()

        self.assertEqual(body["topic"]["title"], "Синус суммы")
        self.assertEqual(body["date"], str(MONDAY))
        self.assertEqual(body["lesson_number"], 1)
        self.assertEqual(body["course"]["name"], "9Б Алгебра")

    def test_neighbours_are_of_the_same_course(self):
        """Листаем по своему классу: чужой час рядом ничего не объясняет."""
        other = make_course(self.school, self.year, "8А Геометрия")
        assign(self.user, other)
        make_slot(self.user, other, MONDAY, 2)

        body = self.card().json()

        self.assertIsNone(body["previous"])
        self.assertEqual(body["next"], self.tuesday.pk)

    def test_the_neighbour_on_the_same_day_is_found_by_number(self):
        later = make_slot(self.user, self.course, MONDAY, 4)

        self.assertEqual(self.card().json()["next"], later.pk)
        self.assertEqual(self.card(later).json()["previous"], self.monday.pk)

    def test_a_recorded_topic_wins_here_too(self):
        self.monday.lesson = self.second
        self.monday.save(update_fields=["lesson"])

        body = self.card().json()

        self.assertEqual(body["topic"]["title"], "Косинус суммы")
        self.assertTrue(body["confirmed"])

    def test_a_colleague_may_look_but_not_write(self):
        """Расписание общее, содержимое курса — нет."""
        self.sign_in(self.colleague)

        body = self.card().json()

        self.assertEqual(body["topic"]["title"], "Синус суммы")
        self.assertFalse(body["may_write"])

    def test_the_lead_may_write(self):
        self.assertTrue(self.card().json()["may_write"])

    def test_an_administrator_may_write_too(self):
        """Расписание школы правит и он: курс не его, а час школьный."""
        self.sign_in(self.admin)

        self.assertTrue(self.card().json()["may_write"])

    def test_a_student_gets_nothing(self):
        self.sign_in(self.student)

        self.assertEqual(self.card().status_code, 403)


class OptionsTests(DayTestCase):
    """
    С каким уроком плана связать час — выбор, а не только подтверждение.

    Раскладка подсказывает один, позиционно, и в обычный день она права. Но
    необычным день бывает чаще, чем кажется: заболели и перенесли
    контрольную, вернулись к теме, поменяли порядок. Тогда нужен весь план.
    """

    def options(self, slot=None):
        return self.client.get(
            reverse("slot-card", args=[(slot or self.monday).pk])
        ).json()["options"]

    def test_the_whole_plan_is_offered_with_numbers(self):
        rows = self.options()

        self.assertEqual(
            [(row["number"], row["title"]) for row in rows],
            [(1, "Синус суммы"), (2, "Косинус суммы")],
        )

    def test_a_row_taken_by_another_hour_is_flagged_not_hidden(self):
        """Исчезнувшая из списка строка выглядит потерянной."""
        self.tuesday.lesson = self.second
        self.tuesday.save(update_fields=["lesson"])

        rows = {row["title"]: row["taken"] for row in self.options()}

        self.assertIsNone(rows["Синус суммы"])
        self.assertEqual(rows["Косинус суммы"], str(self.tuesday.date))

    def test_the_row_of_this_very_hour_is_not_taken(self):
        """Свою же связь менять можно — она не мешает сама себе."""
        self.monday.lesson = self.first
        self.monday.save(update_fields=["lesson"])

        rows = {row["title"]: row["taken"] for row in self.options()}

        self.assertIsNone(rows["Синус суммы"])

    def test_choosing_a_taken_row_is_refused_by_name_and_date(self):
        self.tuesday.lesson = self.second
        self.tuesday.save(update_fields=["lesson"])

        response = self.client.patch(
            reverse("slot-detail", args=[self.monday.pk]),
            {"lesson": self.second.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], "slot_lesson_taken")
        self.assertEqual(body["params"]["date"], str(self.tuesday.date))

    def test_any_row_of_the_plan_can_be_chosen_not_just_the_suggested_one(self):
        response = self.client.patch(
            reverse("slot-detail", args=[self.monday.pk]),
            {"lesson": self.second.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.monday.refresh_from_db()
        self.assertEqual(self.monday.lesson, self.second)
