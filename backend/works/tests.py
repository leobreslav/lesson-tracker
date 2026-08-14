"""
Правила работ: окно, попытки, журнал и вердикт.

Четыре решения, на которых стоит подсистема, проверяются здесь поимённо —
их легко нарушить мимоходом, а последствия видны не сразу: попытка,
съеденная не тогда; ответ, затёртый вторым; вердикт, переехавший на новую
отправку.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from schools.services import enrol, remove_from_course
from schools.testing import (
    SchoolTestMixin,
    make_course,
    make_task,
    make_work,
    make_year,
)

from .models import Submission, Task, Work


class WorkTestCase(SchoolTestMixin, APITestCase):
    """Учитель с курсом, работа в нём и ученик, который её решает."""

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        self.task = make_task(self.work)
        self.enrolment = enrol(self.student, self.course, by=self.admin)
        self.sign_in(self.student)

    def answer(self, text="4", task=None):
        return self.client.post(
            reverse("student-answer", args=[(task or self.task).pk]),
            {"answer": text},
            format="json",
        )

    def my_work(self, work=None):
        return self.client.get(reverse("student-work", args=[(work or self.work).pk]))

    def my_works(self):
        return self.client.get(reverse("student-works"))


# --- окно времени вместо черновика ------------------------------------------------


class WindowTests(WorkTestCase):
    def test_a_work_that_has_not_opened_does_not_exist_for_the_student(self):
        """Черновика нет: его роль играет окно, начинающееся в будущем."""
        soon = timezone.now() + timedelta(days=1)
        self.work.opens_at, self.work.closes_at = soon, soon + timedelta(days=1)
        self.work.save()

        self.assertEqual(self.my_works().json()["works"], [])
        self.assertEqual(self.my_work().status_code, 404)
        self.assertEqual(self.answer().status_code, 404)

    def test_a_closed_work_stays_visible_but_takes_no_answers(self):
        self.answer("сначала")
        self.work.closes_at = timezone.now() - timedelta(minutes=1)
        self.work.save()

        listed = self.my_works().json()["works"][0]
        refused = self.answer("потом")

        self.assertEqual(listed["state"], "closed")
        self.assertFalse(listed["can_answer"])
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "work_closed")
        # ответ, отправленный до закрытия, остался на месте
        self.assertEqual(
            [row["answer"] for row in self.my_work().json()["tasks"][0]["submissions"]],
            ["сначала"],
        )

    def test_reopening_the_window_lets_the_work_continue(self):
        """«Окно продлили — можно работать дальше»: состояние, не статус."""
        self.work.closes_at = timezone.now() - timedelta(minutes=1)
        self.work.save()
        self.assertEqual(self.answer().status_code, 400)

        self.work.closes_at = timezone.now() + timedelta(days=1)
        self.work.save()

        self.assertEqual(self.answer().status_code, 201)


# --- попытки ----------------------------------------------------------------------


class AttemptTests(WorkTestCase):
    def test_an_attempt_is_spent_on_any_submission(self):
        """
        Главное решение подсистемы: непроверенная отправка тоже расходует.

        Иначе право ученика на ответ зависело бы от того, как быстро учитель
        дошёл до его ячейки, — правило, которое ученик не может проверить
        сам.
        """
        self.work.attempts = 2
        self.work.save()

        first = self.answer("раз")
        second = self.answer("два")
        third = self.answer("три")

        self.assertEqual(first.json()["attempts_left"], 1)
        self.assertEqual(second.json()["attempts_left"], 0)
        self.assertEqual(third.status_code, 400)
        self.assertEqual(third.json()["code"], "attempts_exhausted")

    def test_a_verdict_does_not_spend_an_attempt(self):
        self.work.attempts = 2
        self.work.save()
        self.answer("раз")

        Submission.objects.update(is_correct=False, checked_at=timezone.now())

        self.assertEqual(self.answer("два").json()["attempts_left"], 0)

    def test_attempts_are_counted_per_task_not_per_work(self):
        self.work.attempts = 1
        self.work.save()
        second_task = make_task(self.work, "Ещё задача", position=1)

        self.assertEqual(self.answer().status_code, 201)
        self.assertEqual(self.answer(task=second_task).status_code, 201)

    def test_without_a_limit_the_answer_is_never_refused(self):
        self.work.attempts = None
        self.work.save()

        for _ in range(5):
            self.assertEqual(self.answer().status_code, 201)

        self.assertIsNone(self.my_work().json()["tasks"][0]["attempts_left"])


# --- журнал -----------------------------------------------------------------------


class JournalTests(WorkTestCase):
    def test_nothing_is_overwritten(self):
        """Отправка — строка журнала, а не значение поля."""
        self.answer("первый")
        self.answer("второй")

        history = self.my_work().json()["tasks"][0]["submissions"]

        self.assertEqual([row["answer"] for row in history], ["первый", "второй"])

    def test_the_answer_is_stored_exactly_as_typed(self):
        """
        Никакой нормализации при сохранении: когда появится автопроверка,
        обрабатывать надо будет при сравнении, а исходное к тому времени
        должно быть цело.
        """
        typed = "  x + 3\n"

        self.answer(typed)

        self.assertEqual(Submission.objects.get().answer, typed)

    def test_a_new_submission_leaves_the_cell_unchecked(self):
        """
        Вердикт приклеен к отправке. Пришла новая — проверять надо заново.

        Тут же и ответ на гонку: учитель видит, что ответ переделали после
        его отметки, потому что отметка осталась на прошлой строке.
        """
        self.answer("раз")
        Submission.objects.update(is_correct=True, checked_at=timezone.now())

        self.answer("два")

        history = self.my_work().json()["tasks"][0]["submissions"]
        self.assertEqual([row["verdict"] for row in history], [True, None])


# --- кто это видит ------------------------------------------------------------------


class VisibilityTests(WorkTestCase):
    def test_a_removed_student_keeps_reading_and_stops_answering(self):
        self.answer("успел")
        remove_from_course(self.enrolment)

        listed = self.my_works().json()["works"][0]
        refused = self.answer("уже нет")

        self.assertFalse(listed["can_answer"])
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "not_in_course")
        self.assertEqual(len(self.my_work().json()["tasks"][0]["submissions"]), 1)

    def test_another_courses_work_is_invisible(self):
        other = make_course(self.school, self.year, name="9В")
        make_work(self.user, other, title="Чужая")

        titles = [row["title"] for row in self.my_works().json()["works"]]

        self.assertEqual(titles, [self.work.title])

    def test_a_hidden_verdict_waits_for_the_window_to_close(self):
        """`show_result` выключен — отметка не видна до закрытия окна."""
        self.work.show_result = False
        self.work.save()
        self.answer()
        Submission.objects.update(is_correct=True, checked_at=timezone.now())

        self.assertIsNone(self.my_work().json()["tasks"][0]["submissions"][0]["verdict"])

        self.work.closes_at = timezone.now() - timedelta(minutes=1)
        self.work.save()

        self.assertTrue(self.my_work().json()["tasks"][0]["submissions"][0]["verdict"])

    def test_a_teacher_cannot_reach_the_student_half(self):
        self.sign_in(self.user)

        answer = self.client.get(reverse("student-works"))

        self.assertEqual(answer.status_code, 403)
        self.assertEqual(answer.json()["code"], "students_only")


# --- половина учителя ----------------------------------------------------------------


class TeacherSideTests(WorkTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in(self.user)

    def test_a_work_closing_before_it_opens_is_refused(self):
        answer = self.client.post(
            reverse("work-list"),
            {
                "course": self.course.pk,
                "title": "Задом наперёд",
                "opens_at": "2027-01-10T09:00:00Z",
                "closes_at": "2027-01-09T09:00:00Z",
            },
            format="json",
        )

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.json()["code"], "work_dates_reversed")

    def test_editing_an_open_work_is_allowed_and_priced(self):
        """
        Запрет здесь дороже ошибки: опечатку в условии находят посреди урока.
        Поэтому правка проходит, а цена называется числом.
        """
        self.sign_in(self.student)
        self.answer("ответ")
        self.sign_in(self.user)

        impact = self.client.get(reverse("work-impact", args=[self.work.pk])).json()
        renamed = self.client.patch(
            reverse("work-detail", args=[self.work.pk]),
            {"title": "Переименована посреди урока"},
            format="json",
        )

        self.assertEqual(impact, {"state": "open", "answers": 1, "students": 1, "checked": 0})
        self.assertEqual(renamed.status_code, 200)

    def test_rechecking_a_task_clears_the_verdicts_and_keeps_the_answers(self):
        """Неверный эталон — единственный случай, ради которого это есть."""
        self.sign_in(self.student)
        self.answer("x+3")
        self.sign_in(self.user)
        Submission.objects.update(is_correct=False, checked_at=timezone.now())

        answer = self.client.post(reverse("task-recheck", args=[self.task.pk]))

        self.assertEqual(answer.json()["reset"], 1)
        row = Submission.objects.get()
        self.assertIsNone(row.is_correct)
        self.assertIsNone(row.checked_at)
        self.assertEqual(row.answer, "x+3")

    def test_tasks_keep_dense_positions(self):
        first = self.task
        second = self.client.post(
            reverse("task-list"),
            {"work": self.work.pk, "question": "Вторая", "answers": ["2"]},
            format="json",
        ).json()
        third = self.client.post(
            reverse("task-list"),
            {"work": self.work.pk, "question": "Третья", "answers": []},
            format="json",
        ).json()

        self.assertEqual([first.position, second["position"], third["position"]], [0, 1, 2])

        self.client.post(
            reverse("task-move", args=[third["id"]]), {"direction": "up"}, format="json"
        )
        self.client.delete(reverse("task-detail", args=[second["id"]]))

        self.assertEqual(
            list(Task.objects.filter(work=self.work).values_list("question", "position")),
            [(first.question, 0), ("Третья", 1)],
        )

    def test_the_edge_of_the_list_is_not_an_error(self):
        answer = self.client.post(
            reverse("task-move", args=[self.task.pk]), {"direction": "up"}, format="json"
        )

        self.assertEqual(answer.status_code, 200)
        self.assertFalse(answer.json()["moved"])

    def test_empty_reference_answers_are_dropped(self):
        """Пустая строка формы — это не ответ «ничего», а мусор."""
        created = self.client.post(
            reverse("task-list"),
            {"work": self.work.pk, "question": "Устно", "answers": ["", "  "]},
            format="json",
        )

        self.assertEqual(created.json()["answers"], [])

    def test_a_work_of_a_course_they_do_not_teach_is_refused(self):
        alien = make_course(self.alien_school, make_year(self.alien_school), name="9Г")

        answer = self.client.post(
            reverse("work-list"),
            {
                "course": alien.pk,
                "title": "Чужой курс",
                "opens_at": "2027-01-09T09:00:00Z",
                "closes_at": "2027-01-10T09:00:00Z",
            },
            format="json",
        )

        self.assertEqual(answer.status_code, 400)

    def test_the_list_carries_the_number_of_tasks(self):
        make_task(self.work, "Вторая", position=1)

        rows = self.client.get(reverse("work-list"), {"course": self.course.pk}).json()

        self.assertEqual(rows[0]["tasks_count"], 2)
        self.assertEqual(rows[0]["state"], "open")


class QueryCountTests(WorkTestCase):
    def test_the_student_list_does_not_grow_with_the_works(self):
        """
        Список работ ученик открывает первым делом, и работ за год десятки.

        Проверяется не число — оно поедет от соседней правки, — а то, что от
        числа работ оно не зависит.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as one_work:
            self.my_works()

        for index in range(5):
            extra = make_work(self.user, self.course, title=f"Работа {index}")
            make_task(extra)

        with CaptureQueriesContext(connection) as six_works:
            response = self.my_works()

        self.assertEqual(len(response.json()["works"]), 6)
        self.assertEqual(
            len(six_works),
            len(one_work),
            f"запросы растут с работами: {len(one_work)} против {len(six_works)}",
        )
