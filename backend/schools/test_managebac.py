"""
Выгрузка ManageBac по курсу: разбор файла и что он делает с базой.

Разбор проверяется на строках ячеек — он чистая функция, — а решения и
запись через API, потому что именно там сходятся права, курс из
query-строки, файл и транзакция.
"""

import io

from accounts.models import Kind
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from families.models import Guardianship
from openpyxl import Workbook
from rest_framework.test import APITestCase
from schedule.models import CourseStudent

from . import managebac
from .models import Invitation
from .services import enrol, remove_from_course
from .testing import make_course, make_school, make_user, sign_in

User = get_user_model()

HEADER = [
    "Student ID", "First Name", "Middle Name", "Last Name", "Preferred Name",
    "Other Name", "Phone Number", "E-mail Address", "Gender", "Date of Birth",
    "National ID",
    "Parent 1 Last Name", "Parent 1 First Name", "Parent 1 Phone Number",
    "Parent 1 E-mail address",
    "Parent 2 Last Name", "Parent 2 First Name", "Parent 2 Phone Number",
    "Parent 2 E-mail address",
    "Parent 3 Last Name", "Parent 3 First Name", "Parent 3 Phone Number",
    "Parent 3 E-mail address",
]


def pupil_row(
    student_id, first, last, email, *parents, phone="+7 999 000-00-00",
    born="2014-05-01",
):
    """
    Строка выгрузки: ученик и до трёх родителей тройками (фамилия, имя,
    адрес). Телефон и дата рождения заполнены нарочно — их не читаем.
    """
    row = [student_id, first, "", last, "", "", phone, email, "F", born, "ID-1"]
    for last_name, first_name, address in parents:
        row += [last_name, first_name, phone, address]
    return row


def sheet_rows(*pupils, group="IB MYP Mathematics 1 (Grade 6)"):
    """Раскладка, которую отдаёт ManageBac: школа, группа, полосы, шапка."""
    return [
        ["Lumio Private School"],
        [group],
        [""],
        ["Students Information"] + [""] * 10 + ["Parents Information"],
        HEADER,
        *pupils,
    ]


def workbook(*pupils, **kwargs) -> bytes:
    book = Workbook()
    sheet = book.active
    for row in sheet_rows(*pupils, **kwargs):
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


MUM = ("Иванова", "Мария", "mum@example.com")
DAD = ("Иванов", "Сергей", "dad@example.com")


# --- разбор: столбцы по заголовкам, отказ вместо угадывания ---------------------


class ParseTests(APITestCase):
    def parse(self, *pupils, **kwargs):
        return managebac.parse_rows(sheet_rows(*pupils, **kwargs))

    def test_a_row_is_a_student_with_their_parents(self):
        parsed = self.parse(pupil_row(412, "Пётр", "Иванов", "Petr@School.ru", MUM, DAD))

        self.assertEqual(parsed.errors, [])
        self.assertEqual(parsed.group, "IB MYP Mathematics 1 (Grade 6)")
        [pupil] = parsed.pupils
        self.assertEqual(
            (pupil.external_id, pupil.first, pupil.last, pupil.email),
            ("412", "Пётр", "Иванов", "petr@school.ru"),
        )
        self.assertEqual(
            [(adult.first, adult.last, adult.email) for adult in pupil.parents],
            [("Мария", "Иванова", "mum@example.com"), ("Сергей", "Иванов", "dad@example.com")],
        )

    def test_the_header_is_found_by_its_words_and_not_by_its_row(self):
        rows = [["что-то сверху"]] * 7 + sheet_rows(
            pupil_row(1, "А", "Б", "ab@example.com")
        )

        parsed = managebac.parse_rows(rows)

        self.assertEqual(len(parsed.pupils), 1)

    def test_without_the_header_the_file_is_refused_whole(self):
        parsed = managebac.parse_rows([["Иванов", "ivanov@example.com"]])

        self.assertEqual(parsed.errors[0]["code"], "roster_header_missing")
        self.assertEqual(parsed.pupils, [])

    def test_a_student_without_an_address_is_refused_by_the_line(self):
        parsed = self.parse(pupil_row(1, "Пётр", "Иванов", ""))

        self.assertEqual(parsed.errors[0]["code"], "roster_no_email")
        self.assertEqual(parsed.errors[0]["params"]["line"], 6)

    def test_empty_rows_and_repeats_do_not_count(self):
        parsed = self.parse(
            pupil_row(1, "А", "Б", "ab@example.com"),
            [""] * 23,
            pupil_row(1, "А", "Б", "AB@example.com"),
        )

        self.assertEqual(len(parsed.pupils), 1)
        self.assertEqual(parsed.duplicates, 1)
        self.assertEqual(parsed.rows, 2)

    def test_a_parent_without_an_address_is_a_warning_and_not_a_refusal(self):
        parsed = self.parse(
            pupil_row(1, "А", "Б", "ab@example.com", ("Иванова", "Мария", ""))
        )

        self.assertEqual(parsed.errors, [])
        self.assertEqual(parsed.warnings[0]["code"], "roster_parent_no_email")
        self.assertEqual(parsed.pupils[0].parents, [])

    def test_a_parent_with_the_students_own_address_is_skipped(self):
        parsed = self.parse(
            pupil_row(1, "А", "Б", "ab@example.com", ("Б", "А", "ab@example.com"))
        )

        self.assertEqual(parsed.warnings[0]["code"], "roster_parent_is_student")
        self.assertEqual(parsed.pupils[0].parents, [])

    def test_the_same_parent_in_two_slots_is_one_parent(self):
        parsed = self.parse(pupil_row(1, "А", "Б", "ab@example.com", MUM, MUM))

        self.assertEqual(len(parsed.pupils[0].parents), 1)

    def test_a_workbook_that_is_not_one_is_a_single_error(self):
        parsed = managebac.parse_workbook(b"not a zip", filename="list.xlsx")

        self.assertEqual(parsed.errors[0]["code"], "file_not_xlsx")


# --- что файл сделает с базой ---------------------------------------------------------


class UploadTestCase(APITestCase):
    def setUp(self):
        self.school = make_school()
        self.admin = make_user(self.school, "admin@school.ru", admin=True)
        self.course = make_course(self.school)
        sign_in(self.client, self.admin)

    def call(self, name, *pupils, course=None, remove_missing=None, **kwargs):
        data = {
            "file": SimpleUploadedFile(
                "Students.xlsx",
                workbook(*pupils, **kwargs),
                content_type=(
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"
                ),
            )
        }
        if remove_missing is not None:
            data["remove_missing"] = "true" if remove_missing else "false"
        return self.client.post(
            reverse(name),
            data,
            format="multipart",
            QUERY_STRING=f"course={(course or self.course).pk}",
        )

    def preview(self, *pupils, **kwargs):
        return self.call("coursestudent-upload-preview", *pupils, **kwargs)

    def upload(self, *pupils, **kwargs):
        return self.call("coursestudent-upload", *pupils, **kwargs)

    def student(self, email, school=None, **kwargs):
        return make_user(
            school if school is not None else self.school, email, student=True, **kwargs
        )

    def parent(self, email, **kwargs):
        return make_user(self.school, email, parent=True, **kwargs)


class PreviewTests(UploadTestCase):
    def test_it_names_every_outcome_for_students_and_parents(self):
        enrolled = self.student("already@example.com")
        enrol(enrolled, self.course)
        removed = self.student("back@example.com")
        remove_from_course(enrol(removed, self.course))
        self.student("free@example.com")
        self.student("elsewhere@example.com", school=make_school("Other"))
        mum = self.parent("mum@example.com")
        Guardianship.objects.create(parent=mum, child=enrolled)

        answer = self.preview(
            pupil_row(1, "А", "Б", "already@example.com", MUM),
            pupil_row(2, "В", "Г", "back@example.com", MUM),
            pupil_row(3, "Д", "Е", "free@example.com", DAD),
            pupil_row(4, "Ж", "З", "new@example.com", ("Учительская", "Анна", "admin@school.ru")),
            pupil_row(5, "И", "К", "elsewhere@example.com", DAD),
        ).json()

        actions = {person["email"]: person["action"] for person in answer["people"]}
        self.assertEqual(
            actions,
            {
                "already@example.com": "already",
                "back@example.com": "restore",
                "free@example.com": "enrol",
                "new@example.com": "new",
                "elsewhere@example.com": "blocked",
            },
        )
        parents = {
            person["email"]: [(adult["email"], adult["action"]) for adult in person["parents"]]
            for person in answer["people"]
        }
        self.assertEqual(parents["already@example.com"], [("mum@example.com", "linked")])
        self.assertEqual(parents["back@example.com"], [("mum@example.com", "link")])
        self.assertEqual(parents["free@example.com"], [("dad@example.com", "new")])
        # адрес учителя родительским быть не может — родитель пропущен, а
        # ребёнок при этом заводится
        self.assertEqual(parents["new@example.com"], [("admin@school.ru", "blocked")])
        self.assertEqual(parents["elsewhere@example.com"], [("dad@example.com", "skipped")])
        self.assertEqual(answer["parents"], {"new": 1, "link": 1, "linked": 1, "blocked": 1, "skipped": 1})

    def test_it_writes_nothing(self):
        before = (User.objects.count(), CourseStudent.objects.count())

        self.preview(pupil_row(1, "А", "Б", "new@example.com", MUM))

        self.assertEqual((User.objects.count(), CourseStudent.objects.count()), before)

    def test_it_returns_errors_in_the_body_rather_than_refusing(self):
        answer = self.preview(pupil_row(1, "А", "Б", ""))

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(answer.json()["errors"][0]["code"], "roster_no_email")

    def test_it_lists_who_would_leave_the_course(self):
        staying = self.student("stay@example.com")
        leaving = self.student("gone@example.com")
        enrol(staying, self.course)
        enrol(leaving, self.course)

        answer = self.preview(pupil_row(1, "А", "Б", "stay@example.com")).json()

        self.assertEqual(
            [person["email"] for person in answer["leaving_people"]],
            ["gone@example.com"],
        )
        self.assertTrue(answer["remove_missing"])

    def test_a_changed_address_is_recognised_by_the_student_id(self):
        old = self.student("old@example.com")
        old.external_id = "412"
        old.save()
        enrol(old, self.course)

        answer = self.preview(pupil_row(412, "А", "Б", "new@example.com")).json()

        [person] = answer["people"]
        self.assertEqual((person["action"], person["previous_email"]), ("already", "old@example.com"))
        self.assertEqual(answer["renamed"], 1)
        # человек упомянут номером, значит снимать его не за что
        self.assertEqual(answer["leaving_people"], [])

    def test_two_accounts_behind_one_row_are_a_conflict(self):
        by_number = self.student("one@example.com")
        by_number.external_id = "412"
        by_number.save()
        self.student("two@example.com")

        answer = self.preview(pupil_row(412, "А", "Б", "two@example.com")).json()

        [person] = answer["people"]
        self.assertEqual((person["action"], person["code"]), ("blocked", "roster_id_conflict"))

    def test_an_address_recorded_under_another_number_is_a_conflict(self):
        known = self.student("one@example.com")
        known.external_id = "412"
        known.save()

        answer = self.preview(pupil_row(999, "А", "Б", "one@example.com")).json()

        self.assertEqual(answer["people"][0]["code"], "roster_id_conflict")

    def test_a_student_number_of_another_school_is_a_coincidence(self):
        other = self.student("other@example.com", school=make_school("Other"))
        other.external_id = "412"
        other.save()

        answer = self.preview(pupil_row(412, "А", "Б", "new@example.com")).json()

        self.assertEqual(answer["people"][0]["action"], "new")

    def test_the_number_of_queries_does_not_grow_with_the_list(self):
        rows = [
            pupil_row(n, "А", f"Б{n}", f"pupil{n}@example.com", ("Р", "М", f"mum{n}@example.com"))
            for n in range(1, 4)
        ]
        with self.assertNumQueries(7) as small:
            self.preview(*rows)
        rows = [
            pupil_row(n, "А", f"Б{n}", f"pupil{n}@example.com", ("Р", "М", f"mum{n}@example.com"))
            for n in range(1, 31)
        ]
        with self.assertNumQueries(len(small.captured_queries)):
            self.preview(*rows)


class UploadTests(UploadTestCase):
    def test_it_enrols_students_and_links_their_parents_in_one_go(self):
        free = self.student("free@example.com")

        answer = self.upload(
            pupil_row(412, "Пётр", "Иванов", "new@example.com", MUM, DAD),
            pupil_row(413, "Анна", "Иванова", "free@example.com", MUM),
        )

        self.assertEqual(answer.status_code, 200, answer.content)
        new = User.objects.get(email="new@example.com")
        self.assertEqual((new.kind, new.school_id, new.external_id), (Kind.STUDENT, self.school.pk, "412"))
        self.assertEqual((new.first_name, new.last_name), ("Пётр", "Иванов"))
        self.assertFalse(new.has_usable_password())
        self.assertTrue(CourseStudent.objects.filter(course=self.course, student=new, removed_at=None).exists())
        self.assertTrue(CourseStudent.objects.filter(course=self.course, student=free, removed_at=None).exists())

        mum = User.objects.get(email="mum@example.com")
        dad = User.objects.get(email="dad@example.com")
        self.assertEqual((mum.kind, mum.school_id), (Kind.PARENT, self.school.pk))
        self.assertEqual((mum.first_name, mum.last_name), ("Мария", "Иванова"))
        # мама у обоих детей — одна учётка, две связи
        self.assertEqual(set(Guardianship.objects.filter(parent=mum).values_list("child", flat=True)), {new.pk, free.pk})
        self.assertEqual(list(Guardianship.objects.filter(parent=dad).values_list("child", flat=True)), [new.pk])
        # билет и след: приглашение выписано и ученику, и родителям
        self.assertEqual(
            set(Invitation.objects.filter(school=self.school).values_list("email", "kind")),
            {("new@example.com", "student"), ("mum@example.com", "parent"), ("dad@example.com", "parent")},
        )
        free.refresh_from_db()
        self.assertEqual(free.external_id, "413")

    def test_a_second_upload_of_the_same_file_changes_nothing(self):
        row = pupil_row(1, "Пётр", "Иванов", "new@example.com", MUM, DAD)
        self.upload(row)
        before = (
            User.objects.count(),
            CourseStudent.objects.count(),
            Guardianship.objects.count(),
            Invitation.objects.count(),
        )

        answer = self.upload(row).json()

        self.assertEqual(
            (User.objects.count(), CourseStudent.objects.count(), Guardianship.objects.count(), Invitation.objects.count()),
            before,
        )
        self.assertEqual(answer["already"], 1)
        self.assertEqual(answer["parents"]["linked"], 2)

    def test_whoever_is_not_in_the_file_is_taken_off_the_course(self):
        gone = self.student("gone@example.com")
        enrol(gone, self.course)

        self.upload(pupil_row(1, "А", "Б", "stay@example.com"))

        row = CourseStudent.objects.get(student=gone)
        self.assertIsNotNone(row.removed_at)
        # строка осталась: это след того, что человек здесь учился
        self.assertTrue(CourseStudent.objects.filter(student=gone).exists())

    def test_the_removal_can_be_declined(self):
        gone = self.student("gone@example.com")
        enrol(gone, self.course)

        self.upload(pupil_row(1, "А", "Б", "stay@example.com"), remove_missing=False)

        self.assertIsNone(CourseStudent.objects.get(student=gone).removed_at)

    def test_a_changed_address_moves_the_account_and_not_the_person(self):
        old = self.student("old@example.com")
        old.external_id = "412"
        old.save()
        enrol(old, self.course)

        self.upload(pupil_row(412, "А", "Б", "new@example.com"))

        old.refresh_from_db()
        self.assertEqual(old.email, "new@example.com")
        self.assertEqual(User.objects.filter(kind=Kind.STUDENT).count(), 1)
        self.assertIsNone(CourseStudent.objects.get(student=old).removed_at)

    def test_the_name_of_somebody_who_already_signed_in_is_theirs(self):
        arrived = self.student("kid@example.com")
        arrived.first_name, arrived.last_name = "Настоящее", "Имя"
        arrived.save()

        self.upload(pupil_row(1, "Из", "Файла", "kid@example.com"))

        arrived.refresh_from_db()
        self.assertEqual((arrived.first_name, arrived.last_name), ("Настоящее", "Имя"))

    def test_the_label_of_somebody_who_has_not_signed_in_follows_the_file(self):
        waiting = self.student("kid@example.com")
        waiting.last_login = None
        waiting.first_name = "Ярлык"
        waiting.save()

        self.upload(pupil_row(1, "Пётр", "Иванов", "kid@example.com"))

        waiting.refresh_from_db()
        self.assertEqual((waiting.first_name, waiting.last_name), ("Пётр", "Иванов"))

    def test_a_blocked_parent_does_not_block_the_child(self):
        answer = self.upload(
            pupil_row(1, "А", "Б", "kid@example.com", ("Учительская", "Анна", "admin@school.ru"))
        )

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertTrue(User.objects.filter(email="kid@example.com", kind=Kind.STUDENT).exists())
        self.assertEqual(Guardianship.objects.count(), 0)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.kind, Kind.TEACHER)

    def test_a_row_it_cannot_read_cancels_the_whole_upload(self):
        answer = self.upload(
            pupil_row(1, "А", "Б", "ok@example.com"),
            pupil_row(2, "В", "Г", ""),
        )

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.json()["code"], "roster_no_email")
        self.assertFalse(User.objects.filter(email="ok@example.com").exists())

    def test_a_parent_who_signed_in_before_being_invited_is_adopted(self):
        stray = make_user(None, "mum@example.com")

        self.upload(pupil_row(1, "А", "Б", "kid@example.com", MUM))

        stray.refresh_from_db()
        self.assertEqual((stray.kind, stray.school_id), (Kind.PARENT, self.school.pk))
        self.assertEqual(User.objects.filter(email="mum@example.com").count(), 1)
        self.assertTrue(Guardianship.objects.filter(parent=stray).exists())

    def test_an_adopted_parent_of_two_children_is_linked_to_both(self):
        """
        Учётка без школы принимается первой строкой, а вторая строка того же
        родителя видит её ещё в старом виде — экземпляр из выборки плана.
        Связывать надо принятую, иначе `link` откажет: «не родитель».
        """
        stray = make_user(None, "mum@example.com")

        answer = self.upload(
            pupil_row(1, "А", "Б", "kid1@example.com", MUM),
            pupil_row(2, "В", "Б", "kid2@example.com", MUM),
        )

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(Guardianship.objects.filter(parent=stray).count(), 2)

    def test_without_a_file_it_says_so(self):
        answer = self.client.post(
            reverse("coursestudent-upload"),
            {},
            format="multipart",
            QUERY_STRING=f"course={self.course.pk}",
        )

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.json()["code"], "file_required")

    def test_a_teacher_without_the_role_cannot_upload(self):
        teacher = make_user(self.school, "teacher@school.ru")
        sign_in(self.client, teacher)

        answer = self.upload(pupil_row(1, "А", "Б", "kid@example.com"))

        self.assertEqual(answer.status_code, 403)
