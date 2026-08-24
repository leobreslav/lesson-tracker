"""
Классы (хоумрумы): состав, перевод и ученик, стоящий в двух местах.

Класс заведён не ради ещё одного справочника. Его смысл в том, что курс
собран из учеников, а ученики собраны в классы, — и, зная оба состава,
можно наконец ответить на вопрос, на который до сих пор не отвечал никто:
**не стоит ли кто-то в двух местах разом**.

Здесь проверяется и то, и другое: правила самой принадлежности (одна на год,
снятие вместо удаления) и пересечение составов, ради которого всё затевалось.
"""

from datetime import timedelta

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import (
    MONDAY,
    SchoolTestMixin,
    assign,
    make_course,
    make_user,
    make_year,
)

from .models import CourseStudent, Homegroup, HomegroupStudent, Slot


class HomegroupTestCase(SchoolTestMixin, APITestCase):
    """Шестая параллель: два класса, два курса и трое учеников."""

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.algebra = make_course(self.school, self.year, "6 Алгебра")
        self.german = make_course(self.school, self.year, "6 Немецкий")
        assign(self.user, self.algebra)
        assign(self.colleague, self.german)

        self.a = Homegroup.objects.create(school=self.school, year=self.year, name="6А")
        self.b = Homegroup.objects.create(school=self.school, year=self.year, name="6Б")

        self.ivanov = make_user(self.school, "ivanov@example.com", student=True)
        self.ivanov.first_name = "Иван"
        self.ivanov.save(update_fields=["first_name"])
        self.petrova = make_user(self.school, "petrova@example.com", student=True)
        self.petrova.first_name = "Аня"
        self.petrova.save(update_fields=["first_name"])

    def put_in(self, group, student):
        return HomegroupStudent.objects.create(homegroup=group, student=student)

    def enrol(self, course, student):
        return CourseStudent.objects.create(course=course, student=student)

    def slot(self, course, number=1, day=MONDAY, **flags):
        return Slot.objects.create(
            year=self.year, course=course, date=day, lesson_number=number, **flags
        )

    def warnings_of(self, slot_id):
        rows = self.client.get(
            reverse("slot-list"),
            {
                "scope": "school",
                "start": MONDAY.isoformat(),
                "end": (MONDAY + timedelta(days=6)).isoformat(),
            },
        ).json()
        return next(row["warnings"] for row in rows if row["id"] == slot_id)


class HomegroupMembershipTests(HomegroupTestCase):
    """Принадлежность: одна на год, и снимается, а не стирается."""

    def test_the_year_of_the_row_follows_the_homegroup(self):
        """
        Год лежит копией на самой строке — ради ограничения уникальности, —
        и копия не может разойтись с оригиналом: она проставляется из класса
        и нигде больше не пишется.
        """
        row = self.put_in(self.a, self.ivanov)

        self.assertEqual(row.year_id, self.a.year_id)

    def test_a_student_belongs_to_one_homegroup_a_year(self):
        self.put_in(self.a, self.ivanov)
        self.client.force_authenticate(self.admin)

        refused = self.client.post(
            reverse("homegroup-student-list"),
            {"homegroup": self.b.pk, "student": self.ivanov.pk},
            format="json",
        )

        self.assertEqual(refused.status_code, 400, refused.content)
        self.assertEqual(refused.json()["code"], "homegroup_taken")
        # и отказ называет класс, в котором человек уже числится: без этого
        # он говорит «нельзя» и не говорит, что делать
        self.assertEqual(refused.json()["params"]["homegroup"], "6А")

    def test_a_transfer_is_possible_because_the_old_row_is_only_closed(self):
        """
        Перевод из 6А в 6Б посреди года — обычное дело, и он не должен
        стирать, что человек был в 6А: расписание сентября собиралось по
        тому составу.
        """
        row = self.put_in(self.a, self.ivanov)
        self.client.force_authenticate(self.admin)

        self.client.delete(reverse("homegroup-student-detail", args=[row.pk]))
        row.refresh_from_db()
        self.assertIsNotNone(row.removed_at)

        moved = self.client.post(
            reverse("homegroup-student-list"),
            {"homegroup": self.b.pk, "student": self.ivanov.pk},
            format="json",
        )
        self.assertEqual(moved.status_code, 201, moved.content)
        self.assertEqual(HomegroupStudent.objects.filter(student=self.ivanov).count(), 2)

    def test_a_homegroup_with_people_inside_is_not_deleted(self):
        self.put_in(self.a, self.ivanov)
        self.client.force_authenticate(self.admin)

        refused = self.client.delete(reverse("homegroup-detail", args=[self.a.pk]))

        self.assertEqual(refused.status_code, 400, refused.content)
        self.assertEqual(refused.json()["code"], "homegroup_in_use")

    def test_the_list_counts_who_is_inside_now(self):
        self.put_in(self.a, self.ivanov)
        gone = self.put_in(self.a, self.petrova)
        self.client.force_authenticate(self.admin)
        self.client.delete(reverse("homegroup-student-detail", args=[gone.pk]))

        rows = self.client.get(reverse("homegroup-list")).json()
        counts = {row["name"]: row["students"] for row in rows}

        self.assertEqual(counts["6А"], 1)
        self.assertEqual(counts["6Б"], 0)

    def test_a_teacher_reads_the_list_and_may_not_change_it(self):
        answer = self.client.get(reverse("homegroup-list"))
        self.assertEqual(answer.status_code, 200, answer.content)

        refused = self.client.post(
            reverse("homegroup-list"),
            {"year": self.year.pk, "name": "6В"},
            format="json",
        )
        self.assertEqual(refused.status_code, 403, refused.content)

    def test_a_tutor_is_a_property_of_the_class_and_not_a_right(self):
        """
        Классный руководитель ничего не открывает и не закрывает: это ответ
        на вопрос «чей это класс», который задают, когда надо написать.
        """
        self.client.force_authenticate(self.admin)
        answer = self.client.post(
            reverse("homegroup-list"),
            {"year": self.year.pk, "name": "6В", "tutor": self.colleague.pk},
            format="json",
        )

        self.assertEqual(answer.status_code, 201, answer.content)
        self.assertEqual(
            Homegroup.objects.get(name="6В").tutor_id, self.colleague.pk
        )
        self.assertTrue(answer.json()["tutor_name"])


class StudentIsInTwoPlacesTests(HomegroupTestCase):
    """Пересечение составов — то, ради чего классы и заведены."""

    def test_two_lessons_sharing_a_student_warn_both(self):
        """
        Две подгруппы 6А в третьем часу — норма, ровно для того их и делят.
        Ошибка — когда в обеих оказался Иванов: он один.
        """
        self.enrol(self.algebra, self.ivanov)
        self.enrol(self.german, self.ivanov)
        first = self.slot(self.algebra, number=3)
        second = self.slot(self.german, number=3)

        for slot in (first, second):
            codes = {one["code"] for one in self.warnings_of(slot.pk)}
            self.assertIn("slot_student_busy", codes)

    def test_the_warning_names_who_exactly(self):
        """
        «Кто-то пересекается» — сообщение, с которым нечего делать: чтобы
        починить расписание, надо знать имя.
        """
        self.enrol(self.algebra, self.ivanov)
        self.enrol(self.german, self.ivanov)
        first = self.slot(self.algebra, number=3)
        self.slot(self.german, number=3)

        (warning,) = [
            one for one in self.warnings_of(first.pk) if one["code"] == "slot_student_busy"
        ]
        self.assertEqual(warning["params"]["students"], ["Иван"])

    def test_different_students_in_the_same_hour_are_not_a_clash(self):
        """Подгруппы затем и делят, чтобы они шли одновременно."""
        self.enrol(self.algebra, self.ivanov)
        self.enrol(self.german, self.petrova)
        first = self.slot(self.algebra, number=3)
        self.slot(self.german, number=3)

        self.assertEqual(self.warnings_of(first.pk), [])

    def test_a_cancelled_lesson_holds_nobody(self):
        self.enrol(self.algebra, self.ivanov)
        self.enrol(self.german, self.ivanov)
        first = self.slot(self.algebra, number=3)
        self.slot(self.german, number=3, is_cancelled=True, reason="Карантин")

        self.assertEqual(self.warnings_of(first.pk), [])

    def test_a_student_taken_off_the_course_is_not_counted(self):
        """Снятый с курса на нём не сидит — и место в этом часе не занимает."""
        self.enrol(self.algebra, self.ivanov)
        row = self.enrol(self.german, self.ivanov)
        row.removed_at = row.created_at
        row.save(update_fields=["removed_at"])

        first = self.slot(self.algebra, number=3)
        self.slot(self.german, number=3)

        self.assertEqual(self.warnings_of(first.pk), [])

    def test_one_slot_answers_about_itself(self):
        """
        У одиночного ответа периода нет, и спросить он обязан сам — иначе
        правка часа сообщала бы «всё в порядке» там, где на экране рядом
        горит предупреждение.
        """
        self.enrol(self.algebra, self.ivanov)
        self.enrol(self.german, self.ivanov)
        self.slot(self.german, number=4)
        mine = self.slot(self.algebra, number=9)

        self.client.force_authenticate(self.admin)
        answer = self.client.patch(
            reverse("slot-detail", args=[mine.pk]),
            {"lesson_number": 4},
            format="json",
        )

        self.assertEqual(answer.status_code, 200, answer.content)
        codes = {one["code"] for one in answer.json()["warnings"]}
        self.assertIn("slot_student_busy", codes)
