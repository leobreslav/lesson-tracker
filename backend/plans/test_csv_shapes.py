"""
Вложенность и спецсимволы в CSV учебного плана.

Два разбирательства в одном файле, потому что оба про одно: файл говорит о
структуре плана ровно то, что в нём написано, и ничего сверх.

**Вложенность.** У формата два стиля. В привычном тема стоит отдельной
строкой-заголовком, а уроки под ней идут с пустой ячейкой темы; в
«протянутом» тема повторяется в каждой строке урока. Пустая ячейка темы
означает «урок вне темы» только во втором — и определяется это по самому
файлу, а не по наличию столбца id. Пока определялось по id, человек,
выгрузивший план и поправивший его в привычном стиле, получал пустые темы и
все уроки на верхнем уровне.

**Спецсимволы.** В названиях уроков запятые — обычное дело, а разделитель
файла определяется эвристикой. Здесь проверяется, что она не путается, и
что кавычки, точки с запятой и переводы строк доезжают целыми.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse

from . import services
from .tests import PlanTestCase

# план, где каждое название с запятой, кавычками и точкой с запятой
NASTY = (
    ("Дроби, обыкновенные и десятичные", "тема; важная", True),
    ("Сложение и вычитание дробей, имеющих разные знаменатели", "№ 12, 13", False),
    ('Умножение «в столбик» и деление "уголком"', 'заметка со "скобками"', False),
    ("Точка с запятой; и запятая, вместе", "первая строка\nвторая строка", False),
)


def shape(rows):
    """Строки разбора как «тема / урок», с пометкой «вне темы»."""
    out = []
    for row in rows:
        if row.is_section:
            out.append(("тема", row.title))
        else:
            out.append(("урок вне темы" if row.at_top_level else "урок", row.title))
    return out


class NestingTests(SimpleTestCase):
    """Разбор: в какой стиль написан файл и что из этого следует."""

    CLASSIC = "Тема 1,,\n,Урок 1,\n,Урок 2,\nТема 2,,\n,Урок 3,\n"
    CLASSIC_WITH_IDS = (
        "id,Тема,Урок,Заметка\n"
        ",Тема 1,,\n,,Урок 1,\n,,Урок 2,\n,Тема 2,,\n,,Урок 3,\n"
    )
    SPREAD = "Тема,Урок\nТема 1,Урок 1\nТема 1,Урок 2\nТема 2,Урок 3\n"

    EXPECTED = [
        ("тема", "Тема 1"),
        ("урок", "Урок 1"),
        ("урок", "Урок 2"),
        ("тема", "Тема 2"),
        ("урок", "Урок 3"),
    ]

    def test_lessons_go_under_the_theme_above_them(self):
        self.assertEqual(shape(services.parse_plan_csv(self.CLASSIC).rows), self.EXPECTED)

    def test_the_id_column_does_not_change_what_an_empty_theme_means(self):
        """
        Тот же файл со столбцом id читается так же.

        Пока пустая тема при наличии id значила «вне темы», выгруженный и
        поправленный руками план приезжал обратно плоским: темы пустые,
        уроки на верхнем уровне.
        """
        parsed = services.parse_plan_csv(self.CLASSIC_WITH_IDS)

        self.assertTrue(parsed.has_ids)
        self.assertEqual(shape(parsed.rows), self.EXPECTED)

    def test_the_spread_format_gives_the_same_tree(self):
        self.assertEqual(shape(services.parse_plan_csv(self.SPREAD).rows), self.EXPECTED)

    def test_a_repeated_theme_makes_an_empty_cell_mean_outside(self):
        """
        И только в таком файле. Тема написана у первых уроков, значит
        пустая ячейка у последнего — утверждение, а не умолчание.
        """
        text = (
            "id,Тема,Урок,Заметка\n"
            "1,Тема 1,,\n2,Тема 1,Урок 1,\n3,,Повторение,\n"
        )

        self.assertEqual(
            shape(services.parse_plan_csv(text).rows),
            [("тема", "Тема 1"), ("урок", "Урок 1"), ("урок вне темы", "Повторение")],
        )

    def test_a_file_without_a_single_filled_pair_falls_back_to_classic(self):
        """
        Известный предел, доставшийся от трёхстолбцового формата.

        Стиль виден по строкам, где тема и урок написаны рядом. Если в
        файле нет ни одной такой строки — а так выглядит выгрузка плана, ни
        у одной темы которого нет уроков, — свидетельств не осталось, и
        пустая ячейка читается по-привычному: «внутри темы выше». Урок
        верхнего уровня, стоящий после пустой темы, при обратном импорте
        уедет внутрь неё.
        """
        text = "id,Тема,Урок,Заметка\n1,Тема 1,,\n2,,Урок,\n"

        self.assertEqual(
            shape(services.parse_plan_csv(text).rows),
            [("тема", "Тема 1"), ("урок", "Урок")],
        )

    def test_lessons_before_the_first_theme_stay_at_the_top(self):
        text = ",Повторение,\nТема 1,,\n,Урок 1,\n"

        rows = services.parse_plan_csv(text).rows

        self.assertEqual(
            shape(rows), [("урок", "Повторение"), ("тема", "Тема 1"), ("урок", "Урок 1")]
        )


class SpecialCharacterTests(SimpleTestCase):
    """Разделитель, кавычки, переводы строк."""

    def parse(self, text):
        return [(row.title, row.note) for row in services.parse_plan_csv(text).rows]

    def test_a_comma_inside_a_name_does_not_split_the_cell(self):
        text = 'Тема,Урок,Заметка\n"Дроби, обычные",,\n,"Сложение, вычитание",\n'

        self.assertEqual(
            self.parse(text),
            [("Дроби, обычные", ""), ("Сложение, вычитание", "")],
        )

    def test_a_file_where_every_name_has_a_comma_still_reads_as_semicolons(self):
        """Русский Excel: разделитель «;», а запятые внутри значений."""
        text = (
            "Тема;Урок;Заметка\n"
            '"Дроби, обычные";;\n'
            ';"Сложение, вычитание";\n'
            ';"Умножение, деление";\n'
            ';"Точка, ещё";\n'
        )

        self.assertEqual(services.sniff_delimiter(text), ";")
        self.assertEqual(
            [title for title, _ in self.parse(text)],
            ["Дроби, обычные", "Сложение, вычитание", "Умножение, деление", "Точка, ещё"],
        )

    def test_a_semicolon_inside_a_name_does_not_win_over_the_comma(self):
        text = 'Тема,Урок,Заметка\nДроби; и точки,,\n,"Урок; раз",\n,"Урок; два",\n'

        self.assertEqual(services.sniff_delimiter(text), ",")
        self.assertEqual(
            [title for title, _ in self.parse(text)],
            ["Дроби; и точки", "Урок; раз", "Урок; два"],
        )

    def test_doubled_quotes_come_out_as_one(self):
        text = 'Тема,Урок,Заметка\nТема 1,,\n,"Урок ""в кавычках""",\n'

        self.assertEqual(self.parse(text)[1][0], 'Урок "в кавычках"')

    def test_a_newline_inside_a_note_survives_and_does_not_confuse_the_sniffer(self):
        """
        Перевод строки внутри кавычек — часть заметки, а не конец записи.

        Разделитель считается по записям именно поэтому: порезав текст по
        \\n, эвристика сравнивала бы обрывки строк.
        """
        text = 'Тема;Урок;Заметка\n"Дроби, обычные";;"первая, строка\nвторая, строка"\n;"Сложение, вычитание";\n'

        self.assertEqual(services.sniff_delimiter(text), ";")
        self.assertEqual(self.parse(text)[0][1], "первая, строка\nвторая, строка")

    def test_spaces_around_a_value_are_trimmed(self):
        """Предсказуемо: обрезаются всегда, а не когда как."""
        text = "Тема,Урок,Заметка\n  Тема 1  ,,\n,  Урок 1  ,  заметка  \n"

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

    def import_back(self, exported):
        return self.client.post(
            f"{reverse('plannode-import')}?course={self.course.pk}",
            {
                "file": SimpleUploadedFile("plan.csv", exported, content_type="text/csv"),
                "mode": "replace",
            },
            format="multipart",
        )

    def export(self, **params):
        return self.client.get(
            reverse("plannode-export"), {"course": self.course.pk, **params}
        )

    def test_the_plan_survives_a_round_trip_unchanged(self):
        self.build_nasty()
        before = self.titles_with_notes()

        response = self.import_back(self.export().content)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.titles_with_notes(), before)

    def test_the_same_without_the_id_column(self):
        self.build_nasty()
        before = self.titles_with_notes()

        response = self.import_back(self.export(with_ids="false").content)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.titles_with_notes(), before)

    def test_a_file_saved_by_russian_excel_imports(self):
        """cp1251, разделитель «;», значения в кавычках с запятыми внутри."""
        text = (
            "Тема;Урок;Заметка\n"
            '"Дроби, обыкновенные";;\n'
            ';"Сложение, вычитание";"№ 12, 13"\n'
            ';"Умножение, деление";\n'
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
