"""
Применение разобранной пачки: страницы ученикам, клетки в оценки.

Проверяется то, что нельзя увидеть по частям: применение либо случилось
целиком, либо не случилось вовсе. Половина применённой пачки — это часть
класса с работами и оценками, а часть без, и какая именно, снаружи не видно.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from files.models import Attachment
from rest_framework.test import APITestCase
from schools.services import enrol
from schools.testing import (
    SchoolTestMixin,
    make_course,
    make_user,
    make_work,
    make_year,
)

from . import services
from .models import Mark, ScanPage, StudentWork
from .test_splitting import book


class ScanApplyTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course, on_paper=True)
        services.set_questions(
            self.work,
            [{"question": f"Задача {n}", "maximum": 3} for n in range(1, 4)],
            by=self.user,
        )

        self.student.first_name, self.student.last_name = "Fil", "Burmov"
        self.student.save()
        self.second = make_user(self.school, "second@example.com", student=True)
        self.second.first_name, self.second.last_name = "Peter", "Tibora"
        self.second.save()
        enrol(self.student, self.course, by=self.admin)
        enrol(self.second, self.course, by=self.admin)

        self.client.force_authenticate(self.user)

    def read(self, index, first, surname, marks):
        cells = [None] * 16
        for question, value in marks.items():
            cells[question] = value
        services.save_scan_reading(
            self.work,
            index=index,
            fingerprint=f"f{index}",
            data={"first_name": first, "surname": surname, "values": cells},
        )

    def apply(self, pages=2):
        return self.client.post(
            reverse("work-scan-apply", args=[self.work.pk]),
            {"file": SimpleUploadedFile("scan.pdf", book(pages))},
            format="multipart",
        )

    def test_pages_become_attachments_and_cells_become_marks(self):
        self.read(0, "Fil", "Burmov", {0: 3, 1: 1})
        self.read(1, "Peter", "Tibora", {0: 2})

        response = self.apply()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["students"], 2)
        mine = StudentWork.objects.get(work=self.work, student=self.student)
        self.assertEqual(Attachment.objects.filter(student_work=mine).count(), 1)
        self.assertEqual(
            sorted(Mark.objects.filter(student_work=mine).values_list("value", flat=True)),
            [1, 3],
        )

    def test_two_pages_of_one_student_go_into_one_file(self):
        """Работа это один кусок, сколько бы листов она ни заняла."""
        self.read(0, "Fil", "Burmov", {0: 3})
        self.read(1, "", "", {2: 2})

        self.apply()

        mine = StudentWork.objects.get(work=self.work, student=self.student)
        self.assertEqual(Attachment.objects.filter(student_work=mine).count(), 1)
        self.assertEqual(
            sorted(Mark.objects.filter(student_work=mine).values_list("value", flat=True)),
            [2, 3],
        )

    def test_conditions_go_into_the_students_file(self):
        """
        Листы условий едут в PDF вместе с решением.

        Иначе ученик открывает свои ответы без вопросов — половину документа,
        — а ради того, чтобы он видел работу целиком, скан ему и отдают.
        """
        services.mark_headerless(self.work, index=0)
        self.read(1, "Fil", "Burmov", {0: 3})
        services.mark_headerless(self.work, index=2)
        self.read(3, "Peter", "Tibora", {0: 2})

        response = self.apply(pages=4)

        self.assertEqual(response.status_code, 200)
        mine = StudentWork.objects.get(work=self.work, student=self.student)
        paper = Attachment.objects.get(student_work=mine)
        from io import BytesIO

        from files import storage
        from pypdf import PdfReader

        with storage.backend().open(paper.stored_file.key) as fp:
            self.assertEqual(len(PdfReader(BytesIO(fp.read())).pages), 2)

    def test_the_rows_are_gone_once_it_is_applied(self):
        """Работа сделана: дальше про неё отвечают вложения и оценки."""
        self.read(0, "Fil", "Burmov", {0: 3})

        self.apply()

        self.assertFalse(ScanPage.objects.filter(work=self.work).exists())

    def test_a_page_outside_the_file_stops_everything(self):
        """Прочитали больше страниц, чем прислали, — не применяем ничего."""
        self.read(0, "Fil", "Burmov", {0: 3})
        self.read(5, "Peter", "Tibora", {0: 1})

        response = self.apply(pages=2)

        self.assertEqual(response.json()["code"], "split_out_of_range")
        self.assertFalse(Attachment.objects.filter(student_work__work=self.work).exists())
        self.assertTrue(ScanPage.objects.filter(work=self.work).exists())

    def test_nothing_read_is_refused(self):
        response = self.apply()

        self.assertEqual(response.json()["code"], "scan_nothing_read")

    def test_a_human_decision_survives_into_the_marks(self):
        """Сказали «эта страница Петра» — баллы уходят ему, а не тому, чьё имя."""
        self.read(0, "Fil", "Burmov", {0: 3})
        self.client.post(
            reverse("work-scan-page", args=[self.work.pk]),
            {"index": 0, "student": self.second.pk},
            format="json",
        )

        self.apply()

        theirs = StudentWork.objects.get(work=self.work, student=self.second)
        self.assertEqual(
            list(Mark.objects.filter(student_work=theirs).values_list("value", flat=True)),
            [3],
        )
        self.assertFalse(
            StudentWork.objects.filter(work=self.work, student=self.student).exists()
        )

    def test_an_online_work_has_nothing_to_scan(self):
        online = make_work(self.user, self.course)

        response = self.client.get(reverse("work-scan-state", args=[online.pk]))

        self.assertEqual(response.json()["code"], "not_on_paper")
