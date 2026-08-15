"""
Посещаемость: первая таблица, которая по-настоящему висит на занятии.

У остальных на нём одно поле, а здесь строка на человека — и отсюда все
решения. Главное из них: **строка заводится по требованию**. Пока никого не
отметили, строк нет, и «не отмечено» отличается от «отсутствовал» тем, что
первого просто нет в базе. Различать их обязательно: пустой журнал и журнал,
где не было всего класса, — разные вещи.
"""

from datetime import timedelta

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.services import enrol
from schools.testing import (
    MONDAY,
    SchoolTestMixin,
    assign,
    make_course,
    make_slot,
    make_user,
    make_year,
)

from .models import Attendance, CourseStudent, Slot


class AttendanceTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        assign(self.user, self.course)
        self.slot = make_slot(self.user, self.course, MONDAY, 1)

        self.second = make_user(self.school, "second@example.com", student=True)
        enrol(self.student, self.course, by=self.admin)
        enrol(self.second, self.course, by=self.admin)

    def url(self, slot=None):
        return reverse("slot-attendance", args=[(slot or self.slot).pk])

    def read(self):
        return self.client.get(self.url()).json()["students"]

    def mark(self, marks, slot=None):
        return self.client.post(self.url(slot), {"marks": marks}, format="json")


class RosterTests(AttendanceTestCase):
    def test_the_list_comes_from_the_course_not_from_the_marks(self):
        """До первой отметки строк нет, а список уже есть."""
        rows = self.read()

        self.assertEqual(len(rows), 2)
        self.assertEqual([row["status"] for row in rows], [None, None])
        self.assertEqual(Attendance.objects.count(), 0)

    def test_unmarked_is_not_the_same_as_absent(self):
        self.mark([{"student": self.student.pk, "status": "absent"}])

        rows = {row["id"]: row["status"] for row in self.read()}

        self.assertEqual(rows[self.student.pk], "absent")
        self.assertIsNone(rows[self.second.pk])

    def test_a_student_removed_from_the_course_stays_and_is_flagged(self):
        """
        «Не был» и «уже не учится» — разные ответы, и смешивать их нельзя.

        Отметка за прошлое занятие при этом настоящая: человек тогда был.
        """
        CourseStudent.objects.filter(course=self.course, student=self.second).update(
            removed_at="2026-10-01T00:00:00Z"
        )

        rows = {row["id"]: row["active"] for row in self.read()}

        self.assertTrue(rows[self.student.pk])
        self.assertFalse(rows[self.second.pk])


class MarkingTests(AttendanceTestCase):
    def test_a_batch_is_written_at_once(self):
        response = self.mark(
            [
                {"student": self.student.pk, "status": "present"},
                {"student": self.second.pk, "status": "late", "note": "автобус"},
            ]
        )

        self.assertEqual(response.status_code, 200, response.content)
        rows = {row.student_id: row for row in Attendance.objects.all()}
        self.assertEqual(rows[self.student.pk].status, "present")
        self.assertEqual(rows[self.second.pk].status, "late")
        self.assertEqual(rows[self.second.pk].note, "автобус")

    def test_marking_twice_does_not_double_the_row(self):
        self.mark([{"student": self.student.pk, "status": "present"}])
        self.mark([{"student": self.student.pk, "status": "absent"}])

        row = Attendance.objects.get()
        self.assertEqual(row.status, "absent")

    def test_null_removes_the_mark_instead_of_storing_it(self):
        """«Не отмечено» — это отсутствие строки, а не третье значение."""
        self.mark([{"student": self.student.pk, "status": "present"}])

        self.mark([{"student": self.student.pk, "status": None}])

        self.assertEqual(Attendance.objects.count(), 0)
        self.assertIsNone(self.read()[0]["status"])

    def test_who_marked_is_remembered(self):
        self.mark([{"student": self.student.pk, "status": "present"}])

        self.assertEqual(Attendance.objects.get().marked_by, self.user)

    def test_somebody_from_another_course_cannot_be_marked(self):
        outsider = make_user(self.school, "outsider@example.com", student=True)

        response = self.mark([{"student": outsider.pk, "status": "present"}])

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Attendance.objects.exists())

    def test_an_unknown_status_is_refused(self):
        response = self.mark([{"student": self.student.pk, "status": "болел"}])

        self.assertEqual(response.status_code, 400)


class AccessTests(AttendanceTestCase):
    def test_a_colleague_may_read_but_not_mark(self):
        """Расписание общее, а журнал ведёт тот, кто вёл занятие."""
        self.sign_in(self.colleague)

        self.assertEqual(self.client.get(self.url()).status_code, 200)
        self.assertEqual(
            self.mark([{"student": self.student.pk, "status": "present"}]).status_code,
            403,
        )

    def test_an_administrator_may_mark(self):
        self.sign_in(self.admin)

        self.assertEqual(
            self.mark([{"student": self.student.pk, "status": "present"}]).status_code,
            200,
        )

    def test_a_student_gets_nothing(self):
        self.sign_in(self.student)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "teachers_only")

    def test_a_lesson_of_another_school_is_not_found(self):
        alien_course = make_course(self.alien_school, name="Чужой")
        alien = make_slot(self.alien_admin, alien_course, MONDAY, 1)

        self.assertEqual(self.client.get(self.url(alien)).status_code, 404)


class SweepTests(AttendanceTestCase):
    """
    Занятие с журналом переживает массовую чистку — **само**.

    `Slot.empty_conditions` считает записью любую обратную связь, и
    посещаемость попала под защиту в тот день, когда её завели, а не когда
    кто-то вспомнил дописать её в список. Ради этого условие и переписали.
    """

    def test_a_lesson_with_a_journal_is_not_swept(self):
        self.mark([{"student": self.student.pk, "status": "present"}])

        self.client.delete(
            f"{reverse('slot-bulk')}?course={self.course.pk}"
            f"&start={MONDAY}&end={MONDAY + timedelta(days=6)}&only_regular=true"
        )

        self.assertTrue(Slot.objects.filter(pk=self.slot.pk).exists())

    def test_an_empty_lesson_is_still_swept(self):
        self.client.delete(
            f"{reverse('slot-bulk')}?course={self.course.pk}"
            f"&start={MONDAY}&end={MONDAY + timedelta(days=6)}&only_regular=true"
        )

        self.assertFalse(Slot.objects.filter(pk=self.slot.pk).exists())

    def test_deleting_the_lesson_takes_the_journal_with_it(self):
        """Журнал существует ради занятия и без него не значит ничего."""
        self.mark([{"student": self.student.pk, "status": "present"}])

        self.slot.delete()

        self.assertEqual(Attendance.objects.count(), 0)
