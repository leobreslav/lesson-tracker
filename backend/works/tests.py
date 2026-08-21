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
    assign,
    make_course,
    make_task,
    make_user,
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

        self.assertEqual(
            impact,
            {
                "state": "open",
                "answers": 1,
                "students": 1,
                "checked": 0,
                # оценки считаются наравне с отправками: у бумажной работы
                # отправок нет вовсе, и цена, слепая к оценкам, сообщала бы
                # «ничего не затронуто» про проверенный класс
                "graded": 0,
                "top": 1,
            },
        )
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
            list(
                Task.objects.filter(work=self.work).values_list(
                    "problem__text", "position"
                )
            ),
            [(first.problem.text, 0), ("Третья", 1)],
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


class OwnershipTests(WorkTestCase):
    """
    Работа принадлежит курсу, а не тому, кто её составил.

    Личной она была, пока курс могли вести двое. Ведущий теперь один, а
    цена личной работы осталась бы дважды: уход человека уносил её вместе с
    ответами учеников (`CASCADE`), а после смены ведущего непроверенное
    некому было бы проверить.
    """

    def setUp(self):
        super().setUp()
        self.sign_in(self.student)
        self.answer("4")

    def test_the_answers_outlive_the_teacher_who_set_the_work(self):
        """Раньше `CASCADE` стирал вместе с учёткой и ответы, и отметки."""
        self.user.delete()

        self.work.refresh_from_db()
        self.assertIsNone(self.work.created_by_id)
        self.assertEqual(self.work.course_id, self.course.pk)
        self.assertEqual(Submission.objects.filter(task=self.task).count(), 1)

    def test_the_next_lead_teacher_marks_what_the_previous_one_left(self):
        """
        Смена ведущего не оставляет непроверенного без хозяина.

        Пока работа была личной, ответы предшественника висели у учеников
        на виду, а доправить условие или отметить их не мог никто.
        """
        assign(self.colleague, self.course)
        submission = Submission.objects.get()
        self.sign_in(self.colleague)

        marked = self.client.patch(
            reverse("submission-detail", args=[submission.pk]),
            {"is_correct": True},
            format="json",
        )
        renamed = self.client.patch(
            reverse("work-detail", args=[self.work.pk]),
            {"title": "Та же работа, новый ведущий"},
            format="json",
        )

        self.assertEqual(marked.status_code, 200, marked.content)
        self.assertEqual(renamed.status_code, 200, renamed.content)
        submission.refresh_from_db()
        self.assertTrue(submission.is_correct)
        self.assertEqual(submission.checked_by, self.colleague)

    def test_a_colleague_who_does_not_lead_the_course_reaches_nothing(self):
        """Курс мой ровно потому, что мне его поручили, — иначе его нет."""
        self.sign_in(self.colleague)

        listed = self.client.get(reverse("work-list"), {"course": self.course.pk})
        refused = self.client.patch(
            reverse("work-detail", args=[self.work.pk]),
            {"title": "По-моему, так лучше"},
            format="json",
        )

        self.assertEqual(listed.json(), [])
        self.assertEqual(refused.status_code, 404)


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


# --- сводная таблица ------------------------------------------------------------


class TableTests(WorkTestCase):
    """
    Ученики по строкам, задачи по столбцам — и три состояния ячейки.

    Проверяется то, из-за чего таблицу вообще собирают на сервере: ячейка
    показывает **последнюю** отправку, снятые с курса остаются строками, а
    «переделал после проверки» видно не по времени, а само.
    """

    def setUp(self):
        super().setUp()
        self.second = make_task(self.work, "Вторая", position=1)
        self.sign_in(self.user)

    def table(self, params=None):
        return self.client.get(reverse("work-table", args=[self.work.pk]), params or {})

    def answer_as(self, student, task, text):
        self.sign_in(student)
        self.client.post(
            reverse("student-answer", args=[task.pk]), {"answer": text}, format="json"
        )
        self.sign_in(self.user)

    def test_the_grid_has_a_row_per_student_and_a_column_per_task(self):
        answer = self.table().json()

        self.assertEqual([task["id"] for task in answer["tasks"]],
                         [self.task.pk, self.second.pk])
        self.assertEqual([row["id"] for row in answer["students"]], [self.student.pk])
        self.assertEqual(len(answer["students"][0]["cells"]), 2)

    def test_an_empty_cell_is_a_state_of_its_own(self):
        cell = self.table().json()["students"][0]["cells"][0]

        self.assertIsNone(cell["submission"])
        self.assertEqual(cell["attempts"], 0)

    def test_the_cell_shows_the_last_answer_and_counts_the_rest(self):
        self.answer_as(self.student, self.task, "сначала")
        self.answer_as(self.student, self.task, "потом")

        cell = self.table().json()["students"][0]["cells"][0]

        self.assertEqual(cell["answer"], "потом")
        self.assertEqual(cell["attempts"], 2)

    def test_redone_after_checking_is_marked(self):
        """
        Весь ответ на гонку «учитель проверял, пока ученик отправлял».

        Отметка осталась на прошлой строке, ячейка вернулась в «не
        проверено», и видно, что смотрели не то.
        """
        self.answer_as(self.student, self.task, "раз")
        first = Submission.objects.get()
        self.client.patch(
            reverse("submission-detail", args=[first.pk]),
            {"is_correct": True},
            format="json",
        )

        self.answer_as(self.student, self.task, "два")

        cell = self.table().json()["students"][0]["cells"][0]
        self.assertTrue(cell["redone"])
        self.assertIsNone(cell["verdict"])

    def test_a_removed_student_stays_a_row_and_is_marked(self):
        """Его ответы никуда не делись, и смешивать их с работающими нельзя."""
        self.answer_as(self.student, self.task, "успел")
        remove_from_course(self.enrolment)

        row = self.table().json()["students"][0]

        self.assertFalse(row["active"])
        self.assertEqual(row["answered"], 1)

    def test_the_column_counts_who_managed_it(self):
        """Столбец, с которым не справилась половина класса, — весь смысл."""
        self.answer_as(self.student, self.task, "верно")
        self.client.patch(
            reverse("submission-detail", args=[Submission.objects.get().pk]),
            {"is_correct": False},
            format="json",
        )

        column = self.table().json()["tasks"][0]

        self.assertEqual(
            (column["answered"], column["correct"], column["wrong"], column["unchecked"]),
            (1, 0, 1, 0),
        )

    def test_the_version_makes_an_unchanged_answer_cheap(self):
        version = self.table().json()["version"]

        answer = self.table({"version": version}).json()

        self.assertFalse(answer["changed"])
        self.assertNotIn("students", answer)

    def test_any_event_moves_the_version(self):
        version = self.table().json()["version"]

        self.answer_as(self.student, self.task, "ответ")
        after_answer = self.table().json()["version"]
        self.assertNotEqual(after_answer, version)

        self.client.patch(
            reverse("submission-detail", args=[Submission.objects.get().pk]),
            {"is_correct": True},
            format="json",
        )
        after_verdict = self.table().json()["version"]
        self.assertNotEqual(after_verdict, after_answer)

    def test_the_number_of_queries_does_not_grow_with_the_students(self):
        """Тридцать учеников на десять задач — это триста ячеек."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.answer_as(self.student, self.task, "ответ")

        with CaptureQueriesContext(connection) as one_student:
            self.table()

        for index in range(5):
            extra = make_user(
                self.school, f"pupil{index}@example.com", student=True
            )
            enrol(extra, self.course, by=self.admin)
            self.answer_as(extra, self.task, f"ответ {index}")

        with CaptureQueriesContext(connection) as six_students:
            answer = self.table()

        self.assertEqual(len(answer.json()["students"]), 6)
        self.assertEqual(
            len(six_students),
            len(one_student),
            f"запросы растут с учениками: {len(one_student)} против "
            f"{len(six_students)}",
        )


class VerdictTests(WorkTestCase):
    def setUp(self):
        super().setUp()
        self.answer("4")
        self.submission = Submission.objects.get()
        self.sign_in(self.user)

    def patch(self, value):
        return self.client.patch(
            reverse("submission-detail", args=[self.submission.pk]),
            {"is_correct": value},
            format="json",
        )

    def test_a_verdict_stamps_who_and_when(self):
        self.patch(True)

        self.submission.refresh_from_db()
        self.assertTrue(self.submission.is_correct)
        self.assertEqual(self.submission.checked_by, self.user)
        self.assertIsNotNone(self.submission.checked_at)

    def test_a_verdict_can_be_taken_back(self):
        self.patch(False)

        self.patch(None)

        self.submission.refresh_from_db()
        self.assertIsNone(self.submission.is_correct)
        self.assertIsNone(self.submission.checked_at)
        self.assertIsNone(self.submission.checked_by)

    def test_the_answer_itself_is_never_editable(self):
        """Это слова ученика, а не наша запись о них."""
        self.client.patch(
            reverse("submission-detail", args=[self.submission.pk]),
            {"answer": "подправил за него"},
            format="json",
        )

        self.submission.refresh_from_db()
        self.assertEqual(self.submission.answer, "4")

    def test_the_journal_is_read_by_task_for_checking_a_column(self):
        """Проверяют столбцом: открыть задачу и пройти ответы подряд."""
        rows = self.client.get(
            reverse("submission-list"), {"task": self.task.pk}
        ).json()

        self.assertEqual([row["answer"] for row in rows], ["4"])
        self.assertEqual(rows[0]["student_name"], self.student.email)

    def test_a_submission_cannot_be_deleted(self):
        answer = self.client.delete(
            reverse("submission-detail", args=[self.submission.pk])
        )

        self.assertEqual(answer.status_code, 405)
        self.assertTrue(Submission.objects.exists())


class SummaryTests(WorkTestCase):
    """
    Статистика работы: числа, которых таблица не говорит одним взглядом.

    Итоги по строкам и столбцам в ней уже есть, а «сколько человек дошло
    до конца» и «какая задача провалилась» — нет: их пришлось бы считать
    глазами по тридцати строкам.
    """

    def setUp(self):
        super().setUp()
        self.second = make_task(self.work, "Вторая", position=1)
        self.work.attempts = None
        self.work.save()
        self.other = make_user(self.school, "pupil@example.com", student=True)
        enrol(self.other, self.course, by=self.admin)
        self.sign_in(self.user)

    def summary(self):
        return self.client.get(reverse("work-table", args=[self.work.pk])).json()[
            "summary"
        ]

    def answer_as(self, student, task, text):
        self.sign_in(student)
        self.client.post(
            reverse("student-answer", args=[task.pk]), {"answer": text}, format="json"
        )
        self.sign_in(self.user)

    def mark(self, submission, value):
        self.client.patch(
            reverse("submission-detail", args=[submission.pk]),
            {"is_correct": value},
            format="json",
        )

    def test_started_and_finished_count_the_whole_work(self):
        self.answer_as(self.student, self.task, "раз")
        self.answer_as(self.student, self.second, "два")
        self.answer_as(self.other, self.task, "только первая")

        numbers = self.summary()

        self.assertEqual(numbers["students"], 2)
        self.assertEqual(numbers["started"], 2)
        self.assertEqual(numbers["finished"], 1)

    def test_a_removed_student_leaves_the_denominator_but_not_the_work(self):
        """
        Снятый ничего «не не закончил» — он ушёл. А его ответы всё ещё
        надо проверить: работа учителя от его ухода меньше не стала.
        """
        self.answer_as(self.student, self.task, "успел")
        remove_from_course(self.enrolment)

        numbers = self.summary()

        self.assertEqual(numbers["students"], 1)
        self.assertEqual(numbers["started"], 0)
        self.assertEqual(numbers["answers"], 1)
        self.assertEqual(numbers["unchecked"], 1)

    def test_the_summary_agrees_with_the_grid_it_was_counted_from(self):
        """
        Сводка и таблица обязаны говорить одно и то же: два расчёта над
        одними данными расходятся молча.
        """
        self.answer_as(self.student, self.task, "раз")
        self.answer_as(self.other, self.second, "два")
        self.mark(Submission.objects.first(), True)

        table = self.client.get(reverse("work-table", args=[self.work.pk])).json()

        self.assertEqual(
            table["summary"]["answers"],
            sum(column["answered"] for column in table["tasks"]),
        )
        self.assertEqual(
            table["summary"]["correct"],
            sum(row["correct"] for row in table["students"]),
        )


class StudentPollingTests(WorkTestCase):
    """
    Ученик опрашивает свою работу так же, как учитель — таблицу.

    Отметка приходит к нему без его участия, и страница, которую надо
    обновлять руками, — это страница, которой не верят.
    """

    def version(self):
        return self.my_work().json()["version"]

    def test_an_unchanged_page_is_cheap(self):
        version = self.version()

        answer = self.client.get(
            reverse("student-work", args=[self.work.pk]), {"version": version}
        ).json()

        self.assertFalse(answer["changed"])
        self.assertNotIn("tasks", answer)

    def test_a_verdict_moves_the_version(self):
        self.answer("ответ")
        before = self.version()

        self.sign_in(self.user)
        self.client.patch(
            reverse("submission-detail", args=[Submission.objects.get().pk]),
            {"is_correct": True},
            format="json",
        )
        self.sign_in(self.student)

        self.assertNotEqual(self.version(), before)
        self.assertTrue(
            self.my_work().json()["tasks"][0]["submissions"][0]["verdict"]
        )

    def test_an_edited_task_moves_the_version_too(self):
        """
        Правка открытой работы разрешена и названа ценой — значит ученик
        должен увидеть новое условие, а не то, что было при загрузке.
        """
        before = self.version()

        self.sign_in(self.user)
        self.client.patch(
            reverse("task-detail", args=[self.task.pk]),
            {"question": "Другое условие"},
            format="json",
        )
        self.client.patch(
            reverse("work-detail", args=[self.work.pk]),
            {"title": "Переименована"},
            format="json",
        )
        self.sign_in(self.student)

        self.assertNotEqual(self.version(), before)
