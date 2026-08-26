"""
Справочник видов работ: контрольная, проверочная, самостоятельная, проект.

Проверяется здесь то же, что и у систем оценивания, и по тем же причинам:
**правит администратор, а выбирает учитель**, запрещённый вид не доезжает до
работы никаким путём, и новая школа не получает ничего — угаданный список хуже
пустого.

И отдельно — то, ради чего вид вообще заведён: он **не заменяет** домашность.
Домашняя контрольная бывает, и сложи мы их в один список, она стала бы
невыразимой.
"""

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import (
    SchoolTestMixin,
    assign,
    make_course,
    make_school,
    make_work,
    make_year,
)

from . import kinds
from .models import WorkKind


class WorkKindTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        assign(self.user, self.course)
        self.client.force_authenticate(self.admin)

    def test_a_new_school_gets_nothing_and_that_is_the_decision(self):
        """
        Угаданный список хуже пустого: школе, у которой «зачёт» вместо
        контрольных, пришлось бы удалять то, чего она не просила. Вместо
        посева — кнопка «типовые».
        """
        answer = self.client.get(reverse("work-kinds"))

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.data["kinds"], [])

    def test_the_typical_set_arrives_by_one_button_and_twice_is_safe(self):
        first = self.client.post(reverse("work-kinds"), {"typical": True})
        second = self.client.post(reverse("work-kinds"), {"typical": True})

        self.assertEqual(first.data["added"], 6)
        self.assertEqual(second.data["added"], 0)
        self.assertEqual(self.school.work_kinds.count(), 6)

    def test_a_renamed_kind_survives_the_typical_button(self):
        """
        «Обновить до типовых» — худшее из прочтений этой кнопки: школа могла
        переименовать «Проверочную» в «Летучку» и перекрасить её.
        """
        kinds.add_typical(self.school, "ru")
        mine = self.school.work_kinds.get(name="Проверочная")
        mine.name, mine.label = "Летучка", "Лт"
        mine.save(update_fields=["name", "label"])

        self.client.post(reverse("work-kinds"), {"typical": True})

        mine.refresh_from_db()
        self.assertEqual((mine.name, mine.label), ("Летучка", "Лт"))

    def test_a_kind_needs_a_label_because_the_gradebook_shows_it(self):
        """
        Метка — то, чем вид виден в журнале, и вывести её из имени нельзя:
        «Проект» и «Проверочная» дали бы одну и ту же букву.
        """
        answer = self.client.post(reverse("work-kinds"), {"name": "Диктант"})

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "work_kind_label_required")

    def test_a_teacher_reads_the_list_but_does_not_edit_it(self):
        """
        Та же форма доступа, что у систем оценивания: выбирать вид учителю, а
        держать список — школе.
        """
        self.client.force_authenticate(self.user)

        self.assertEqual(self.client.get(reverse("work-kinds")).status_code, 200)
        self.assertEqual(
            self.client.post(
                reverse("work-kinds"), {"name": "Диктант", "label": "Дк"}
            ).status_code,
            403,
        )

    def test_a_forbidden_kind_does_not_reach_a_work_by_any_road(self):
        """
        Запрет — единственный рычаг администратора над выбором, и обойти его
        значением в теле запроса нельзя. Тот же сторож, что у систем.
        """
        kinds.add_typical(self.school, "ru")
        banned = self.school.work_kinds.get(name="Проект")
        banned.is_allowed = False
        banned.save(update_fields=["is_allowed"])

        self.client.force_authenticate(self.user)
        work = make_work(self.user, self.course)
        answer = self.client.patch(
            reverse("work-detail", args=[work.pk]), {"kind": banned.pk}, format="json"
        )

        self.assertEqual(answer.status_code, 400)
        work.refresh_from_db()
        self.assertIsNone(work.kind_id)

    def test_somebody_else_s_kind_does_not_exist(self):
        other = WorkKind.objects.create(
            school=make_school("Соседняя"), name="Чужой", label="Ч"
        )

        answer = self.client.patch(
            reverse("work-kind", args=[other.pk]), {"name": "Мой"}, format="json"
        )

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "other_school")

    def test_removing_a_kind_leaves_the_works_alone(self):
        """
        Работы про то, что уже решали, а не про то, как школа их называет:
        убранный вид не уносит их с собой, а только снимает подпись.
        """
        kinds.add_typical(self.school, "ru")
        kind = self.school.work_kinds.get(name="Контрольная")
        work = make_work(self.user, self.course)
        work.kind = kind
        work.save(update_fields=["kind"])

        self.client.delete(reverse("work-kind", args=[kind.pk]))

        work.refresh_from_db()
        self.assertIsNone(work.kind_id)

    def test_a_kind_does_not_replace_being_set_for_home(self):
        """
        Домашняя контрольная — обычное дело, и выразима она только потому, что
        признаков два: вид отвечает «что это за работа», домашность — «где её
        показать». Один список сделал бы её невыразимой.
        """
        kinds.add_typical(self.school, "ru")
        kind = self.school.work_kinds.get(name="Контрольная")

        self.client.force_authenticate(self.user)
        work = make_work(self.user, self.course)
        answer = self.client.patch(
            reverse("work-detail", args=[work.pk]),
            {"kind": kind.pk, "is_homework": True},
            format="json",
        )

        self.assertEqual(answer.status_code, 200, answer.data)
        work.refresh_from_db()
        self.assertEqual((work.kind_id, work.is_homework), (kind.pk, True))

    def test_the_gradebook_head_carries_the_kind_and_not_a_guess(self):
        """
        Значок в шапке подписан видом, а цвет берётся оттуда же: выводить его
        из «итоговая или нет» было приблизительным ответом на точный вопрос.
        """
        from . import journal

        kinds.add_typical(self.school, "ru")
        kind = self.school.work_kinds.get(name="Лабораторная")
        work = make_work(self.user, self.course)
        work.kind = kind
        work.save(update_fields=["kind"])

        head = journal._work_head(work)

        self.assertEqual(head["kind"]["label"], "Л")
        self.assertEqual(head["kind"]["color"], "amber")

    def test_a_work_without_a_kind_is_a_normal_state(self):
        """У школы без справочника вид пустой, и это не поломка, а состояние."""
        from . import journal

        head = journal._work_head(make_work(self.user, self.course))

        self.assertIsNone(head["kind"])
