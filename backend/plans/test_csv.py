"""Импорт и экспорт учебного плана через CSV."""

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse

from . import services
from .models import PlanNode
from .tests import PlanTestCase

PLAIN = """Тема,Урок,Заметка
Тригонометрические формулы,,
,Синус и косинус суммы,
,Тангенс суммы,
Векторы,,
,Понятие вектора,повторить из 8 класса
"""

SPREAD = """Тема,Урок
Тригонометрия,Синус
Тригонометрия,Косинус
Векторы,Понятие вектора
"""


def parsed(rows):
    return [("тема" if row.is_section else "урок", row.title) for row in rows]


class ParseTests(SimpleTestCase):
    def parse(self, text):
        # разбор отдаёт ещё и признак «в файле есть столбец id»; тестам
        # этого раздела он не нужен, они про трёхстолбцовый формат
        parsed_file = services.parse_plan_csv(text)
        return parsed_file.rows, parsed_file.warnings

    def test_empty_cells_format(self):
        rows, warnings = self.parse(PLAIN)

        self.assertEqual(
            parsed(rows),
            [
                ("тема", "Тригонометрические формулы"),
                ("урок", "Синус и косинус суммы"),
                ("урок", "Тангенс суммы"),
                ("тема", "Векторы"),
                ("урок", "Понятие вектора"),
            ],
        )
        self.assertEqual(rows[-1].note, "повторить из 8 класса")
        self.assertEqual(warnings, [])

    def test_spread_format_creates_headers_on_change(self):
        rows, _ = self.parse(SPREAD)

        self.assertEqual(
            parsed(rows),
            [
                ("тема", "Тригонометрия"),
                ("урок", "Синус"),
                ("урок", "Косинус"),
                ("тема", "Векторы"),
                ("урок", "Понятие вектора"),
            ],
        )

    def test_header_is_optional(self):
        rows, _ = self.parse("Векторы,,\n,Понятие вектора,\n")

        self.assertEqual(parsed(rows), [("тема", "Векторы"), ("урок", "Понятие вектора")])

    def test_header_is_recognised_case_insensitively(self):
        rows, _ = self.parse("ТЕМА;УРОК;ЗАМЕТКА\nВекторы;;\n")

        self.assertEqual(parsed(rows), [("тема", "Векторы")])

    def test_first_row_that_only_looks_like_data_is_kept(self):
        rows, _ = self.parse("Векторы,Понятие вектора\n")

        self.assertEqual(parsed(rows), [("тема", "Векторы"), ("урок", "Понятие вектора")])

    def test_lessons_before_the_first_header_have_no_theme(self):
        rows, _ = self.parse(",Повторение,\n,Входная контрольная,\nВекторы,,\n,Понятие,\n")

        self.assertEqual(
            parsed(rows),
            [
                ("урок", "Повторение"),
                ("урок", "Входная контрольная"),
                ("тема", "Векторы"),
                ("урок", "Понятие"),
            ],
        )

    def test_semicolon_delimiter(self):
        rows, _ = self.parse("Векторы;;\n;Понятие вектора;повторить\n")

        self.assertEqual(parsed(rows), [("тема", "Векторы"), ("урок", "Понятие вектора")])
        self.assertEqual(rows[1].note, "повторить")

    def test_spaces_are_trimmed_and_extra_columns_ignored(self):
        rows, _ = self.parse("  Векторы  ,,,лишнее\n, Понятие  ,  заметка ,ещё\n")

        self.assertEqual(rows[0].title, "Векторы")
        self.assertEqual(rows[1].title, "Понятие")
        self.assertEqual(rows[1].note, "заметка")

    def test_blank_lines_are_skipped_without_warnings(self):
        rows, warnings = self.parse("Векторы,,\n\n,Понятие,\n\n\n")

        self.assertEqual(len(rows), 2)
        self.assertEqual(warnings, [])

    def test_row_without_theme_and_lesson_warns(self):
        rows, warnings = self.parse("Векторы,,\n,,только заметка\n")

        self.assertEqual(len(rows), 1)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["code"], "csv_row_empty")
        self.assertEqual(warnings[0]["params"]["row"], 2)

    def test_too_long_title_is_skipped_with_a_warning(self):
        rows, warnings = self.parse(f",{'о' * 201},\n")

        self.assertEqual(rows, [])
        self.assertEqual(warnings[0]["code"], "csv_row_too_long")

    def test_row_limit_is_reported(self):
        text = "\n".join(f",Урок {index}," for index in range(2100))

        with self.assertRaises(services.PlanImportError) as caught:
            self.parse(text)

        self.assertIn("2000", str(caught.exception))


class DecodeTests(SimpleTestCase):
    def test_utf8(self):
        self.assertEqual(services.decode_csv("Векторы".encode()), "Векторы")

    def test_utf8_with_bom(self):
        data = "﻿Тема,Урок\n".encode()

        # BOM не должен попасть в первую ячейку, иначе шапка не распознается
        self.assertEqual(services.decode_csv(data), "Тема,Урок\n")

    def test_cp1251(self):
        data = "Векторы;;\n;Понятие;\n".encode("cp1251")

        rows = services.parse_plan_csv(services.decode_csv(data)).rows

        self.assertEqual(parsed(rows), [("тема", "Векторы"), ("урок", "Понятие")])

    def test_unreadable_file(self):
        with self.assertRaises(services.PlanImportError):
            services.decode_csv(b"\xff\xfe\x00\x00\xd8\x00")

    def test_delimiter_sniffing(self):
        self.assertEqual(services.sniff_delimiter("a;b;c\n1;2;3"), ";")
        self.assertEqual(services.sniff_delimiter("a,b,c\n1,2,3"), ",")
        # запятые внутри значений не должны перевешивать
        self.assertEqual(services.sniff_delimiter("Тема;Урок\nА, Б, В;урок"), ";")


class ImportApiTests(PlanTestCase):
    def upload(self, text, mode="replace", course=None, encoding="utf-8"):
        payload = text.encode(encoding)
        return self.client.post(
            f"{reverse('plannode-import')}?course={(course or self.course).pk}",
            {
                "file": SimpleUploadedFile("plan.csv", payload, content_type="text/csv"),
                "mode": mode,
            },
            format="multipart",
        )

    def titles(self):
        return self.structure()

    def test_import_creates_the_tree(self):
        response = self.upload(PLAIN)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json(),
            {
                "created_rows": 5,
                "created_headers": 2,
                "created_lessons": 3,
                "warnings": [],
            },
        )
        self.assertEqual(
            self.titles(),
            [
                "Тригонометрические формулы",
                "  Синус и косинус суммы",
                "  Тангенс суммы",
                "Векторы",
                "  Понятие вектора",
            ],
        )

    def test_positions_are_dense(self):
        self.upload(PLAIN)

        self.assertEqual(self.positions(), [0, 1])
        self.assertEqual(self.positions(self.node("Векторы")), [0])

    def test_replace_wipes_the_old_plan(self):
        self.build_sample()

        self.upload(PLAIN, mode="replace")

        self.assertNotIn("Тригонометрия", "".join(self.titles()))
        self.assertEqual(len(self.titles()), 5)

    def test_append_keeps_the_old_plan(self):
        self.build_sample()
        before = len(self.titles())

        response = self.upload(PLAIN, mode="append")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(self.titles()), before + 5)
        self.assertEqual(self.titles()[0], "Тригонометрия")
        self.assertEqual(self.titles()[-1], "  Понятие вектора")
        self.assertEqual(self.positions(), [0, 1, 2, 3, 4, 5, 6])

    def test_cp1251_file(self):
        response = self.upload("Векторы;;\n;Понятие;\n", encoding="cp1251")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.titles(), ["Векторы", "  Понятие"])

    def test_bom_file(self):
        response = self.upload("﻿Тема,Урок,Заметка\nВекторы,,\n,Понятие,\n")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.titles(), ["Векторы", "  Понятие"])

    def test_warnings_are_returned(self):
        response = self.upload("Векторы,,\n,,только заметка\n,Понятие,\n")

        self.assertEqual(response.json()["created_rows"], 2)
        self.assertEqual(len(response.json()["warnings"]), 1)

    def test_broken_file_leaves_everything_untouched(self):
        """Сбой на середине импорта не должен оставить полплана."""
        self.build_sample()
        before = self.titles()

        with patch.object(
            PlanNode.objects, "create", side_effect=RuntimeError("база упала")
        ):
            with self.assertRaises(RuntimeError):
                self.upload(PLAIN)

        self.assertEqual(self.titles(), before)

    def test_unreadable_file_does_not_wipe_the_plan(self):
        self.build_sample()
        before = self.titles()

        response = self.client.post(
            f"{reverse('plannode-import')}?course={self.course.pk}",
            {
                "file": SimpleUploadedFile(
                    "plan.csv", b"\xff\xfe\x00\x00\xd8\x00", content_type="text/csv"
                ),
                "mode": "replace",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "file_unreadable")
        self.assertEqual(self.titles(), before)

    def test_row_limit_gives_a_clear_error(self):
        text = "\n".join(f",Урок {index}," for index in range(2100))

        response = self.upload(text)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "file_unreadable")
        self.assertIn("2000", response.json()["detail"])
        self.assertFalse(PlanNode.objects.filter(teacher=self.user, course=self.course).exists())

    def test_missing_file_is_rejected(self):
        response = self.client.post(
            f"{reverse('plannode-import')}?course={self.course.pk}",
            {"mode": "replace"},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)

    def test_bad_mode_is_rejected(self):
        self.assertEqual(self.upload(PLAIN, mode="wipe").status_code, 400)

    def test_cannot_import_into_another_users_class(self):
        response = self.upload(PLAIN, course=self.alien_class)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(PlanNode.objects.filter(course=self.alien_class).exists())

    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.upload(PLAIN).status_code, 401)


class ExportApiTests(PlanTestCase):
    def export(self, course=None, **params):
        return self.client.get(
            reverse("plannode-export"),
            {"course": (course or self.course).pk, **params},
        )

    def text(self, response):
        return response.content.decode("utf-8-sig")

    def test_export_has_bom_and_header(self):
        self.build_sample()

        response = self.export()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(self.text(response).splitlines()[0], "id,Тема,Урок,Заметка")

    def test_export_mirrors_the_tree(self):
        self.build_sample()

        lines = self.text(self.export(with_ids="false")).splitlines()

        self.assertEqual(
            lines[1:6],
            [
                "Тригонометрия,,",
                ",Синус суммы,",
                ",Косинус суммы,",
                "Векторы,,",
                ",Понятие вектора,",
            ],
        )

    def test_ids_can_be_left_out_for_somebody_else(self):
        self.build_sample()

        plain = self.text(self.export(with_ids="false"))

        self.assertEqual(plain.splitlines()[0], "Тема,Урок,Заметка")
        # столбца id нет вовсе, а не пустой: чужие id ничего не значат
        self.assertNotIn(",,,", plain)

    def test_filename_carries_the_class_and_date(self):
        response = self.export()

        disposition = response["Content-Disposition"]
        self.assertIn("filename*=UTF-8''", disposition)
        self.assertIn("%D0%BF%D0%BB%D0%B0%D0%BD", disposition)  # «план»

    def test_export_of_an_empty_plan_is_just_the_header(self):
        self.assertEqual(self.text(self.export()).strip(), "id,Тема,Урок,Заметка")

    def test_round_trip_gives_the_same_plan(self):
        self.build_sample()
        # уроки вне темы формат держит только до первого заголовка
        PlanNode.objects.filter(title__in=("Повторение", "Контрольная работа")).delete()
        services.reindex(self.owner(), None)
        before = self.titles_with_notes()

        exported = self.export().content

        response = self.client.post(
            f"{reverse('plannode-import')}?course={self.course.pk}",
            {
                "file": SimpleUploadedFile("plan.csv", exported, content_type="text/csv"),
                "mode": "replace",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.titles_with_notes(), before)

    def test_round_trip_keeps_lessons_before_the_first_theme(self):
        self.add("Повторение", position=0)
        section = self.add("Векторы", position=1, is_section=True)
        self.add("Понятие", parent=section, position=0)
        before = self.titles_with_notes()

        exported = self.export().content
        self.client.post(
            f"{reverse('plannode-import')}?course={self.course.pk}",
            {
                "file": SimpleUploadedFile("plan.csv", exported, content_type="text/csv"),
                "mode": "replace",
            },
            format="multipart",
        )

        self.assertEqual(self.titles_with_notes(), before)

    def test_cannot_export_another_users_class(self):
        self.assertEqual(self.export(self.alien_class).status_code, 404)

    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.export().status_code, 401)
