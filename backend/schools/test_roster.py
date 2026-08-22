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
    def test_it_names_every_outcome(self):
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
            {key: answer[key] for key in ("enrol", "restore", "already", "new", "blocked")},
            {"enrol": 1, "restore": 1, "already": 1, "new": 1, "blocked": 1},
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
        self.assertEqual(answer.json()["new"], 1)

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
    def test_it_enrols_restores_and_creates_in_one_go(self):
        known = self.student("known@school.ru")
        back = self.student("back@school.ru")
        remove_from_course(enrol(back, self.course))

        answer = self.enrol_all(
            f"{known.email}\n{back.email}\nПётр Новый, newcomer@school.ru"
        ).json()

        self.assertEqual(
            (answer["enrol"], answer["restore"], answer["new"]), (1, 1, 1)
        )
        # новичок зачислен наравне с остальными: учётку ему завели тут же
        self.assertEqual(
            set(
                CourseStudent.objects.filter(
                    course=self.course, removed_at__isnull=True
                ).values_list("student__email", flat=True)
            ),
            {known.email, back.email, "newcomer@school.ru"},
        )

        person = User.objects.get(email="newcomer@school.ru")
        self.assertTrue(person.is_student)
        self.assertEqual(person.school, self.school)
        self.assertIsNone(person.last_login, "он ещё ни разу не входил")
        self.assertEqual(person.first_name, "Пётр Новый", "ярлык до первого входа")

        # билет остался следом в истории
        invitation = Invitation.objects.get(email="newcomer@school.ru")
        self.assertEqual(invitation.kind, Kind.STUDENT)
        self.assertEqual(invitation.name, "Пётр Новый")

    def test_a_second_course_reuses_the_same_person(self):
        """Второй курс — второе зачисление, а не второй человек."""
        other = make_course(self.school, year=self.course.year, name="9А")

        self.enrol_all("newcomer@school.ru")
        self.enrol_all("newcomer@school.ru", course=other)

        self.assertEqual(User.objects.filter(email="newcomer@school.ru").count(), 1)
        person = User.objects.get(email="newcomer@school.ru")
        self.assertEqual(
            set(person.enrolments.values_list("course__name", flat=True)),
            {self.course.name, other.name},
        )

    def test_a_busy_address_does_not_cancel_the_rest(self):
        """Про занятый сказано поимённо; остальные ни в чём не виноваты."""
        make_user(self.school, "teacher@school.ru")

        answer = self.enrol_all("teacher@school.ru\nnewcomer@school.ru").json()

        self.assertEqual((answer["blocked"], answer["new"]), (1, 1))
        self.assertTrue(User.objects.filter(email="newcomer@school.ru").exists())

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

    def test_the_first_sign_in_only_stamps_the_ticket(self):
        """
        Вход больше ничего не раздаёт: школа, вид и курс уже стоят.

        Раньше здесь применялось всё сразу — и это была единственная точка,
        где человек становился участником. Теперь она только помечает, что
        учётку забрали.
        """
        from .services import accept, pending_for

        self.enrol_all("newcomer@school.ru")
        newcomer = User.objects.get(email="newcomer@school.ru")
        self.assertEqual(newcomer.school, self.school)

        invitation = pending_for("newcomer@school.ru")
        self.assertTrue(accept(newcomer, invitation))

        newcomer.refresh_from_db()
        invitation.refresh_from_db()
        self.assertEqual(newcomer.kind, Kind.STUDENT)
        self.assertIsNotNone(invitation.accepted_at)
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


class OneSchoolPerAddressTests(RosterTestCase):
    """
    Случая «два приглашения в разные школы» больше не бывает.

    Он был единственным, который нельзя было проверить на вводе: пока
    приглашение было записанным адресом, вторая школа могла записать тот же
    адрес, а побеждал первый вход. Приглашение висело вечно и молча,
    поэтому его помечали на чтении полем `conflict`.

    Теперь приглашение заводит учётку, адрес у неё уникален, и второй
    записи просто не получится — отказ приходит там, где ошибку и делают.
    """

    def test_a_second_school_is_refused_at_the_door(self):
        self.enrol_all("newcomer@school.ru")
        other = make_school("Другая")
        outsider = make_user(other, "boss@other.ru", admin=True)
        sign_in(self.client, outsider)

        answer = self.client.post(
            reverse("invitation-list"),
            {"email": "newcomer@school.ru", "kind": "student"},
            format="json",
        )

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.json()["code"], "already_member")
        self.assertEqual(User.objects.filter(email="newcomer@school.ru").count(), 1)


class InvitedTeacherApiTests(SchoolTestMixin, APITestCase):
    """
    Приглашение заводит учителя целиком — до его первого входа.

    Раньше учётки не было, назначению не на кого было встать, и курс
    приходилось нести в самом приглашении до первого входа. Теперь человек
    появляется в момент ввода адреса: его видно в списках, ему можно
    поручить курс обычной таблицей, и отличает его только пустой
    `last_login`.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        self.client.force_authenticate(self.admin)

    def invite(self, email="newcomer@example.com", **extra):
        return self.client.post(
            reverse("invitation-list"),
            {"email": email, "name": "Новенький", "kind": "teacher", **extra},
            format="json",
        )

    def test_inviting_creates_the_account(self):
        answer = self.invite()

        self.assertEqual(answer.status_code, 201, answer.content)
        person = User.objects.get(email="newcomer@example.com")
        self.assertEqual(person.school, self.school)
        self.assertFalse(person.is_student)
        self.assertIsNone(person.last_login)
        self.assertEqual(person.first_name, "Новенький", "ярлык до первого входа")
        self.assertFalse(person.has_usable_password(), "войти можно только Google")

    def test_the_account_shows_up_among_the_members_as_not_yet_arrived(self):
        self.invite()

        rows = self.client.get(reverse("member-list")).json()

        row = next(item for item in rows if item["email"] == "newcomer@example.com")
        self.assertFalse(row["arrived"])
        self.assertTrue(
            all(item["arrived"] for item in rows if item["email"] != row["email"]),
            "у остальных пометки ожидания быть не должно",
        )

    def test_the_course_is_handed_over_by_the_ordinary_assignment(self):
        self.invite()
        person = User.objects.get(email="newcomer@example.com")

        answer = self.client.post(
            reverse("courseassignment-list"),
            {"course": self.course.pk, "teacher": person.pk},
            format="json",
        )

        self.assertEqual(answer.status_code, 201, answer.content)
        self.assertEqual(self.course.assignments.get().teacher, person)

    def test_the_admin_role_comes_with_the_account(self):
        self.invite(email="boss@example.com", is_school_admin=True)

        self.assertTrue(User.objects.get(email="boss@example.com").is_school_admin)

    def test_a_teacher_without_the_role_cannot_invite(self):
        self.client.force_authenticate(self.user)

        answer = self.invite()

        self.assertEqual(answer.status_code, 403)
        self.assertFalse(User.objects.filter(email="newcomer@example.com").exists())
