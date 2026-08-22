"""
Долги по записи: прошедшие занятия, за которыми ничего не сказано.

Долг появляется только у того, кто начал записывать: учителю, который
кнопкой не пользуется, каждый прошедший час был бы долгом, а первое же
нажатие потребовало бы закрыть полгода. До начала учёта работает
позиционная догадка, как работала всегда.

Срока давности у долга нет. Две недели тут были — «через две недели человек
честно не помнит, что было во вторник третьим уроком», — и отменены вместе
с введением строгого порядка: очередь без дырок незакрытый час всё равно не
пропустит, а стареющий долг просто исчезал бы с экрана, продолжая держать
курс.

Закрывается долг пачкой, но с подставленными темами на экране.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from schools.testing import (
    SchoolTestMixin,
    assign,
    make_course,
    make_node,
    make_slot,
    make_year,
)

from .models import Slot


class DebtTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.year = make_year(
            self.school,
            start=self.today - timedelta(days=200),
            end=self.today + timedelta(days=100),
        )
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        assign(self.user, self.course)
        self.first = make_node(self.user, self.course, "Синус суммы", position=0)
        self.second = make_node(self.user, self.course, "Косинус суммы", position=1)

    def slot_on(self, days_ago, number=1, course=None):
        return make_slot(
            self.user,
            course or self.course,
            self.today - timedelta(days=days_ago),
            number,
        )

    def debts(self):
        return self.client.get(reverse("slot-unclosed")).json()["slots"]

    def records(self, course=None):
        from plans import progress

        rows = progress.rows_for(progress.own_courses(self.user), self.today)
        return next(row for row in rows if row["id"] == (course or self.course).pk)[
            "records"
        ]


class CountingTests(DebtTestCase):
    def test_nobody_owes_anything_before_the_first_record(self):
        """
        Кто кнопкой не пользуется, ничего не должен.

        Иначе главная орала бы на человека, которому вся эта механика не
        нужна: каждый прошедший час был бы «долгом».
        """
        self.slot_on(3)
        self.slot_on(2, number=2)

        self.assertEqual(self.records()["unclosed"], 0)
        self.assertEqual(self.debts(), [])

    def test_once_recording_started_the_gaps_are_counted(self):
        done = self.slot_on(3)
        done.lesson = self.first
        done.save(update_fields=["lesson"])
        self.slot_on(2, number=2)

        self.assertEqual(self.records()["unclosed"], 1)
        self.assertEqual(len(self.debts()), 1)

    def test_an_old_gap_does_not_expire(self):
        """
        Срока давности у долга нет — и это пересмотр прежнего решения.

        Две недели тут были: старое переставало считаться и досчитывалось
        позиционно, чтобы настойчивость не догоняла человека через месяц.
        Отменено вместе со строгим порядком: при нём дырка не протухает, а
        блокирует следующую запись, и амнистия означала бы навсегда закрытую
        очередь.

        Настойчивости при этом не прибавилось: долги видно в таблице плана,
        куда приходят сами, а не полосой на дороге.
        """
        done = self.slot_on(30)
        done.lesson = self.first
        done.save(update_fields=["lesson"])
        self.slot_on(20, number=2)

        self.assertEqual(self.records()["unclosed"], 1)
        self.assertEqual(len(self.debts()), 1)

    def test_the_future_owes_nothing(self):
        done = self.slot_on(3)
        done.lesson = self.first
        done.save(update_fields=["lesson"])
        make_slot(self.user, self.course, self.today + timedelta(days=2), 3)

        self.assertEqual(self.records()["unclosed"], 0)

    def test_a_cancelled_lesson_is_not_a_debt(self):
        """Про него уже сказали: его не было."""
        done = self.slot_on(3)
        done.lesson = self.first
        done.save(update_fields=["lesson"])
        skipped = self.slot_on(2, number=2)
        skipped.is_cancelled = True
        skipped.save(update_fields=["is_cancelled"])

        self.assertEqual(self.records()["unclosed"], 0)

    def test_the_share_of_confirmed_is_named_out_loud(self):
        """Любое число по связям сопровождается тем, на чём оно посчитано."""
        done = self.slot_on(3)
        done.lesson = self.first
        done.save(update_fields=["lesson"])
        self.slot_on(2, number=2)

        self.assertEqual(self.records(), {"held": 2, "confirmed": 1, "unclosed": 1})


class ListTests(DebtTestCase):
    def setUp(self):
        super().setUp()
        done = self.slot_on(4)
        done.lesson = self.first
        done.save(update_fields=["lesson"])
        self.owed = self.slot_on(2, number=2)

    def test_the_topic_is_suggested_for_every_gap(self):
        row = self.debts()[0]

        self.assertEqual(row["id"], self.owed.pk)
        self.assertEqual(row["topic"]["title"], "Косинус суммы")
        self.assertEqual(row["course"]["name"], "9Б Алгебра")

    def test_somebody_elses_course_is_not_my_debt(self):
        theirs = make_course(self.school, self.year, "11А Алгебра")
        assign(self.colleague, theirs)
        node = make_node(self.colleague, theirs, "Чужая тема")
        slot = make_slot(self.colleague, theirs, self.today - timedelta(days=4), 5)
        slot.lesson = node
        slot.save(update_fields=["lesson"])
        make_slot(self.colleague, theirs, self.today - timedelta(days=2), 6)

        self.assertEqual([row["id"] for row in self.debts()], [self.owed.pk])


class ClosingTests(DebtTestCase):
    def setUp(self):
        super().setUp()
        self.owed = self.slot_on(2)
        self.also = self.slot_on(1, number=2)

    def close(self, closed):
        return self.client.post(
            reverse("slot-close"), {"closed": closed}, format="json"
        )

    def test_a_batch_records_what_was_covered(self):
        response = self.close(
            [
                {"slot": self.owed.pk, "lesson": self.first.pk},
                {"slot": self.also.pk, "lesson": self.second.pk},
            ]
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.owed.refresh_from_db()
        self.also.refresh_from_db()
        self.assertEqual(self.owed.lesson, self.first)
        self.assertEqual(self.also.lesson, self.second)

    def test_a_lesson_that_did_not_happen_is_cancelled_with_a_reason(self):
        self.close([{"slot": self.owed.pk, "cancelled": True, "reason": "болел"}])

        self.owed.refresh_from_db()
        self.assertTrue(self.owed.is_cancelled)
        self.assertEqual(self.owed.reason, "болел")
        self.assertIsNone(self.owed.lesson_id)

    def test_nothing_is_written_when_one_row_is_wrong(self):
        """Половина закрытого списка хуже незакрытого: непонятно, какая."""
        theirs = make_course(self.school, self.year, "11А Алгебра")
        assign(self.colleague, theirs)
        alien = make_node(self.colleague, theirs, "Чужая тема")

        response = self.close(
            [
                {"slot": self.owed.pk, "lesson": self.first.pk},
                {"slot": self.also.pk, "lesson": alien.pk},
            ]
        )

        self.assertEqual(response.status_code, 400)
        self.owed.refresh_from_db()
        self.assertIsNone(self.owed.lesson_id)

    def test_a_slot_of_another_teacher_is_refused(self):
        theirs = make_course(self.school, self.year, "11А Алгебра")
        assign(self.colleague, theirs)
        slot = make_slot(self.colleague, theirs, self.today - timedelta(days=1), 7)

        response = self.close([{"slot": slot.pk, "lesson": self.first.pk}])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "slot_not_mine")

    def test_the_debt_disappears_once_it_is_closed(self):
        self.close([{"slot": self.owed.pk, "lesson": self.first.pk}])

        self.assertEqual([row["id"] for row in self.debts()], [self.also.pk])

    def test_an_empty_batch_is_refused(self):
        self.assertEqual(self.close([]).status_code, 400)

    def test_a_student_has_no_debts_at_all(self):
        self.sign_in(self.student)

        response = self.client.get(reverse("slot-unclosed"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "teachers_only")


class MethodistTests(DebtTestCase):
    """
    Методисту долги не показываются, и это не мелочь.

    У него уже есть строка курса с расхождением и темпом. Число «не отметил
    двенадцать занятий» — про дисциплину заполнения, а не про курс, и как
    только оно попадёт в чужой обзор, кнопку начнут нажимать не читая. Тогда
    мы получим худшее из возможного: поле, которое выглядит фактом и
    заполнено формально.
    """

    def test_the_review_rows_carry_no_debts(self):
        from schedule.models import CourseMethodist

        CourseMethodist.objects.create(
            course=self.course, user=self.colleague, assigned_by=self.admin
        )
        done = self.slot_on(3)
        done.lesson = self.first
        done.save(update_fields=["lesson"])
        self.slot_on(2, number=2)

        self.sign_in(self.colleague)
        rows = self.client.get(reverse("planreview-list")).json()["plans"]

        row = next(item for item in rows if item["id"] == self.course.pk)
        self.assertNotIn("records", row)
