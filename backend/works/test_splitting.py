"""
Разбор одного скана на работы учеников.

Разметку делает человек — где чья работа, видно только глазами, — а сервер
её проверяет и режет. Проверяет строго: ошибка тут не «неудобно», а чужая
контрольная с отметками у одноклассника, и заметить её некому.

Правило «каждая работа два листа» здесь не реализовано намеренно. Оно
ломается на первом же, кто взял третий, и ломается **молча**: съезжает весь
хвост, а на экране всё выглядит разобранным.
"""

from io import BytesIO
from json import dumps

from django.core.files.storage import storages
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

from .models import StudentWork
from .splitting import Piece, cut, read_pages


def book(pages: int) -> bytes:
    """PDF из нескольких страниц — тем же `pypdf`, что и режет."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


class SplitTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)

        self.second = make_user(self.school, "second@example.com", student=True)
        enrol(self.student, self.course, by=self.admin)
        enrol(self.second, self.course, by=self.admin)

    def split(self, plan, pages=4, name="scan.pdf", data=None):
        import json

        return self.client.post(
            reverse("work-split", args=[self.work.pk]),
            {
                "file": SimpleUploadedFile(
                    name, data if data is not None else book(pages),
                    content_type="application/pdf",
                ),
                "plan": json.dumps(plan),
            },
            format="multipart",
        )


class CuttingTests(SplitTestCase):
    def test_each_student_gets_their_own_pages(self):
        response = self.split(
            [
                {"student": self.student.pk, "first": 1, "last": 2},
                {"student": self.second.pk, "first": 3, "last": 4},
            ]
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"created": 2, "students": 2})

        mine = StudentWork.objects.get(student=self.student).attachments.get()
        with storages["files"].open(mine.stored_file.key) as saved:
            self.assertEqual(read_pages(saved.read()), 2)

    def test_pages_left_over_are_nobody_s_business(self):
        """Пустая страница в конце пачки — обычное дело, а не ошибка."""
        response = self.split([{"student": self.student.pk, "first": 1, "last": 2}])

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Attachment.objects.count(), 1)

    def test_a_student_who_was_absent_simply_has_nothing(self):
        self.split([{"student": self.student.pk, "first": 1, "last": 4}])

        self.assertFalse(
            StudentWork.objects.filter(student=self.second).exists()
        )

    def test_the_file_is_named_after_the_student(self):
        self.second.last_name = "Волкова"
        self.second.save(update_fields=["last_name"])

        self.split([{"student": self.second.pk, "first": 1, "last": 1}])

        self.assertEqual(Attachment.objects.get().title, "Волкова.pdf")


class RefusalTests(SplitTestCase):
    def test_a_page_given_to_two_students_is_refused(self):
        response = self.split(
            [
                {"student": self.student.pk, "first": 1, "last": 2},
                {"student": self.second.pk, "first": 2, "last": 3},
            ]
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "split_overlap")
        self.assertFalse(Attachment.objects.exists())

    def test_pages_outside_the_file_are_refused(self):
        response = self.split([{"student": self.student.pk, "first": 3, "last": 9}])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "split_out_of_range")

    def test_reversed_pages_are_refused(self):
        response = self.split([{"student": self.student.pk, "first": 3, "last": 1}])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "split_out_of_range")

    def test_one_student_twice_is_refused(self):
        """Два куска на человека почти всегда значат пропущенного соседа."""
        response = self.split(
            [
                {"student": self.student.pk, "first": 1, "last": 1},
                {"student": self.student.pk, "first": 2, "last": 2},
            ]
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "split_student_twice")

    def test_a_stranger_cannot_be_named(self):
        outsider = make_user(self.school, "outsider@example.com", student=True)

        response = self.split([{"student": outsider.pk, "first": 1, "last": 1}])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "split_not_in_course")

    def test_an_empty_markup_is_refused(self):
        response = self.split([])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "split_empty")

    def test_something_that_is_not_a_pdf_is_refused(self):
        response = self.split(
            [{"student": self.student.pk, "first": 1, "last": 1}],
            data=b"not a pdf at all",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "file_not_pdf")

    def test_a_work_with_online_tasks_can_be_split_too(self):
        """
        Отказа «эта работа не на бумаге» больше нет, и это не послабление.

        Класс писал онлайн, а сдал на бумаге; или учитель завёл работу
        пустой и принёс пачку. Оба случая обычные, а запирал их флаг,
        который приходилось выставить **заранее**, до того как станет
        известно, чем работа окажется.

        Мешать друг другу нечему: скан ложится на строку «работа и ученик»,
        онлайн-ответы живут на отправках.
        """
        online = make_work(self.user, self.course, title="Онлайн")

        response = self.client.post(
            reverse("work-split", args=[online.pk]),
            {
                "file": SimpleUploadedFile("s.pdf", book(1)),
                "plan": dumps([{"student": self.student.pk, "first": 1, "last": 1}]),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(
            StudentWork.objects.filter(work=online, student=self.student).exists()
        )

    def test_nothing_is_written_when_one_piece_is_wrong(self):
        """Половина разобранной пачки хуже неразобранной."""
        self.split(
            [
                {"student": self.student.pk, "first": 1, "last": 2},
                {"student": self.second.pk, "first": 3, "last": 99},
            ]
        )

        self.assertFalse(StudentWork.objects.exists())
        self.assertFalse(Attachment.objects.exists())


class ReassignTests(SplitTestCase):
    def setUp(self):
        super().setUp()
        self.split([{"student": self.student.pk, "first": 1, "last": 2}])
        self.paper = Attachment.objects.get()

    def test_a_misplaced_work_moves_to_its_owner(self):
        """
        Ошибка в разборе — чужая контрольная у одноклассника, и исправляться
        она должна одним движением, иначе исправлять будут «потом».
        """
        response = self.client.post(
            reverse("work-reassign", args=[self.work.pk]),
            {"attachment": self.paper.pk, "student": self.second.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.student_work.student, self.second)

    def test_the_file_itself_is_not_copied(self):
        before = self.paper.stored_file_id

        self.client.post(
            reverse("work-reassign", args=[self.work.pk]),
            {"attachment": self.paper.pk, "student": self.second.pk},
            format="json",
        )

        self.paper.refresh_from_db()
        self.assertEqual(self.paper.stored_file_id, before)

    def test_an_attachment_of_another_work_cannot_be_moved_here(self):
        other = make_work(self.user, self.course, title="Другая")
        row = StudentWork.objects.create(work=other, student=self.second)
        alien = Attachment.objects.create(
            student_work=row, kind="link", url="https://example.com", title="x"
        )

        response = self.client.post(
            reverse("work-reassign", args=[self.work.pk]),
            {"attachment": alien.pk, "student": self.student.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class PureTests(SchoolTestMixin, APITestCase):
    """Резка — чистая функция: байты в байты, без базы и запросов."""

    def test_a_piece_carries_exactly_its_pages(self):
        data = book(5)

        piece = cut(data, Piece(student_id=1, first=2, last=4))

        self.assertEqual(read_pages(piece), 3)

    def test_a_single_page_piece_is_a_single_page(self):
        self.assertEqual(read_pages(cut(book(3), Piece(1, 2, 2))), 1)
