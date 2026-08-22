"""
Карточка занятия: один урок со всем, что к нему относится.

Учитель заходит в занятие из расписания и ведёт его глядя в план, объявляет
практику, задаёт домашнее. Ответ `card` — ровно этот экран, и своего расчёта
в нём нет ни одного: содержание из плана, подсказка из раскладки, работы из
своих же связей.

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
    live_year,
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

    def lesson(self, slot=None):
        """Карточка занятия. Экрана «день целиком» больше нет: в занятие
        заходят из расписания, и день там виден сеткой."""
        return self.client.get(
            reverse("slot-card", args=[(slot or self.monday).pk])
        ).json()


class TopicTests(DayTestCase):
    def test_the_layout_suggests_what_is_being_covered(self):
        lesson = self.lesson()

        self.assertEqual(lesson["topic"]["title"], "Синус суммы")
        self.assertFalse(lesson["confirmed"], "подсказка — ещё не запись")

    def test_a_recorded_topic_wins_over_the_suggestion(self):
        self.monday.lesson = self.second
        self.monday.save(update_fields=["lesson"])

        lesson = self.lesson()

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

        self.assertEqual(self.lesson()["topic"]["title"], "Синус суммы")

    def test_the_suggestion_does_move(self):
        """И это честно: подсказка — свойство сегодняшней раскладки."""
        self.insert_first()

        self.assertEqual(self.lesson()["topic"]["title"], "Вводный")

    def test_the_content_of_the_plan_comes_along(self):
        self.first.objectives = "Понять формулу"
        self.first.homework = "Параграф 12"
        self.first.save(update_fields=["objectives", "homework"])

        topic = self.lesson()["topic"]

        self.assertEqual(topic["objectives"], "Понять формулу")
        self.assertEqual(topic["homework"], "Параграф 12")

class WorkTests(DayTestCase):
    def test_the_works_of_this_lesson_are_listed(self):
        mine = make_work(self.user, self.course, title="Практика", slot=self.monday)
        make_work(self.user, self.course, title="Чужая", slot=self.tuesday)

        works = self.lesson()["works"]

        self.assertEqual([item["title"] for item in works], ["Практика"])
        self.assertEqual(works[0]["id"], mine.pk)

    def test_a_work_with_no_lesson_belongs_to_no_day(self):
        make_work(self.user, self.course, title="Четвертная")

        self.assertEqual(self.lesson()["works"], [])


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


class RecordingTests(DayTestCase):
    """
    Записать — значит подтвердить подсказку, а не выбрать из списка.

    Что было на уроке, решает **план**: не угадал — правят план, и подсказка
    меняется сама. Выбор из сорока строк отвечал бы на тот же вопрос мимо
    плана, не оставляя следа, что план разошёлся с реальностью, — а это ровно
    та вторая летопись, от которой мы отказались.

    Снимается запись повторным нажатием, тем же приёмом, что отметка в
    журнале и вердикт в проверке работ: без него исправить запись было бы
    нечем — «связать с другой строкой» больше не предлагается.
    """

    def setUp(self):
        """
        Свой курс на живом годе: запись идёт только по прошедшим часам.

        Общая фикстура стоит на зашитом 2026/2027, а он в будущем целиком —
        записать там нечего. Поэтому здесь год вокруг сегодня, вчера и
        позавчера, и порядок записи виден на настоящих датах.
        """
        super().setUp()
        self.year = live_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Живой")
        assign(self.user, self.course)

        self.first = make_node(self.user, self.course, "Синус суммы", position=0)
        self.second = make_node(self.user, self.course, "Косинус суммы", position=1)

        today = timezone.localdate()
        self.monday = make_slot(self.user, self.course, today - timedelta(days=2), 1)
        self.tuesday = make_slot(self.user, self.course, today - timedelta(days=1), 1)

    def card(self, slot=None):
        return self.client.get(
            reverse("slot-card", args=[(slot or self.monday).pk])
        ).json()

    def test_the_card_offers_no_choice_of_rows(self):
        self.assertNotIn("options", self.card())

    def test_the_suggestion_is_what_gets_recorded(self):
        suggested = self.card()["topic"]["id"]

        response = self.client.patch(
            reverse("slot-detail", args=[self.monday.pk]),
            {"lesson": suggested},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.monday.refresh_from_db()
        self.assertEqual(self.monday.lesson_id, suggested)
        self.assertTrue(self.card()["confirmed"])

    def test_recording_is_withdrawn_by_clearing_the_link(self):
        """Записал не то — снял, поправил план, записал заново."""
        self.monday.lesson = self.second
        self.monday.save(update_fields=["lesson"])

        response = self.client.patch(
            reverse("slot-detail", args=[self.monday.pk]),
            {"lesson": None},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.monday.refresh_from_db()
        self.assertIsNone(self.monday.lesson)

        # строка вернулась в очередь раскладки, и подсказка снова работает
        body = self.card()
        self.assertFalse(body["confirmed"])
        self.assertEqual(body["topic"]["title"], "Синус суммы")

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

    def test_only_the_suggested_row_is_accepted(self):
        """
        Строку тоже не выбирают: записывается предложенная раскладкой.

        Правило это было и раньше, но держалось тем, что в интерфейсе выбора
        негде взять; по API можно было записать любую, оставив предыдущие
        строки неиспользованными — и они молча уезжали на более поздние дни.

        Пропуск темы выражается теперь перестановкой строки в плане, то есть
        видимой правкой программы. Непроведённые строки двигаются свободно,
        так что путь остаётся.
        """
        refused = self.client.patch(
            reverse("slot-detail", args=[self.monday.pk]),
            {"lesson": self.second.pk},
            format="json",
        )

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "slot_record_not_suggested")
        self.assertEqual(refused.json()["params"]["title"], "Синус суммы")

    def test_an_hour_with_no_row_left_asks_for_one(self):
        """
        Слотов больше, чем строк: записывать нечего, и это не тупик.

        «Провели то, чего в плане нет» значит дописать строку — та же
        доктрина, что «не успели — дописывается строка». Отменять час, который
        был, нельзя: отмена это «не было».
        """
        self.client.patch(
            reverse("slot-detail", args=[self.monday.pk]),
            {"lesson": self.first.pk},
            format="json",
        )
        self.client.patch(
            reverse("slot-detail", args=[self.tuesday.pk]),
            {"lesson": self.second.pk},
            format="json",
        )
        spare = make_slot(self.user, self.course, timezone.localdate(), 2)

        refused = self.client.patch(
            reverse("slot-detail", args=[spare.pk]),
            {"lesson": self.first.pk},
            format="json",
        )


        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "slot_record_no_row")


class OrderTests(RecordingTests):
    """
    Записи идут подряд, и снять можно только последнюю.

    Дырка посреди закрытого хвоста — два разных факта в одном виде: «провёл,
    но не отметил» и «не было, а отменить забыл». Пока их не различили,
    «сколько курса пройдено» неизвестно, а это число читает методист.

    Снятие ограничено последней записью потому, что следа у него нет: у
    оценки исправление — событие (`MarkChange`), а тут поле молча
    возвращается в пустоту. Отмена последнего действия прошлого не
    переписывает; всё, что глубже, — уже переписывает.
    """

    def record(self, slot, lesson):
        return self.client.patch(
            reverse("slot-detail", args=[slot.pk]),
            {"lesson": lesson.pk if lesson else None},
            format="json",
        )

    def test_the_first_record_may_be_any_past_hour(self):
        """
        До первой записи очереди нет: система ничего и не обещала знать.

        Час любой, а строка всё равно та, что предлагает раскладка: за
        вторником по позиции стоит вторая строка.
        """
        answer = self.record(self.tuesday, self.second)

        self.assertEqual(answer.status_code, 200, answer.content)

    def test_after_the_first_one_the_order_is_strict(self):
        self.record(self.monday, self.first)
        later = make_slot(self.user, self.course, timezone.localdate(), 1)

        refused = self.record(later, self.second)

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "slot_record_out_of_order")
        # называем час, который мешает: искать его руками — не ответ
        self.assertEqual(refused.json()["params"]["date"], str(self.tuesday.date))

    def test_a_cancelled_hour_closes_itself(self):
        """«Не было» — такой же ответ, как «так и было», и очередь он двигает."""
        self.record(self.monday, self.first)
        self.client.patch(
            reverse("slot-detail", args=[self.tuesday.pk]),
            {"is_cancelled": True, "reason": "Карантин"},
            format="json",
        )
        later = make_slot(self.user, self.course, timezone.localdate(), 1)

        answer = self.record(later, self.second)

        self.assertEqual(answer.status_code, 200, answer.content)

    def test_the_future_is_not_recorded(self):
        ahead = make_slot(
            self.user, self.course, timezone.localdate() + timedelta(days=3), 1
        )

        refused = self.record(ahead, self.first)

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "slot_record_future")

    def test_only_the_last_record_is_withdrawn(self):
        self.record(self.monday, self.first)
        self.record(self.tuesday, self.second)

        refused = self.record(self.monday, None)

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "slot_record_not_last")
        self.assertEqual(refused.json()["params"]["date"], str(self.tuesday.date))

    def test_the_last_one_is_withdrawn_and_then_the_one_before(self):
        """Отматывать можно сколько угодно — по одной, с конца."""
        self.record(self.monday, self.first)
        self.record(self.tuesday, self.second)

        self.assertEqual(self.record(self.tuesday, None).status_code, 200)
        self.assertEqual(self.record(self.monday, None).status_code, 200)

    def test_an_older_record_is_not_rewritten_either(self):
        """Правка записанного — то же переписывание прошлого, что и снятие."""
        third = make_node(self.user, self.course, "Тангенс суммы", position=2)
        self.record(self.monday, self.first)
        self.record(self.tuesday, self.second)

        refused = self.record(self.monday, third)

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "slot_record_not_last")

    def test_cancelling_a_lesson_is_not_a_record_and_needs_no_order(self):
        """Очередь — про записи; отмена и причина к ней отношения не имеют."""
        answer = self.client.patch(
            reverse("slot-detail", args=[self.tuesday.pk]),
            {"is_cancelled": True, "reason": "Актированный день"},
            format="json",
        )

        self.assertEqual(answer.status_code, 200, answer.content)


class HomeworkTests(DayTestCase):
    """
    Домашняя работа — та же `Work`, просто показанная в своём разделе.

    Отличать её обязательно, и вывести отличие неоткуда: пустая домашняя и
    пустая классная в данных неразличимы, а показывать их надо в разных
    местах урока. Поэтому признак явный — как `on_paper` рядом.
    """

    def create(self, **fields):
        from django.utils import timezone

        now = timezone.now()
        return self.client.post(
            reverse("work-list"),
            {
                "course": self.course.pk,
                "slot": self.monday.pk,
                "title": "Параграф 12",
                "opens_at": (now + timedelta(days=1)).isoformat(),
                "closes_at": (now + timedelta(days=8)).isoformat(),
                **fields,
            },
            format="json",
        )

    def works_of_the_day(self):
        card = self.client.get(reverse("slot-card", args=[self.monday.pk])).json()
        return {work["title"]: work["is_homework"] for work in card["works"]}

    def test_a_work_says_whether_it_was_set_for_home(self):
        response = self.create(is_homework=True)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.works_of_the_day(), {"Параграф 12": True})

    def test_an_ordinary_work_of_the_lesson_is_not_homework(self):
        self.create(title="Практика")

        self.assertEqual(self.works_of_the_day(), {"Практика": False})

    def test_both_live_on_the_same_lesson(self):
        """Разделов на экране два, а сущность одна и та же."""
        self.create(is_homework=True)
        self.create(title="Практика")

        self.assertEqual(
            self.works_of_the_day(), {"Параграф 12": True, "Практика": False}
        )
