"""
Спецсимволы в CSV учебного плана и файлы, сохранённые чем попало.

В названиях уроков запятые, кавычки и точки с запятой — обычное дело, а
разделитель файла определяется эвристикой. Здесь проверяется, что она не
путается, что кавычки и переводы строк доезжают целыми и что план,
у которого спецсимвол в каждом названии, переживает круговой прогон.

Вложенность сюда больше не относится: формат один, тема написана в каждой
строке, и угадывать нечего — это проверяет `test_csv.py`.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse

from . import services
from .tests import PlanTestCase

HEAD = "id,Тема,Урок,Заметка\n"

# план, где каждое название с запятой, кавычками и точкой с запятой
NASTY = (
    ("Дроби, обыкновенные и десятичные", "", True),
    ("Сложение и вычитание дробей, имеющих разные знаменатели", "№ 12, 13", False),
    ('Умножение «в столбик» и деление "уголком"', 'заметка со "скобками"', False),
    ("Точка с запятой; и запятая, вместе", "первая строка\nвторая строка", False),
)


class SpecialCharacterTests(SimpleTestCase):
    """Разделитель, кавычки, переводы строк."""

    def parse(self, text):
        result = services.parse_plan_csv(text)
        self.assertEqual(result.errors, [])
        return [(row.title, row.note) for row in result.rows]

    def test_a_comma_inside_a_name_does_not_split_the_cell(self):
        text = HEAD + ',"Дроби, обычные","Сложение, вычитание",\n'

        self.assertEqual(
            self.parse(text),
            [("Дроби, обычные", ""), ("Сложение, вычитание", "")],
        )

    def test_a_file_where_every_name_has_a_comma_still_reads_as_semicolons(self):
        """Русский Excel: разделитель «;», а запятые внутри значений."""
        text = (
            "id;Тема;Урок;Заметка\n"
            ';"Дроби, обычные";"Сложение, вычитание";\n'
            ';"Дроби, обычные";"Умножение, деление";\n'
            ';"Дроби, обычные";"Точка, ещё";\n'
        )

        self.assertEqual(services.sniff_delimiter(text), ";")
        self.assertEqual(
            [title for title, _ in self.parse(text)],
            ["Дроби, обычные", "Сложение, вычитание", "Умножение, деление", "Точка, ещё"],
        )

    def test_a_semicolon_inside_a_name_does_not_win_over_the_comma(self):
        text = HEAD + ',Дроби; и точки,"Урок; раз",\n,Дроби; и точки,"Урок; два",\n'

        self.assertEqual(services.sniff_delimiter(text), ",")
        self.assertEqual(
            [title for title, _ in self.parse(text)],
            ["Дроби; и точки", "Урок; раз", "Урок; два"],
        )

    def test_doubled_quotes_come_out_as_one(self):
        text = HEAD + ',Тема 1,"Урок ""в кавычках""",\n'

        self.assertEqual(self.parse(text)[1][0], 'Урок "в кавычках"')

    def test_a_newline_inside_a_note_survives_and_does_not_confuse_the_sniffer(self):
        """
        Перевод строки внутри кавычек — часть заметки, а не конец записи.

        Разделитель считается по записям именно поэтому: порезав текст по
        \\n, эвристика сравнивала бы обрывки строк.
        """
        text = (
            "id;Тема;Урок;Заметка\n"
            ';"Дроби, обычные";"Сложение, вычитание";"первая, строка\nвторая, строка"\n'
            ';"Дроби, обычные";"Умножение, деление";\n'
        )

        self.assertEqual(services.sniff_delimiter(text), ";")
        self.assertEqual(self.parse(text)[1][1], "первая, строка\nвторая, строка")

    def test_spaces_around_a_value_are_trimmed(self):
        """Предсказуемо: обрезаются всегда, а не когда как."""
        text = HEAD + " ,  Тема 1  ,  Урок 1  ,  заметка  \n"

        self.assertEqual(self.parse(text), [("Тема 1", ""), ("Урок 1", "заметка")])


class NastyRoundTripTests(PlanTestCase):
    """Экспорт → импорт на плане, где спецсимвол в каждом названии."""

    def build_nasty(self):
        section = None
        for position, (title, note, is_section) in enumerate(NASTY):
            node = self.add(
                title,
                parent=None if is_section else section,
                position=position,
                is_section=is_section,
            )
            node.note = note
            node.save(update_fields=["note"])
            if is_section:
                section = node

    def import_back(self, exported, mode="replace"):
        return self.client.post(
            f"{reverse('plannode-import')}?course={self.course.pk}",
            {
                "file": SimpleUploadedFile("plan.csv", exported, content_type="text/csv"),
                "mode": mode,
            },
            format="multipart",
        )

    def export(self, **params):
        return self.client.get(
            reverse("plannode-export"), {"course": self.course.pk, **params}
        )

    def test_the_plan_survives_a_round_trip_through_replace(self):
        self.build_nasty()
        before = self.titles_with_notes()

        response = self.import_back(self.export().content)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.titles_with_notes(), before)

    def test_the_plan_survives_a_round_trip_through_sync(self):
        self.build_nasty()
        before = self.titles_with_notes()

        response = self.import_back(self.export().content, mode="sync")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["created"], 0)
        self.assertEqual(response.json()["deleted"], 0)
        self.assertEqual(self.titles_with_notes(), before)

    def test_a_file_saved_by_russian_excel_imports(self):
        """cp1251, разделитель «;», значения в кавычках с запятыми внутри."""
        text = (
            "id;Тема;Урок;Заметка\n"
            ';"Дроби, обыкновенные";"Сложение, вычитание";"№ 12, 13"\n'
            ';"Дроби, обыкновенные";"Умножение, деление";\n'
        )

        response = self.import_back(text.encode("cp1251"))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.titles_with_notes(),
            [
                (None, "Дроби, обыкновенные", "", True),
                ("Дроби, обыкновенные", "Сложение, вычитание", "№ 12, 13", False),
                ("Дроби, обыкновенные", "Умножение, деление", "", False),
            ],
        )
