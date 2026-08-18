"""
Массовый ввод состава курса: разбор текста и что он делает с базой.

Разбор проверяется без базы — он чистая функция, — а решения и запись через
API, потому что именно там сходятся права, курс из query-строки и
транзакция.
"""

from accounts.models import Kind
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APITestCase
from schedule.models import CourseStudent

from . import roster
from .models import Invitation
from .services import enrol, remove_from_course
from .testing import (
    SchoolTestMixin,
    make_course,
    make_school,
    make_user,
    make_year,
    sign_in,
)

User = get_user_model()


# --- разбор: три формата и отказ вместо угадывания -----------------------------------


class ParseTests(APITestCase):
    def parse(self, text):
        return roster.parse_roster(text)

    def test_a_bare_address_is_a_person(self):
        parsed = self.parse("ivanov@school.ru\npetrov@school.ru")

        self.assertEqual([person.email for person in parsed.people],
                         ["ivanov@school.ru", "petrov@school.ru"])
        self.assertEqual([person.name for person in parsed.people], ["", ""])
        self.assertEqual(parsed.errors, [])

    def test_a_name_comes_with_the_address_in_any_column(self):
        """Порядок столбцов не задан: в выгрузках адрес бывает и первым."""
        parsed = self.parse(
            "Иванов Пётр, ivanov@school.ru\n"
            "petrov@school.ru;Петров Иван\n"
            "Сидоров\tАнна\tsidorova@school.ru"
        )

        self.assertEqual(
            [(person.email, person.name) for person in parsed.people],
            [
                ("ivanov@school.ru", "Иванов Пётр"),
                ("petrov@school.ru", "Петров Иван"),
                ("sidorova@school.ru", "Сидоров Анна"),
            ],
        )

    def test_the_address_is_lowercased(self):
        parsed = self.parse("Ivan.Petrov@School.RU")

        self.assertEqual(parsed.people[0].email, "ivan.petrov@school.ru")

    def test_angle_brackets_come_off(self):
        """«Пётр <petrov@school.ru>» — как это приезжает из почты."""
        parsed = self.parse("Пётр <petrov@school.ru>")

        self.assertEqual(parsed.people[0].email, "petrov@school.ru")

    def test_empty_lines_are_skipped_and_repeats_collapse(self):
        parsed = self.parse("\n\nivanov@school.ru\n \nIVANOV@school.ru\n,\n")

        self.assertEqual(len(parsed.people), 1)
        self.assertEqual(parsed.duplicates, 1)
        self.assertEqual(parsed.rows, 2)

    def test_a_line_without_an_address_is_refused_by_its_number(self):
        parsed = self.parse("ivanov@school.ru\nПетров Иван\n")

        self.assertEqual([person.email for person in parsed.people],
                         ["ivanov@school.ru"])
        self.assertEqual(parsed.errors[0]["code"], "roster_no_email")
        self.assertEqual(parsed.errors[0]["params"]["line"], 2)

    def test_two_addresses_in_one_line_are_refused(self):
        parsed = self.parse("ivanov@school.ru petrov@school.ru")

        self.assertEqual(parsed.errors[0]["code"], "roster_two_emails")

    def test_a_broken_address_is_refused(self):
        parsed = self.parse("Пётр, petrov@@school")

        self.assertEqual(parsed.errors[0]["code"], "roster_bad_email")
        self.assertEqual(parsed.people, [])

    def test_a_whole_spreadsheet_row_is_refused_rather_than_guessed(self):
        """Пятый столбец — это класс, телефон или оценка, а не имя."""
        parsed = self.parse("Иванов\tПётр\t6А\t89990000000\tivanov@school.ru")

        self.assertEqual(parsed.errors[0]["code"], "roster_too_many_columns")
        self.assertEqual(parsed.errors[0]["params"]["columns"], 5)


# --- что вставка сделает с базой ------------------------------------------------------


class RosterTestCase(APITestCase):
    def setUp(self):
        self.school = make_school()
        self.admin = make_user(self.school, "admin@school.ru", admin=True)
        self.course = make_course(self.school)
        sign_in(self.client, self.admin)

    def preview(self, text, course=None):
        return self.client.post(
            reverse("coursestudent-preview"),
            {"text": text},
            format="json",
            QUERY_STRING=f"course={(course or self.course).pk}",
        )

    def enrol_all(self, text, course=None):
        return self.client.post(
            reverse("coursestudent-enrol"),
            {"text": text},
            format="json",
            QUERY_STRING=f"course={(course or self.course).pk}",
        )

    def student(self, email, school=None, **kwargs):
        return make_user(
            school if school is not None else self.school,
            email,
            student=True,
            **kwargs,
        )


class PreviewTests(RosterTestCase):
    def test_it_names_five_outcomes(self):
        known = self.student("known@school.ru")
        back = self.student("back@school.ru")
        already = self.student("already@school.ru")
        teacher = make_user(self.school, "teacher@school.ru")
        enrol(already, self.course)
        remove_from_course(enrol(back, self.course))

        answer = self.preview(
            "\n".join(
                [
                    known.email,
                    back.email,
                    already.email,
                    "newcomer@school.ru",
                    teacher.email,
                ]
            )
        ).json()

        self.assertEqual(
            {key: answer[key] for key in ("enrol", "restore", "already", "invite", "blocked")},
            {"enrol": 1, "restore": 1, "already": 1, "invite": 1, "blocked": 1},
        )
        self.assertEqual(answer["rows"], 5)

    def test_it_writes_nothing(self):
        self.student("known@school.ru")

        self.preview("known@school.ru\nnewcomer@school.ru")

        self.assertEqual(CourseStudent.objects.count(), 0)
        self.assertEqual(Invitation.objects.count(), 0)

    def test_a_blocked_address_says_whose_it_is(self):
        make_user(self.school, "teacher@school.ru")

        answer = self.preview("teacher@school.ru").json()

        self.assertEqual(answer["people"][0]["action"], "blocked")
        self.assertEqual(answer["people"][0]["code"], "email_other_kind")

    def test_a_student_of_another_school_is_blocked(self):
        other = make_school("Другая")
        self.student("elsewhere@school.ru", school=other)

        answer = self.preview("elsewhere@school.ru").json()

        self.assertEqual(answer["people"][0]["code"], "already_member")

    def test_it_refuses_nothing_and_returns_errors_in_the_body(self):
        """Отказ кодом 400 был бы виден только в консоли браузера."""
        answer = self.preview("Петров Иван\nnewcomer@school.ru")

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()["errors"][0]["code"], "roster_no_email")
        self.assertEqual(answer.json()["invite"], 1)

    def test_the_name_of_an_existing_account_wins_over_the_pasted_one(self):
        person = self.student("known@school.ru")
        person.first_name, person.last_name = "Пётр", "Иванов"
        person.save()

        answer = self.preview("Кто-то Другой, known@school.ru").json()

        self.assertEqual(answer["people"][0]["name"], "Пётр Иванов")

    def test_the_number_of_queries_does_not_grow_with_the_list(self):
        for index in range(3):
            self.student(f"one{index}@school.ru")
        short = "\n".join(f"one{index}@school.ru" for index in range(3))

        for index in range(3, 12):
            self.student(f"one{index}@school.ru")
        long = "\n".join(f"one{index}@school.ru" for index in range(12))

        with self.assertNumQueries(len(self.captureQueries(short))):
            self.preview(long)

    def captureQueries(self, text):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as captured:
            self.preview(text)
        return captured.captured_queries


class EnrolTests(RosterTestCase):
    def test_it_enrols_restores_and_invites_in_one_go(self):
        known = self.student("known@school.ru")
        back = self.student("back@school.ru")
        remove_from_course(enrol(back, self.course))

        answer = self.enrol_all(
            f"{known.email}\n{back.email}\nПётр Новый, newcomer@school.ru"
        ).json()

        self.assertEqual(
            (answer["enrol"], answer["restore"], answer["invite"]), (1, 1, 1)
        )
        self.assertEqual(
            set(
                CourseStudent.objects.filter(
                    course=self.course, removed_at__isnull=True
                ).values_list("student__email", flat=True)
            ),
            {known.email, back.email},
        )

        invitation = Invitation.objects.get(email="newcomer@school.ru")
        self.assertEqual(invitation.kind, Kind.STUDENT)
        self.assertEqual(invitation.name, "Пётр Новый")
        self.assertEqual(list(invitation.courses.all()), [self.course])

    def test_a_second_course_lands_in_the_same_invitation(self):
        other = make_course(self.school, year=self.course.year, name="9А")

        self.enrol_all("newcomer@school.ru")
        self.enrol_all("newcomer@school.ru", course=other)

        invitation = Invitation.objects.get(email="newcomer@school.ru")
        self.assertEqual(
            set(invitation.courses.values_list("name", flat=True)),
            {self.course.name, other.name},
        )

    def test_a_busy_address_does_not_cancel_the_rest(self):
        """Про занятый сказано поимённо; остальные ни в чём не виноваты."""
        make_user(self.school, "teacher@school.ru")

        answer = self.enrol_all("teacher@school.ru\nnewcomer@school.ru").json()

        self.assertEqual((answer["blocked"], answer["invite"]), (1, 1))
        self.assertTrue(Invitation.objects.filter(email="newcomer@school.ru").exists())

    def test_a_line_it_cannot_read_cancels_the_whole_paste(self):
        """Половина применённого списка хуже неприменённого."""
        answer = self.enrol_all("Петров Иван\nnewcomer@school.ru")

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.json()["code"], "roster_no_email")
        self.assertEqual(Invitation.objects.count(), 0)

    def test_nothing_pasted_is_refused_too(self):
        answer = self.enrol_all("   \n\n")

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.json()["code"], "roster_empty")

    def test_the_invitation_enrols_at_the_first_sign_in(self):
        from .services import accept, pending_for

        self.enrol_all("newcomer@school.ru")
        newcomer = User.objects.create_user(email="newcomer@school.ru")

        accept(newcomer, pending_for("newcomer@school.ru"))

        newcomer.refresh_from_db()
        self.assertEqual(newcomer.kind, Kind.STUDENT)
        self.assertEqual(newcomer.school, self.school)
        self.assertTrue(
            CourseStudent.objects.filter(
                course=self.course, student=newcomer, removed_at__isnull=True
            ).exists()
        )

    def test_a_teacher_of_the_school_cannot_paste_a_roster(self):
        """Состав курса — школьный объект: правит его администратор."""
        sign_in(self.client, make_user(self.school, "colleague@school.ru"))

        answer = self.enrol_all("newcomer@school.ru")

        self.assertEqual(answer.status_code, 403)
        self.assertEqual(Invitation.objects.count(), 0)


class ConflictMarkTests(RosterTestCase):
    """
    Приглашение, которое уже никогда не сработает, помечается на чтении.

    Проверка на вводе всё, кроме одного случая, закрывает: два приглашения в
    разные школы, написанные до первого входа. Побеждает первый вход.
    """

    def test_an_address_that_went_to_another_school_is_marked(self):
        self.enrol_all("newcomer@school.ru")
        # тем временем человек вошёл и оказался в другой школе
        other = make_school("Другая")
        make_user(other, "newcomer@school.ru", student=True)

        rows = self.client.get(reverse("invitation-list")).json()

        self.assertEqual(rows[0]["conflict"], "already_member")

    def test_an_ordinary_invitation_is_not_marked(self):
        self.enrol_all("newcomer@school.ru")

        rows = self.client.get(reverse("invitation-list")).json()

        self.assertIsNone(rows[0]["conflict"])

    def test_the_list_can_be_narrowed_to_one_course(self):
        other = make_course(self.school, year=self.course.year, name="9А")
        self.enrol_all("here@school.ru")
        self.enrol_all("there@school.ru", course=other)

        rows = self.client.get(
            reverse("invitation-list"), {"course": self.course.pk, "kind": "student"}
        ).json()

        self.assertEqual([row["email"] for row in rows], ["here@school.ru"])


class PendingTeacherApiTests(SchoolTestMixin, APITestCase):
    """
    Приглашённому учителю курс поручают через само приглашение.

    Учётки ещё нет, назначению не на кого встать — а нагрузку раздают уже
    сейчас. Поэтому у приглашения правятся курсы, и карточка курса
    показывает такого человека отдельной плашкой: место занято, но пока
    обещанием.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        self.invitation = Invitation.objects.create(
            school=self.school,
            email="newcomer@example.com",
            name="Новенький",
            kind="teacher",
            created_by=self.admin,
        )
        self.client.force_authenticate(self.admin)

    def attach(self, courses):
        return self.client.patch(
            reverse("invitation-detail", args=[self.invitation.pk]),
            {"courses": courses},
            format="json",
        )

    def test_a_course_is_attached_to_an_invitation(self):
        response = self.attach([self.course.pk])

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            [course.pk for course in self.invitation.courses.all()], [self.course.pk]
        )

    def test_the_course_card_names_who_is_expected(self):
        self.attach([self.course.pk])

        response = self.client.get(reverse("course-detail", args=[self.course.pk]))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json()["pending_teachers"],
            [
                {
                    "invitation": self.invitation.pk,
                    "name": "Новенький",
                    "email": "newcomer@example.com",
                }
            ],
        )

    def test_an_accepted_invitation_stops_being_pending(self):
        """Вошёл — плашка ожидания уходит, на её место встаёт назначение."""
        self.attach([self.course.pk])
        self.invitation.accepted_at = timezone.now()
        self.invitation.save(update_fields=["accepted_at"])

        response = self.client.get(reverse("course-detail", args=[self.course.pk]))

        self.assertEqual(response.json()["pending_teachers"], [])

    def test_a_student_invitation_is_not_a_pending_teacher(self):
        self.invitation.kind = "student"
        self.invitation.save(update_fields=["kind"])
        self.attach([self.course.pk])

        response = self.client.get(reverse("course-detail", args=[self.course.pk]))

        self.assertEqual(response.json()["pending_teachers"], [])

    def test_the_address_is_not_editable(self):
        """Адрес — то, за что поручились: сменить его значит выписать другое."""
        response = self.client.patch(
            reverse("invitation-detail", args=[self.invitation.pk]),
            {"email": "someone.else@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.email, "newcomer@example.com")

    def test_detaching_is_the_same_patch_with_the_course_left_out(self):
        self.attach([self.course.pk])

        self.attach([])

        self.assertFalse(self.invitation.courses.exists())

    def test_a_teacher_without_the_role_cannot_hand_out_load(self):
        self.client.force_authenticate(self.user)

        response = self.attach([self.course.pk])

        self.assertEqual(response.status_code, 403)
