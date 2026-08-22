"""
Бумажная работа: у каждого ученика свой скан, и только свой.

Проверяется здесь одно, и оно важнее всего остального в этой подсистеме:
**ученик не видит чужую работу**. Ошибка тут — не «показали лишнее», а
контрольная одноклассника с отметками у него на экране, и заметить это
некому, кроме теста.

Сама бумажная работа — та же `Work`, у которой не задействованы задачи и
отправки. Признак явный (`on_paper`), потому что пустая онлайн-работа и
пустая бумажная в данных неразличимы, а показывать ученику надо разное.
"""

from django.urls import reverse
from files.models import Attachment
from rest_framework.test import APITestCase
from schools.services import enrol
from schools.testing import (
    SchoolTestMixin,
    make_course,
    make_stored_file,
    make_user,
    make_work,
    make_year,
)

from .models import StudentWork


class PaperTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course, on_paper=True)

        self.classmate = make_user(self.school, "classmate@example.com", student=True)
        enrol(self.student, self.course, by=self.admin)
        enrol(self.classmate, self.course, by=self.admin)

        self.mine = StudentWork.objects.create(work=self.work, student=self.student)
        self.theirs = StudentWork.objects.create(
            work=self.work, student=self.classmate
        )
        self.my_scan = Attachment.objects.create(
            student_work=self.mine,
            kind="file",
            stored_file=make_stored_file(self.school, self.user),
            title="Степанов.pdf",
        )
        self.their_scan = Attachment.objects.create(
            student_work=self.theirs,
            kind="file",
            stored_file=make_stored_file(self.school, self.user, name="second.pdf"),
            title="Одноклассник.pdf",
        )

    def download(self, attachment):
        return self.client.get(
            reverse("attachment-download", args=[attachment.pk]) + "?json=1"
        )


class OwnershipTests(PaperTestCase):
    def test_a_student_downloads_their_own_work(self):
        self.sign_in(self.student)

        answer = self.download(self.my_scan)

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertIn("url", answer.data)

    def test_a_classmates_work_does_not_exist_for_them(self):
        """
        Не «нельзя», а «нет такого»: знать, что у соседа что-то лежит, ему
        тоже незачем.
        """
        self.sign_in(self.student)

        self.assertEqual(self.download(self.their_scan).status_code, 404)

    def test_the_list_shows_a_student_only_their_own(self):
        self.sign_in(self.student)

        listing = self.client.get(reverse("attachment-list")).json()

        self.assertEqual([item["id"] for item in listing], [self.my_scan.pk])

    def test_the_teacher_of_the_course_reaches_everybody(self):
        self.assertEqual(self.download(self.my_scan).status_code, 200)
        self.assertEqual(self.download(self.their_scan).status_code, 200)

    def test_a_teacher_of_another_course_reaches_nobody(self):
        self.sign_in(self.colleague)

        self.assertEqual(self.download(self.my_scan).status_code, 403)

    def test_a_student_cannot_delete_their_own_scan(self):
        """Скан — запись учителя о работе, а не слова ученика о ней."""
        self.sign_in(self.student)

        refused = self.client.delete(
            reverse("attachment-detail", args=[self.my_scan.pk])
        )

        self.assertEqual(refused.status_code, 403)
        self.assertTrue(Attachment.objects.filter(pk=self.my_scan.pk).exists())

    def test_a_student_cannot_attach_anything_anywhere(self):
        self.sign_in(self.student)

        refused = self.client.post(
            reverse("attachment-list"),
            {"student_work": self.mine.pk, "url": "https://example.com"},
            format="json",
        )

        self.assertEqual(refused.status_code, 400, refused.content)


class UploadTests(PaperTestCase):
    def test_the_teacher_attaches_a_scan_to_one_student(self):
        response = self.client.post(
            reverse("attachment-list"),
            {"student_work": self.theirs.pk, "url": "https://example.com/scan"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.theirs.attachments.count(), 2)

    def test_a_row_of_another_course_is_not_a_valid_choice(self):
        theirs_course = make_course(self.school, self.year, "10А")
        other = make_work(self.colleague, theirs_course)
        outside = StudentWork.objects.create(work=other, student=self.student)

        refused = self.client.post(
            reverse("attachment-list"),
            {"student_work": outside.pk, "url": "https://example.com"},
            format="json",
        )

        self.assertEqual(refused.status_code, 400, refused.content)

    def test_exactly_one_owner_is_named(self):
        refused = self.client.post(
            reverse("attachment-list"),
            {"url": "https://example.com"},
            format="json",
        )

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "attachment_owner_required")


class StudentViewTests(PaperTestCase):
    def test_the_work_page_carries_the_scan(self):
        self.sign_in(self.student)

        body = self.client.get(reverse("student-work", args=[self.work.pk])).json()

        self.assertEqual(
            [item["id"] for item in body["papers"]], [self.my_scan.pk]
        )

    def test_the_scan_is_shown_even_when_results_are_hidden(self):
        """
        `show_result` — про отметку, разошедшуюся по классу. Своя исписанная
        бумага ни к кому больше не относится, и прятать её не от кого.
        """
        self.work.show_result = False
        self.work.save(update_fields=["show_result"])
        self.sign_in(self.student)

        body = self.client.get(reverse("student-work", args=[self.work.pk])).json()

        self.assertEqual(len(body["papers"]), 1)

    def test_the_teachers_table_says_who_has_a_scan(self):
        body = self.client.get(reverse("work-table", args=[self.work.pk])).json()

        papers = {row["id"]: len(row["papers"]) for row in body["students"]}
        self.assertEqual(papers[self.student.pk], 1)
        self.assertEqual(papers[self.classmate.pk], 1)

    def test_a_paper_work_says_so(self):
        self.assertTrue(
            self.client.get(reverse("work-detail", args=[self.work.pk])).json()[
                "on_paper"
            ]
        )
