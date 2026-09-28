"""
Удаление ученика из курса без следа.

Проверяется три вещи, и каждая про свой способ ошибиться: что после удаления
следа действительно **нет**, что удаление не задело **чужого**, и что
необратимое действие не случается **нечаянно**.
"""

from django.urls import reverse
from rest_framework.test import APITestCase
from schedule.models import Attendance, CourseStudent
from schools.services import enrol
from schools.testing import (
    SchoolTestMixin,
    make_course,
    make_slot,
    make_task,
    make_user,
    make_work,
    make_year,
)
from works import services as work_services
from works.models import (
    Mark,
    ScanAlias,
    ScanPage,
    StudentWork,
    Submission,
    Thread,
)


class PurgeFromCourseTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.other = make_course(self.school, self.year, name="Другой курс")
        self.work = make_work(self.user, self.course)
        self.task = make_task(self.work)
        self.elsewhere = make_work(self.user, self.other)
        self.slot = make_slot(self.user, self.course, day=self.year.start_date, number=1)

        self.mate = make_user(self.school, "mate@example.com", student=True)
        self.row = enrol(self.student, self.course, by=self.admin)
        enrol(self.mate, self.course, by=self.admin)
        enrol(self.student, self.other, by=self.admin)

        self.client.force_authenticate(self.admin)

    def leave_traces(self, student, work=None, task=None):
        """Всё, что ученик оставляет в курсе: работа с оценкой, ответ, разговор."""
        work = work or self.work
        task = task or self.task
        work_services.grade(work, student, scores={task.pk: 1}, by=self.user)
        Submission.objects.create(task=task, student=student, answer="4")
        Thread.objects.create(task=task, student=student)

    def purge(self, row=None, **params):
        return self.client.delete(
            reverse("coursestudent-detail", args=[(row or self.row).pk])
            + "?"
            + "&".join(f"{name}={value}" for name, value in {"hard": "true", **params}.items())
        )

    def test_a_student_who_left_nothing_goes_at_once(self):
        """
        Называть нечего — и вопрос про ноль работ был бы ритуалом.

        Это и есть обычный случай: в курс записали не того, выгрузка принесла
        чужой список, и человек в курсе не успел ничего.
        """
        response = self.purge()

        self.assertEqual(response.status_code, 204)
        self.assertFalse(CourseStudent.objects.filter(pk=self.row.pk).exists())

    def test_what_he_left_is_named_before_it_is_taken(self):
        """
        Необратимое не случается нечаянно: первый запрос называет цену.

        Приём тот же, что у отвязки от школы и удаления курса, с одной
        разницей, ради которой у отказа свой код: там подтверждение
        **сохраняет** названное, здесь — удаляет.
        """
        self.leave_traces(self.student)
        Attendance.objects.create(slot=self.slot, student=self.student, status="absent")

        response = self.purge()

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], "enrolment_has_traces")
        self.assertEqual(
            {name: body["params"][name] for name in ("works", "answers", "threads", "attendance")},
            {"works": 1, "answers": 1, "threads": 1, "attendance": 1},
        )
        self.assertTrue(CourseStudent.objects.filter(pk=self.row.pk).exists())
        self.assertTrue(StudentWork.objects.filter(student=self.student).exists())

    def test_confirmed_it_leaves_no_trace_in_the_course(self):
        """
        После удаления в курсе нет ничего, что указывало бы на ученика.

        Оставь мы хоть одну таблицу, след остался бы в базе — а условие было
        именно в том, чтобы его не было. Проверяется каждая по отдельности:
        новая связь на ученика внутри курса обязана попасть и сюда.
        """
        self.leave_traces(self.student)
        Attendance.objects.create(slot=self.slot, student=self.student, status="absent")
        ScanAlias.objects.create(course=self.course, student=self.student, written="fil")

        response = self.purge(force="true")

        self.assertEqual(response.status_code, 204)
        inside = {"course": self.course}
        self.assertFalse(CourseStudent.objects.filter(student=self.student, **inside).exists())
        self.assertFalse(
            StudentWork.objects.filter(student=self.student, work__course=self.course).exists()
        )
        self.assertFalse(
            Mark.objects.filter(
                student_work__student=self.student, student_work__work__course=self.course
            ).exists()
        )
        self.assertFalse(
            Submission.objects.filter(
                student=self.student, task__work__course=self.course
            ).exists()
        )
        self.assertFalse(
            Thread.objects.filter(student=self.student, task__work__course=self.course).exists()
        )
        self.assertFalse(
            Attendance.objects.filter(student=self.student, slot__course=self.course).exists()
        )
        self.assertFalse(ScanAlias.objects.filter(student=self.student, **inside).exists())

    def test_the_classmate_and_the_other_course_are_untouched(self):
        """
        Удаляется след одного человека в одном курсе, и ничего сверх того.

        Сосед по курсу и тот же ученик в другом курсе — два способа снести
        лишнее одним забытым условием в выборке, и проверяются оба.
        """
        self.leave_traces(self.student)
        self.leave_traces(self.mate)
        far = make_task(self.elsewhere)
        self.leave_traces(self.student, work=self.elsewhere, task=far)

        self.purge(force="true")

        self.assertTrue(
            StudentWork.objects.filter(student=self.mate, work=self.work).exists()
        )
        self.assertTrue(Submission.objects.filter(student=self.mate).exists())
        self.assertTrue(
            StudentWork.objects.filter(student=self.student, work=self.elsewhere).exists()
        )
        self.assertTrue(
            CourseStudent.objects.filter(student=self.student, course=self.other).exists()
        )

    def test_the_account_stays(self):
        """Удаляется след в курсе, а не человек: в школе он остаётся."""
        self.purge()

        self.student.refresh_from_db()
        self.assertEqual(self.student.school_id, self.school.pk)

    def test_a_page_of_an_unsorted_pile_loses_its_owner_and_stays(self):
        """
        Страница пачки — не его, а работы: она теряет хозяина и возвращается
        человеку вопросом. Удалить её значило бы потерять лист из стопки, в
        которой лежат и чужие работы.
        """
        ScanPage.objects.create(
            work=self.work, index=0, student=self.student, decided_by_human=True
        )

        self.purge()

        page = ScanPage.objects.get(work=self.work, index=0)
        self.assertIsNone(page.student_id)
        self.assertFalse(page.decided_by_human)

    def test_a_plain_delete_still_only_takes_him_off_the_course(self):
        """
        Обычный `DELETE` снимает, как и снимал.

        Под одним адресом теперь два действия, и перепутать их нельзя:
        необратимое требует слова `hard`, а без него всё сделанное учеником
        остаётся на месте.
        """
        self.leave_traces(self.student)

        response = self.client.delete(reverse("coursestudent-detail", args=[self.row.pk]))

        self.assertEqual(response.status_code, 204)
        self.row.refresh_from_db()
        self.assertIsNotNone(self.row.removed_at)
        self.assertTrue(StudentWork.objects.filter(student=self.student).exists())

    def test_a_teacher_may_not_do_it(self):
        """Состав курса правит администратор, и удаление без следа — тем более."""
        self.client.force_authenticate(self.user)

        response = self.purge()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(CourseStudent.objects.filter(pk=self.row.pk).exists())


class TheTotalCountsMarksTests(SchoolTestMixin, APITestCase):
    """
    Итог ученика в таблице результатов считается по баллам.

    Считался он только там, где есть онлайн-ответ. У бумажной работы ответов
    нет — баллы пришли со скана, — и выходило «0 из 5» у всего класса при
    выставленных галочках в каждой клетке.
    """

    def test_a_mark_without_an_online_answer_counts(self):
        year = make_year(self.school)
        course = make_course(self.school, year)
        work = make_work(self.user, course)
        first, second = make_task(work), make_task(work, position=1)
        enrol(self.student, course, by=self.admin)
        work_services.grade(
            work, self.student, scores={first.pk: 1, second.pk: 0}, by=self.user
        )
        self.client.force_authenticate(self.user)

        table = self.client.get(reverse("work-table", args=[work.pk])).json()

        self.assertEqual(table["students"][0]["correct"], 1)
