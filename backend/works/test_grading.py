"""
Оценки: шкала настраивается у работы, значение лежит по критериям.

Три состояния оценивания — не оценивается, обычная отметка, по критериям —
выражены одними данными: **оценивание есть тогда, когда есть критерии**.
Ноль критериев, один безымянный, несколько именованных. Отдельного флага
нет намеренно: он был бы вторым источником правды о том же самом.

Отсюда и форма хранения: значение — строка «критерий → число», и обычная
отметка это один критерий без имени. Добавить потом буквы или «зачёт»
значит добавить вид критерия, а не переливать уже поставленные оценки.
"""

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.services import enrol
from schools.testing import (
    SchoolTestMixin,
    make_course,
    make_task,
    make_work,
    make_year,
)

from .models import Criterion, Mark, MarkChange, StudentWork


class GradingTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        self.enrolment = enrol(self.student, self.course, by=self.admin)

    def set_scale(self, criteria):
        return self.client.put(
            reverse("work-criteria", args=[self.work.pk]),
            {"criteria": criteria},
            format="json",
        )

    def grade(self, marks=None, comment=None, student=None):
        body = {"student": (student or self.student).pk}
        if marks is not None:
            body["marks"] = marks
        if comment is not None:
            body["comment"] = comment
        return self.client.post(
            reverse("work-grade", args=[self.work.pk]), body, format="json"
        )

    def scale(self):
        return self.client.get(reverse("work-criteria", args=[self.work.pk])).json()


class ScaleTests(GradingTestCase):
    def test_a_work_starts_ungraded(self):
        body = self.scale()

        self.assertEqual(body["criteria"], [])
        self.assertFalse(body["graded"])

    def test_one_nameless_criterion_is_an_ordinary_mark(self):
        self.set_scale([{"name": "", "maximum": 5}])

        body = self.scale()

        self.assertTrue(body["graded"])
        self.assertTrue(body["simple"], "интерфейс должен показать одно поле")

    def test_several_named_criteria_are_a_rubric(self):
        self.set_scale(
            [{"name": f"Критерий {letter}", "maximum": 8} for letter in "ABCD"]
        )

        body = self.scale()

        self.assertEqual(len(body["criteria"]), 4)
        self.assertFalse(body["simple"])
        self.assertEqual([item["position"] for item in body["criteria"]], [0, 1, 2, 3])

    def test_one_named_criterion_is_still_a_rubric(self):
        """Правило однозначное: имя есть — значит критерий, а не отметка."""
        self.set_scale([{"name": "Понимание", "maximum": 8}])

        self.assertFalse(self.scale()["simple"])

    def test_the_scale_is_replaced_whole_and_keeps_its_order(self):
        self.set_scale([{"name": "A", "maximum": 8}, {"name": "B", "maximum": 8}])

        self.set_scale([{"name": "B", "maximum": 6}])

        body = self.scale()
        self.assertEqual(len(body["criteria"]), 1)
        self.assertEqual((body["criteria"][0]["name"], body["criteria"][0]["maximum"]), ("B", 6))

    def test_an_empty_list_turns_grading_off(self):
        self.set_scale([{"name": "", "maximum": 5}])

        self.set_scale([])

        self.assertFalse(self.scale()["graded"])

    def test_dropping_a_criterion_takes_its_marks_and_says_so_first(self):
        """Цена называется до нажатия — тот же разговор, что при импорте плана."""
        self.set_scale([{"name": "A", "maximum": 8}])
        criterion = Criterion.objects.get()
        self.grade(marks={criterion.pk: 6})

        before = self.client.get(
            reverse("work-scale-impact", args=[self.work.pk])
        ).json()
        self.set_scale([])

        self.assertEqual((before["marks"], before["students"]), (1, 1))
        self.assertFalse(Mark.objects.exists())


class MarkTests(GradingTestCase):
    def setUp(self):
        super().setUp()
        self.set_scale([{"name": "A", "maximum": 8}, {"name": "B", "maximum": 8}])
        self.a, self.b = Criterion.objects.order_by("position")

    def test_a_whole_set_is_written_at_once(self):
        response = self.grade(marks={self.a.pk: 6, self.b.pk: 7})

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json()["marks"], {str(self.a.pk): 6, str(self.b.pk): 7}
        )

    def test_a_mark_above_the_maximum_is_refused(self):
        response = self.grade(marks={self.a.pk: 9})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "mark_out_of_range")
        self.assertFalse(Mark.objects.exists())

    def test_a_criterion_of_another_work_is_refused(self):
        other = make_work(self.user, self.course, title="Другая")
        alien = Criterion.objects.create(work=other, position=0, name="X", maximum=5)

        response = self.grade(marks={alien.pk: 3})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "criterion_unknown")

    def test_null_removes_the_mark(self):
        self.grade(marks={self.a.pk: 6})

        self.grade(marks={self.a.pk: None})

        self.assertFalse(Mark.objects.filter(criterion=self.a).exists())

    def test_a_comment_lives_without_any_mark(self):
        """Работа может не оцениваться вовсе, а сказать о ней есть что."""
        self.set_scale([])

        response = self.grade(comment="Аккуратно, но не дописал")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(StudentWork.objects.get().comment, "Аккуратно, но не дописал")

    def test_the_row_appears_only_when_something_is_written(self):
        """«Ещё не проверен» и «строки нет» — одно состояние, и хранить его незачем."""
        self.assertFalse(StudentWork.objects.exists())

        self.grade(marks={self.a.pk: 5})

        self.assertEqual(StudentWork.objects.count(), 1)

    def test_a_student_of_another_course_cannot_be_graded(self):
        outsider = make_course(self.school, self.year, "10А")
        stranger = self.colleague  # не ученик этого курса

        response = self.grade(marks={self.a.pk: 5}, student=stranger)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(outsider.name, "10А")


class HistoryTests(GradingTestCase):
    """
    Исправленная оценка — событие, а не новое значение поля.

    Пишется с первого дня: восстановить задним числом её будет неоткуда, а
    «почему у него было три, а стало четыре» — обычный вопрос к журналу.
    """

    def setUp(self):
        super().setUp()
        self.set_scale([{"name": "", "maximum": 5}])
        self.criterion = Criterion.objects.get()

    def test_every_change_is_written_down_with_its_author(self):
        self.grade(marks={self.criterion.pk: 3})
        self.grade(marks={self.criterion.pk: 4})

        log = list(MarkChange.objects.values_list("value", "changed_by"))

        self.assertEqual(log, [(3, self.user.pk), (4, self.user.pk)])

    def test_setting_the_same_value_again_writes_nothing(self):
        self.grade(marks={self.criterion.pk: 3})

        self.grade(marks={self.criterion.pk: 3})

        self.assertEqual(MarkChange.objects.count(), 1)

    def test_removing_the_mark_is_an_event_too(self):
        self.grade(marks={self.criterion.pk: 3})

        self.grade(marks={self.criterion.pk: None})

        self.assertEqual(
            list(MarkChange.objects.values_list("value", flat=True)), [3, None]
        )


class StudentSideTests(GradingTestCase):
    def setUp(self):
        super().setUp()
        make_task(self.work)
        self.set_scale([{"name": "", "maximum": 5}])
        self.criterion = Criterion.objects.get()
        self.grade(marks={self.criterion.pk: 4}, comment="Хорошо")

    def mine(self):
        self.sign_in(self.student)
        return self.client.get(reverse("student-work", args=[self.work.pk])).json()

    def test_the_student_sees_their_own_mark(self):
        body = self.mine()

        self.assertEqual(body["marks"], {str(self.criterion.pk): 4})
        self.assertEqual(body["comment"], "Хорошо")

    def test_with_results_hidden_the_mark_waits_for_the_window_to_close(self):
        self.work.show_result = False
        self.work.save(update_fields=["show_result"])

        body = self.mine()

        self.assertEqual(body["marks"], {})
        self.assertEqual(body["comment"], "")
        # шкалу при этом видно: «из пяти» — это про работу, а не про него
        self.assertTrue(body["graded"])

    def test_a_mark_moves_the_polling_version(self):
        before = self.mine()["version"]

        self.sign_in(self.user)
        self.grade(marks={self.criterion.pk: 5})

        self.assertNotEqual(self.mine()["version"], before)

    def test_the_table_carries_the_marks_the_teacher_gave(self):
        body = self.client.get(reverse("work-table", args=[self.work.pk])).json()

        row = next(item for item in body["students"] if item["id"] == self.student.pk)
        self.assertEqual(row["marks"], {str(self.criterion.pk): 4})
        self.assertEqual(row["comment"], "Хорошо")
        self.assertEqual(len(body["criteria"]), 1)
