"""
Бланк с подписями задач.

Проверяется не то, что PDF собрался, а то, ради чего он собирается: **подпись
стоит в полосе своей клетки**. Съехавшая на клетку подпись хуже отсутствующей
— учитель впишет балл за «2c» в клетку «2b», и на бумаге это не заметит никто.
"""

import re
from io import BytesIO

from django.urls import reverse
from pypdf import PdfReader
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin

from . import blank

MM = 25.4 / 72
PAGE_HEIGHT = 297


def positions(labels):
    """
    Где встали строки подписей: (x, y) в мм от левого верхнего угла.

    Читается сам поток команд накладки, а не `extract_text`: его обходчик
    отдаёт текст с опозданием и приписывает ему положение **следующего**
    блока — у всех подписей, кроме первой, выходил ноль.
    """
    layer = PdfReader(BytesIO(blank.overlay(blank.clean(labels)))).pages[0]
    stream = layer.get_contents().get_data().decode("latin1")
    return [
        (float(x) * MM, PAGE_HEIGHT - float(y) * MM)
        for x, y in re.findall(r"BT ([\d.]+) ([\d.]+) Td", stream)
    ]


def cell_of(x):
    return int((x - blank.GRID_X) // blank.CELL_WIDTH)


def page_texts(content):
    return [page.extract_text() for page in PdfReader(BytesIO(content)).pages]


class BlankRenderTests(APITestCase):
    def test_each_label_sits_in_the_band_of_its_own_cell(self):
        labels = [""] * 15
        labels[0], labels[2], labels[14] = "1а", "Жук", "ЯЯ"

        found = positions(labels)

        self.assertEqual([cell_of(x) for x, _ in found], [0, 2, 14])
        for x, y in found:
            self.assertGreater(y, blank.GRID_Y, (x, y))
            self.assertLess(y, blank.GRID_Y + blank.LABEL_HEIGHT, (x, y))

    def test_both_pages_carry_the_labels(self):
        """Лицо и оборот у бланка одинаковые, и подписи нужны на обоих."""
        texts = page_texts(blank.render(["Жук"]))

        self.assertEqual(len(texts), 2)
        for text in texts:
            self.assertIn("Жук", text)

    def test_a_long_name_wraps_instead_of_being_cut(self):
        """«324 из Галицкого» — обычное имя задачи, и на бумаге оно должно быть целиком."""
        found = positions(["324 из Галицкого"])
        text = page_texts(blank.render(["324 из Галицкого"]))[0]

        self.assertEqual([cell_of(x) for x, _ in found], [0, 0])
        self.assertIn("Галицкого", text)

    def test_a_label_that_cannot_fit_is_refused_by_name_not_trimmed(self):
        with self.assertRaises(Exception) as caught:
            blank.render(["", "Ааааааааааааааа"])

        self.assertEqual(caught.exception.detail["code"], "blank_label_too_long")
        self.assertEqual(caught.exception.detail["params"]["cell"], 2)

    def test_there_are_fifteen_cells_and_not_more(self):
        with self.assertRaises(Exception) as caught:
            blank.render(["x"] * 16)

        self.assertEqual(caught.exception.detail["code"], "blank_labels_invalid")


class BlankViewTests(SchoolTestMixin, APITestCase):
    def test_a_teacher_gets_a_pdf(self):
        self.client.force_authenticate(self.user)

        answer = self.client.post(
            reverse("work-blank"), {"labels": ["1а", "1б"]}, format="json"
        )

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer["Content-Type"], "application/pdf")
        self.assertTrue(answer.content.startswith(b"%PDF"))

    def test_a_student_does_not(self):
        self.client.force_authenticate(self.student)

        answer = self.client.post(reverse("work-blank"), {"labels": []}, format="json")

        self.assertEqual(answer.status_code, 403)

    def test_a_refusal_arrives_with_its_code(self):
        self.client.force_authenticate(self.user)

        answer = self.client.post(
            reverse("work-blank"), {"labels": "1а"}, format="json"
        )

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "blank_labels_invalid")
