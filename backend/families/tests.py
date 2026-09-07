"""
Родитель: третий вид, а не «ученик с несколькими экранами».

Проверяется здесь в первую очередь то, чего **не** должно быть. Появление вида
опасно ровно этим: правила, написанные под два вида, продолжают работать и
молчат. Самое дорогое из них было сформулировано как «не ученик» и означало
«учитель», — и родитель прошёл бы по нему в учебный план всей школы.
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from schools.testing import (
    SchoolTestMixin,
    assign,
    make_course,
    make_user,
    make_work,
    make_year,
    sign_in,
)

from django.contrib.auth import get_user_model

from .models import Guardianship, link
from . import conversations, viewing

User = get_user_model()


class ParentIsNotATeacherTests(SchoolTestMixin, APITestCase):
    """
    Самая дорогая проверка во всём наборе, и стоит она одной строки кода.

    `IsTeacher` читалось как «не ученик» — пока видов было два, это совпадало
    с «учитель». Родитель совпадение сломал: он не ученик, и по прежнему
    правилу открывал учебный план, расписание и работы всей школы. Ошибка
    была бы молчаливой — ни один тест про ученика не покраснел бы.
    """

    def setUp(self):
        super().setUp()
        self.parent = make_user(
            self.school, email="mama@example.com", parent=True
        )

    def test_a_parent_does_not_get_into_the_teacher_sections(self):
        sign_in(self.client, self.parent)

        answer = self.client.get("/api/courses/")

        self.assertEqual(answer.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(answer.json()["code"], "teachers_only")

    def test_a_parent_is_neither_a_student_nor_a_teacher(self):
        self.assertFalse(self.parent.is_student)
        self.assertFalse(self.parent.is_teacher)
        self.assertTrue(self.parent.is_parent)
        self.assertTrue(self.parent.is_family)


class LinkingTests(SchoolTestMixin, APITestCase):
    """Связь родства заводится через сервис: база вид и школу не проверит."""

    def setUp(self):
        super().setUp()
        self.parent = make_user(self.school, email="mama@example.com", parent=True)
        self.child = make_user(self.school, email="kid@example.com", student=True)

    def test_a_parent_and_a_child_are_linked(self):
        link(self.parent, self.child, relation="мама")

        self.assertEqual(viewing.children_of(self.parent), [self.child])

    def test_linking_twice_does_not_double_the_row(self):
        link(self.parent, self.child)
        link(self.parent, self.child)

        self.assertEqual(Guardianship.objects.count(), 1)

    def test_a_teacher_cannot_be_somebodys_child(self):
        colleague = make_user(self.school, email="other@example.com")

        with self.assertRaises(Exception) as caught:
            link(self.parent, colleague)

        self.assertIn("not_a_student", str(caught.exception.detail))

    def test_a_student_cannot_be_a_parent(self):
        with self.assertRaises(Exception) as caught:
            link(self.child, self.child)

        self.assertIn("not_a_parent", str(caught.exception.detail))

    def test_a_child_from_another_school_is_refused(self):
        from schools.testing import make_school

        stranger = make_user(
            make_school("Другая"), email="far@example.com", student=True
        )

        with self.assertRaises(Exception) as caught:
            link(self.parent, stranger)

        self.assertIn("different_schools", str(caught.exception.detail))

    def test_mother_and_father_are_two_rows_on_one_child(self):
        """
        Две учётки на одного ребёнка — обычное состояние, а не дубль.

        Общая учётка выглядела бы экономией, а стоила бы правды: кто написал
        учителю и кому ушло оповещение — вопросы к человеку.
        """
        father = make_user(self.school, email="papa@example.com", parent=True)

        link(self.parent, self.child, relation="мама")
        link(father, self.child, relation="папа")

        self.assertEqual(Guardianship.objects.filter(child=self.child).count(), 2)
        self.assertEqual(viewing.children_of(father), [self.child])


class WhoseScreenTests(SchoolTestMixin, APITestCase):
    """
    Чей экран показывать. Один вопрос, один ответ — `viewing.subject_of`.

    Разложи его по четырём вьюхам, и однажды пятая забудет спросить; забытое
    место откроет родителю чужого ребёнка, и обнаружит это родитель.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        assign(self.user, self.course)

        self.child = make_user(self.school, email="kid@example.com", student=True)
        self.other = make_user(self.school, email="kid2@example.com", student=True)
        self.parent = make_user(self.school, email="mama@example.com", parent=True)
        link(self.parent, self.child)

        self.course.students.create(student=self.child)
        make_work(self.user, self.course, title="Контрольная")

    def test_a_parent_sees_the_works_of_their_child(self):
        sign_in(self.client, self.parent)

        answer = self.client.get(reverse("student-works"))

        self.assertEqual(answer.status_code, status.HTTP_200_OK)
        titles = [work["title"] for work in answer.json()["works"]]
        self.assertEqual(titles, ["Контрольная"])

    def test_somebody_elses_child_does_not_exist_for_a_parent(self):
        sign_in(self.client, self.parent)

        answer = self.client.get(reverse("student-works"), {"child": self.other.pk})

        self.assertEqual(answer.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(answer.json()["code"], "not_your_child")

    def test_with_several_children_the_parent_has_to_say_which(self):
        """Молча показать первого по алфавиту хуже, чем переспросить."""
        second = make_user(self.school, email="kid3@example.com", student=True)
        link(self.parent, second)
        sign_in(self.client, self.parent)

        answer = self.client.get(reverse("student-works"))

        self.assertEqual(answer.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(answer.json()["code"], "child_required")

    def test_with_one_child_nothing_has_to_be_said(self):
        sign_in(self.client, self.parent)

        answer = self.client.get(reverse("student-works"))

        self.assertEqual(answer.status_code, status.HTTP_200_OK)

    def test_a_student_is_still_shown_their_own_screen(self):
        """У ученика `?child=` не спрашивается вовсе — иначе это дыра."""
        sign_in(self.client, self.child)

        answer = self.client.get(reverse("student-works"), {"child": self.other.pk})

        self.assertEqual(answer.status_code, status.HTTP_200_OK)

    def test_a_parent_does_not_answer_for_their_child(self):
        """
        Смотреть за учёбой и учиться вместо ребёнка — разные вещи, и второе
        закрыто правом, а не экраном.
        """
        work = make_work(self.user, self.course, title="Домашняя")
        task = work.tasks.create(position=0)
        sign_in(self.client, self.parent)

        answer = self.client.post(
            reverse("student-answer", args=[task.pk]), {"answer": "42"}
        )

        self.assertEqual(answer.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(answer.json()["code"], "students_only")


class SchoolLinksTests(SchoolTestMixin, APITestCase):
    """
    Администратор связывает родителя с ребёнком по адресу — и заводит его,
    если такого ещё нет. Тем же путём, что импорт: приглашение как билет,
    учётка сразу, вход — когда человек придёт.
    """

    def setUp(self):
        super().setUp()
        self.child = make_user(self.school, "kid@example.com", student=True)
        sign_in(self.client, self.admin)

    def post(self, **body):
        return self.client.post(
            reverse("guardianship-list"), {"child": self.child.pk, **body}, format="json"
        )

    def test_an_unknown_address_becomes_a_parent_account_and_a_link(self):
        answer = self.post(email="Mum@Example.com", relation="мама")

        self.assertEqual(answer.status_code, 201, answer.content)
        row = Guardianship.objects.get(child=self.child)
        self.assertEqual(row.parent.email, "mum@example.com")
        self.assertTrue(row.parent.is_parent)
        self.assertEqual(row.parent.school_id, self.school.pk)
        self.assertIsNone(row.parent.last_login)
        self.assertEqual(row.relation, "мама")
        self.assertEqual(answer.json()["parent"]["arrived"], False)

    def test_a_known_parent_is_linked_and_not_duplicated(self):
        mum = make_user(self.school, "mum@example.com", parent=True)

        self.post(email="mum@example.com")
        self.post(email="mum@example.com")

        self.assertEqual(Guardianship.objects.filter(parent=mum, child=self.child).count(), 1)

    def test_a_teachers_address_is_refused(self):
        answer = self.post(email=self.user.email)

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.json()["code"], "email_other_kind")

    def test_the_childs_own_address_is_refused(self):
        answer = self.post(email="kid@example.com")

        self.assertEqual(answer.json()["code"], "roster_parent_is_student")

    def test_a_student_of_another_school_is_not_a_child_here(self):
        stranger = make_user(self.alien_school, "far@example.com", student=True)

        answer = self.client.post(
            reverse("guardianship-list"),
            {"child": stranger.pk, "email": "mum@example.com"},
            format="json",
        )

        self.assertEqual(answer.status_code, 400)

    def test_the_students_list_shows_their_parents(self):
        mum = make_user(self.school, "mum@example.com", parent=True)
        Guardianship.objects.create(parent=mum, child=self.child, relation="мама")

        answer = self.client.get(reverse("member-list"), {"kind": "student"}).json()

        [student] = [person for person in answer if person["id"] == self.child.pk]
        [parent] = student["parents"]
        self.assertEqual((parent["email"], parent["relation"], parent["arrived"]), ("mum@example.com", "мама", True))

    def test_unlinking_deletes_the_row_and_keeps_the_people(self):
        mum = make_user(self.school, "mum@example.com", parent=True)
        row = Guardianship.objects.create(parent=mum, child=self.child)

        answer = self.client.delete(reverse("guardianship-detail", args=[row.pk]))

        self.assertEqual(answer.status_code, 204)
        self.assertFalse(Guardianship.objects.exists())
        self.assertTrue(User.objects.filter(pk=mum.pk).exists())
