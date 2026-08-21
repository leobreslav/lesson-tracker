"""
След ученика и пометка «эту задачу он уже решал».

Проверяется главное: след собирается **по условиям**, а не по работам, —
задача, спрошенная трижды, это одна строка с тремя встречами. И что ученику
видно, что задача не новая, но **не видно старого ответа**: повторный вопрос
задают, чтобы посмотреть, как человек решает сейчас.
"""

from bank.models import Problem
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from schedule.models import CourseStudent
from schools.testing import (
    SchoolTestMixin,
    assign,
    make_course,
    make_user,
    make_work,
)

from . import services, track
from .models import Submission, Task


class TrackTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.course = make_course(self.school)
        assign(self.user, self.course)
        self.student = make_user(self.school, "uchenik@example.com", student=True)
        CourseStudent.objects.create(course=self.course, student=self.student)

        self.problem = Problem.objects.create(
            text="$x^2 = 4$", school=self.school, owner=self.user, created_by=self.user
        )
        self.autumn = self.asked("Осенняя", "2")
        self.spring = self.asked("Весенняя", "±2")

    def asked(self, title, answer):
        """Работа, где это условие спросили и ученик ответил."""
        work = make_work(self.user, self.course, title=title)
        task = Task.objects.create(work=work, position=0, problem=self.problem)
        Submission.objects.create(task=task, student=self.student, answer=answer)
        return work

    def test_the_track_is_gathered_by_problems_and_not_by_works(self):
        rows = track.track(self.student)

        # одно условие, две встречи — а не две строки
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["times"], 2)
        self.assertEqual(
            sorted(one["title"] for one in rows[0]["works"]),
            ["Весенняя", "Осенняя"],
        )
        self.assertEqual(track.summary(rows)["repeated"], 1)

    def test_a_teacher_sees_only_his_own_courses_in_it(self):
        other = make_course(self.school, year=self.course.year, name="Чужой")
        assign(self.colleague, other)
        CourseStudent.objects.create(course=other, student=self.student)
        alien = make_work(self.colleague, other, title="Чужая работа")
        Submission.objects.create(
            task=Task.objects.create(work=alien, position=0, problem=self.problem),
            student=self.student,
            answer="…",
        )

        self.client.force_authenticate(self.user)
        answer = self.client.get(reverse("student-track", args=[self.student.pk]))
        titles = {one["title"] for row in answer.data["track"] for one in row["works"]}

        self.assertNotIn("Чужая работа", titles)

    def test_a_student_sees_his_own_track_and_nobody_elses(self):
        self.client.force_authenticate(self.student)
        mine = self.client.get(reverse("student-track", args=[self.student.pk]))
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(mine.data["summary"]["problems"], 1)

        other = make_user(self.school, "sosed@example.com", student=True)
        alien = self.client.get(reverse("student-track", args=[other.pk]))
        self.assertEqual(alien.status_code, 404)

    def test_the_table_marks_the_cells_he_has_met_before(self):
        table = services.build_table(self.spring)
        row = next(one for one in table["students"] if one["id"] == self.student.pk)

        # в весенней работе видно, что осенью он это уже решал
        self.assertEqual(row["cells"][0]["seen_before"], 1)

    def test_the_student_is_told_the_fact_but_not_his_old_answer(self):
        self.spring.opens_at = timezone.now() - timezone.timedelta(hours=1)
        self.spring.save(update_fields=["opens_at"])

        self.client.force_authenticate(self.student)
        answer = self.client.get(reverse("student-work", args=[self.spring.pk]))
        seen = answer.data["tasks"][0]["seen_before"]

        self.assertEqual([one["title"] for one in seen], ["Осенняя"])
        # сам ответ в этот список не попадает: он живёт в той работе, и
        # показывается там по её собственным правилам. Повторный вопрос задают,
        # чтобы посмотреть, как человек решает сейчас, — а не как решил тогда.
        self.assertEqual(
            sorted(seen[0]),
            ["attempts", "closed", "course", "title", "was_right", "when", "work"],
        )
