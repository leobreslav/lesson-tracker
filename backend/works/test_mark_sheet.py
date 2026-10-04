"""
Лист баллов (маркгрид) в пачке: от двери чтения до оценок в журнале.

Раскладка правила проверена без базы (`test_scanning.MarkSheetRuleTests`);
здесь — что правило доезжает по всей дороге. Оборвись оно на одном шаге, и
экран показал бы одно, а в журнал записалось бы другое: например, клетки
бланков, которые на экране помечены «не в счёт».
"""

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APITestCase
from schools.services import enrol
from schools.testing import SchoolTestMixin, make_course, make_user, make_work, make_year

from . import services
from .models import Mark, ScanPage
from .scanning import MARK_CELLS
from .test_splitting import book


class MarkSheetPileTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        # двадцать задач — больше, чем клеток в шапке бланка: ради таких работ
        # лист баллов и заведён
        services.set_questions(
            self.work,
            [{"question": f"Задача {n}", "maximum": 5} for n in range(1, 21)],
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

    def read(self, index, first, surname, marks, sheet="answer"):
        cells = [None] * (MARK_CELLS if sheet == "marks" else 16)
        for question, value in marks.items():
            cells[question] = value
        services.save_scan_reading(
            self.work,
            index=index,
            fingerprint=f"f{index}",
            data={"first_name": first, "surname": surname, "values": cells},
            sheet=sheet,
        )

    def state(self):
        return self.client.get(reverse("work-scan-state", args=[self.work.pk])).json()

    def student_of(self, state, person):
        return next(one for one in state["students"] if one["id"] == person.pk)

    def pile_with_a_mark_sheet(self):
        # Сложено так, как складывают всегда: условия, лист баллов, бланки —
        # блок на ученика. У Фила на бланке черновые цифры, у Питера на листе
        # балл за задачу после пятнадцатой
        services.mark_headerless(self.work, index=0)
        self.read(1, "Fil", "Burmov", {0: 3, 17: 2}, sheet="marks")
        self.read(2, "Fil", "Burmov", {0: 1, 1: 1})
        services.mark_headerless(self.work, index=3)
        self.read(4, "Peter", "Tibora", {19: 5}, sheet="marks")
        self.read(5, "Peter", "Tibora", {0: 2})

    def test_the_marks_come_from_the_mark_sheet_and_not_from_the_blanks(self):
        self.pile_with_a_mark_sheet()

        state = self.state()

        self.assertTrue(state["marks_sheet"])
        # номера вопросов на экране — с единицы
        self.assertEqual(self.student_of(state, self.student)["marks"], {"1": 3, "18": 2})
        self.assertEqual(self.student_of(state, self.second)["marks"], {"20": 5})
        self.assertEqual(self.student_of(state, self.student)["conflicts"], [])

    def test_the_screen_is_told_which_cells_do_not_count(self):
        self.pile_with_a_mark_sheet()

        rows = {row["index"]: row for row in self.state()["pages"]}

        self.assertTrue(rows[2]["cells_ignored"])
        self.assertFalse(rows[1]["cells_ignored"])
        self.assertEqual(rows[1]["sheet"], "marks")
        # прочитанное не стирается — его показывают, оно просто никуда не едет
        self.assertEqual(rows[2]["cells"][:2], [1, 1])
        self.assertEqual(len(rows[1]["cells"]), MARK_CELLS)

    def test_the_journal_gets_the_marks_of_the_mark_sheet(self):
        self.pile_with_a_mark_sheet()
        for packet in self.state()["packets"]:
            self.client.post(
                reverse("work-scan-piece", args=[self.work.pk]),
                {
                    "student": packet["student"],
                    "file": SimpleUploadedFile(
                        "piece.pdf", book(len(packet["pages"]) + len(packet["conditions"]))
                    ),
                },
                format="multipart",
            )

        answer = self.client.post(reverse("work-scan-apply", args=[self.work.pk]))

        self.assertEqual(answer.status_code, 200, answer.content)
        written = {
            (mark.student_work.student_id, mark.task.position): mark.value
            for mark in Mark.objects.filter(student_work__work=self.work, task__isnull=False)
        }
        positions = sorted(task.position for task in self.work.tasks.all())
        self.assertEqual(
            written,
            {
                (self.student.pk, positions[0]): 3,
                (self.student.pk, positions[17]): 2,
                (self.second.pk, positions[19]): 5,
            },
        )

    def test_without_a_mark_sheet_the_blanks_give_the_marks_as_before(self):
        self.read(0, "Fil", "Burmov", {0: 1, 1: 2})

        state = self.state()

        self.assertFalse(state["marks_sheet"])
        self.assertEqual(self.student_of(state, self.student)["marks"], {"1": 1, "2": 2})

    def test_a_hand_edit_of_the_mark_sheet_keeps_all_its_cells(self):
        """Правка руками режет список по листу страницы, а не по шестнадцати."""
        self.read(1, "Fil", "Burmov", {}, sheet="marks")
        cells = [None] * MARK_CELLS
        cells[40] = 4

        self.client.post(
            reverse("work-scan-page", args=[self.work.pk]),
            {"index": 1, "cells": cells},
            format="json",
        )

        self.assertEqual(ScanPage.objects.get(work=self.work, index=1).cells[40], 4)

    def test_an_unread_mark_sheet_is_remembered_as_one(self):
        self.client.post(
            reverse("work-scan-page", args=[self.work.pk]),
            {"index": 4, "headerless": True, "ours": True, "sheet": "marks"},
            format="json",
        )

        self.assertEqual(ScanPage.objects.get(work=self.work, index=4).sheet, "marks")
        self.assertTrue(self.state()["marks_sheet"])

    def test_a_blank_after_a_mark_sheet_is_read_for_its_name_only(self):
        """
        Браузер встретил лист баллов — клетки следующих бланков не в счёт, и
        просьба «не читай клеток» доезжает до читателя нулём, а не теряется:
        иначе за выброшенные клетки платили бы на каждой странице пачки.
        """
        from works import views

        seen = {}

        def reading(**kwargs):
            seen.update(kwargs)
            return {"first_name": "Fil", "surname": "Burmov", "values": []}

        with patch.object(views.vision_services, "read_and_charge", reading):
            answer = self.client.post(
                reverse("work-scan-read", args=[self.work.pk]),
                {
                    "index": 0,
                    "strip": SimpleUploadedFile("strip.jpg", b"picture"),
                    "fingerprint": "f0",
                    "cells": "false",
                },
                format="multipart",
            )

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(seen["cell_count"], 0)

    def test_the_reading_door_asks_for_the_cells_of_the_mark_sheet(self):
        """
        Дорога, а не сервис: лист узнаёт браузер, и узнанное едет по HTTP.
        Оборвись оно, лист баллов читался бы шестнадцатью клетками, и всё,
        что после пятнадцатой задачи, пропало бы молча.
        """
        from works import views

        seen = {}

        def reading(**kwargs):
            seen.update(kwargs)
            return {"first_name": "Fil", "surname": "Burmov", "values": [None] * MARK_CELLS}

        with patch.object(views.vision_services, "read_and_charge", reading):
            answer = self.client.post(
                reverse("work-scan-read", args=[self.work.pk]),
                {
                    "index": 0,
                    "strip": SimpleUploadedFile("strip.jpg", b"picture"),
                    "fingerprint": "f0",
                    "sheet": "marks",
                },
                format="multipart",
            )

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(seen["cell_count"], MARK_CELLS)
        self.assertEqual(ScanPage.objects.get(work=self.work, index=0).sheet, "marks")


class LabelledPageTests(SchoolTestMixin, APITestCase):
    """
    Тестовый алгоритм по всей дороге: дверь чтения, плитки, правка, оценки.

    Прежний алгоритм не меняется — это сторожат все прежние тесты разбора;
    здесь — что новый доезжает до журнала по задачам, а не по местам.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        services.set_questions(
            self.work,
            [{"question": f"Задача {n}", "maximum": 5, "label": label}
             for n, label in enumerate(["1a", "1b", "2"], start=1)],
            by=self.user,
        )
        self.student.first_name, self.student.last_name = "Fil", "Burmov"
        self.student.save()
        enrol(self.student, self.course, by=self.admin)
        self.client.force_authenticate(self.user)

    def read(self, labels, values, flag="true"):
        from works import views

        seen = {}

        def reading(**kwargs):
            seen.update(kwargs)
            return {"first_name": "Fil", "surname": "Burmov", "values": values, "tile_labels": labels}

        with patch.object(views.vision_services, "read_and_charge", reading):
            answer = self.client.post(
                reverse("work-scan-read", args=[self.work.pk]),
                {
                    "index": 0,
                    "strip": SimpleUploadedFile("strip.jpg", b"picture"),
                    "fingerprint": "f0",
                    "labels": flag,
                },
                format="multipart",
            )
        self.assertEqual(answer.status_code, 200, answer.content)
        return seen

    def test_the_door_asks_for_labels_and_the_marks_land_on_their_questions(self):
        seen = self.read(["2", "1a"] + [""] * 14, [4, 1] + [None] * 13 + [5])

        self.assertTrue(seen["with_labels"])
        row = ScanPage.objects.get(work=self.work, index=0)
        self.assertTrue(row.by_labels)
        # «2» во второй клетке на бумаге — третья задача работы
        self.assertEqual(row.cells, [1, None, 4, 5])
        state = self.client.get(reverse("work-scan-state", args=[self.work.pk])).json()
        self.assertEqual(state["students"][0]["marks"], {"1": 1, "3": 4})
        self.assertEqual(state["pages"][0]["tiles"][0]["text"], "2")

    def test_the_main_algorithm_is_untouched_when_the_box_is_not_ticked(self):
        seen = self.read(None, [4, 1] + [None] * 14, flag="false")

        self.assertFalse(seen["with_labels"])
        row = ScanPage.objects.get(work=self.work, index=0)
        self.assertFalse(row.by_labels)
        self.assertEqual(row.cells[:2], [4, 1])

    def test_a_human_picks_the_question_of_a_cell_and_the_marks_follow(self):
        self.read(["4c"] + [""] * 15, [3] + [None] * 15)
        tiles = [{"task": None, "value": None}] * 16
        tiles = [{"task": 1, "value": 3}] + tiles[1:]

        self.client.post(
            reverse("work-scan-page", args=[self.work.pk]),
            {"index": 0, "tiles": tiles},
            format="json",
        )

        row = ScanPage.objects.get(work=self.work, index=0)
        self.assertEqual(row.cells, [None, 3, None, None])
        # прочитанное остаётся рядом: человек видит, что модель увидела «4c»
        self.assertEqual(row.tiles[0]["text"], "4c")

    def test_a_direct_cell_edit_cannot_bypass_the_tiles(self):
        """Правка по позициям мимо плиток развела бы скан и оценки."""
        self.read(["1a"] + [""] * 15, [2] + [None] * 15)

        self.client.post(
            reverse("work-scan-page", args=[self.work.pk]),
            {"index": 0, "cells": [5, 5, 5, 5]},
            format="json",
        )

        self.assertEqual(ScanPage.objects.get(work=self.work, index=0).cells[0], 2)
