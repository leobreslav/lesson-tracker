"""
Импорт и экспорт учебного плана через CSV.

Формат один: `id,Тема,Урок`, шапка обязательна, одна строка — один
урок, тема повторяется в каждой строке. Стилей было три, и разбор угадывал,
какой перед ним; отказ от угадывания — это и есть содержание этого файла:
почти половина тестов здесь проверяет, что непонятный файл **отклонён**, а
не прочитан как-нибудь.

Отклонение всегда целиком: половина применённого файла хуже неприменённого,
потому что непонятно, какая половина.
"""

from datetime import date, timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse
from schedule.models import Slot

from . import services
from .models import PlanNode
from .tests import PlanTestCase

HEAD = "id,Тема,Урок\n"
HEAD_DATED = "id,Тема,Урок,Дата\n"

MONDAY = date(2026, 9, 7)

SAMPLE = HEAD + (
    ",Тригонометрические формулы,Синус и косинус суммы\n"
    ",Тригонометрические формулы,Тангенс суммы\n"
    ",Векторы,Понятие вектора\n"
)


def parsed(rows):
    return [("тема" if row.is_section else "урок", row.title) for row in rows]


def codes(errors):
    return [error["code"] for error in errors]


class ParseTests(SimpleTestCase):
    """Что разбор понимает — и что называет ошибкой."""

    def parse(self, text):
        return services.parse_plan_csv(text)

    def test_a_theme_repeated_on_every_row(self):
        result = self.parse(SAMPLE)

        self.assertTrue(result.ok)
        self.assertEqual(
            parsed(result.rows),
            [
                ("тема", "Тригонометрические формулы"),
                ("урок", "Синус и косинус суммы"),
                ("урок", "Тангенс суммы"),
                ("тема", "Векторы"),
                ("урок", "Понятие вектора"),
            ],
        )

    def test_an_empty_theme_means_a_lesson_outside_any_theme(self):
        result = self.parse(HEAD + ",,Повторение\n,Векторы,Понятие\n")

        self.assertEqual(
            parsed(result.rows),
            [("урок", "Повторение"), ("тема", "Векторы"), ("урок", "Понятие")],
        )
        self.assertTrue(result.rows[0].at_top_level)
        self.assertFalse(result.rows[2].at_top_level)

    def test_a_lesson_after_a_theme_leaves_it_when_the_cell_is_empty(self):
        result = self.parse(HEAD + ",Векторы,Понятие\n,,Итоговый урок\n")

        self.assertEqual(
            parsed(result.rows),
            [("тема", "Векторы"), ("урок", "Понятие"), ("урок", "Итоговый урок")],
        )
        self.assertTrue(result.rows[2].at_top_level)

    def test_the_same_theme_after_another_one_starts_a_second_block(self):
        """
        Заголовок рождается из смены значения, а не из имени.

        Два блока с одинаковым названием — это два блока: строки плана идут
        подряд, и «собрать разрозненные куски в одну тему» файл не просит.
        """
        result = self.parse(HEAD + ",А,Раз\n,Б,Два\n,А,Три\n")

        self.assertEqual(
            parsed(result.rows),
            [("тема", "А"), ("урок", "Раз"), ("тема", "Б"), ("урок", "Два"),
             ("тема", "А"), ("урок", "Три")],
        )

    def test_the_id_column_is_read(self):
        result = self.parse(HEAD + "10,Векторы,Понятие\n,Векторы,Новый\n")

        self.assertEqual([row.node_id for row in result.rows], [None, 10, None])

    def test_the_header_is_case_and_space_insensitive(self):
        result = self.parse("ID; ТЕМА ;УРОК\n;Векторы;Понятие\n")

        self.assertTrue(result.ok, result.errors)
        self.assertEqual(parsed(result.rows), [("тема", "Векторы"), ("урок", "Понятие")])

    def test_trailing_empty_columns_are_forgiven(self):
        """Пятый пустой столбец дописывает сам Excel, это не другой файл."""
        result = self.parse(HEAD + ",Векторы,Понятие,\n")

        self.assertTrue(result.ok, result.errors)

    def test_blank_lines_are_skipped(self):
        result = self.parse(HEAD + ",Векторы,Понятие\n\n\n")

        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.data_rows, 1)

    def test_spaces_around_values_are_trimmed(self):
        result = self.parse(HEAD + " , Векторы , Понятие \n")

        self.assertEqual(result.rows[0].title, "Векторы")
        self.assertEqual(result.rows[1].title, "Понятие")

    def test_the_row_limit_is_reported(self):
        text = HEAD + "\n".join(f",Тема,Урок {index}" for index in range(2100))

        with self.assertRaises(services.PlanImportError) as caught:
            self.parse(text)

        self.assertIn("2000", str(caught.exception))


class RefusalTests(SimpleTestCase):
    """Каждая непонятная строка называется, а не толкуется."""

    def errors(self, text):
        return codes(services.parse_plan_csv(text).errors)

    def test_a_file_without_a_header(self):
        self.assertEqual(self.errors(",Векторы,Понятие\n"), ["csv_header_invalid"])

    def test_a_header_in_another_order(self):
        self.assertEqual(
            self.errors("Тема,id,Урок\n"), ["csv_header_invalid"]
        )

    def test_the_old_three_column_header(self):
        self.assertEqual(
            self.errors("id,Тема,Урок,Заметка\n,Векторы,Понятие,\n"),
            ["csv_header_invalid"],
        )

    def test_the_header_error_says_what_was_expected(self):
        error = services.parse_plan_csv("Тема,Урок\n").errors[0]

        self.assertEqual(error["params"]["expected"], "id,Тема,Урок")

    def test_a_row_with_fewer_columns(self):
        self.assertEqual(self.errors(HEAD + ",Векторы\n"), ["csv_bad_columns"])

    def test_a_row_with_a_filled_fifth_column(self):
        self.assertEqual(
            self.errors(HEAD + ",Векторы,Понятие,,лишнее\n"), ["csv_bad_columns"]
        )

    def test_a_header_row_of_the_old_style(self):
        """Тема без урока — это бывший заголовок; сказать об этом прямо."""
        errors = services.parse_plan_csv(HEAD + ",Векторы,\n").errors

        self.assertEqual(codes(errors), ["csv_section_row"])
        self.assertEqual(errors[0]["params"], {"row": 2, "title": "Векторы"})

    def test_a_row_with_neither_theme_nor_lesson(self):
        self.assertEqual(self.errors(HEAD + "412,,\n"), ["csv_row_empty"])

    def test_a_title_longer_than_the_limit(self):
        self.assertEqual(
            self.errors(HEAD + f",Векторы,{'о' * 201}\n"), ["csv_row_too_long"]
        )

    def test_an_id_that_is_not_a_number(self):
        self.assertEqual(self.errors(HEAD + "абв,Векторы,Понятие\n"), ["csv_bad_id"])

    def test_a_negative_id(self):
        self.assertEqual(self.errors(HEAD + "-5,Векторы,Понятие\n"), ["csv_bad_id"])

    def test_a_zero_id(self):
        self.assertEqual(self.errors(HEAD + "0,Векторы,Понятие\n"), ["csv_bad_id"])

    def test_every_bad_row_is_named_at_once(self):
        """Показать все разом полезнее, чем ту строку, на которой сдались."""
        errors = services.parse_plan_csv(
            HEAD + ",Векторы,\nабв,Векторы,Понятие\n412,,\n"
        ).errors

        self.assertEqual(
            codes(errors), ["csv_section_row", "csv_bad_id", "csv_row_empty"]
        )
        self.assertEqual([error["params"]["row"] for error in errors], [2, 3, 4])

    def test_a_bad_row_leaves_the_others_readable(self):
        """Строки всё равно разобраны: предпросмотру есть что показать."""
        result = services.parse_plan_csv(HEAD + ",Векторы,Понятие\n,Векторы,\n")

        self.assertFalse(result.ok)
        self.assertEqual(result.data_rows, 2)
        self.assertEqual(parsed(result.rows), [("тема", "Векторы"), ("урок", "Понятие")])


class DecodeTests(SimpleTestCase):
    def test_utf8(self):
        self.assertEqual(services.decode_csv("Векторы".encode()), "Векторы")

    def test_utf8_with_bom(self):
        data = "﻿id,Тема,Урок\n".encode()

        # BOM не должен попасть в первую ячейку, иначе шапка не совпадёт
        self.assertEqual(services.decode_csv(data), "id,Тема,Урок\n")

    def test_cp1251(self):
        data = "id;Тема;Урок\n;Векторы;Понятие;\n".encode("cp1251")

        result = services.parse_plan_csv(services.decode_csv(data))

        self.assertTrue(result.ok, result.errors)
        self.assertEqual(parsed(result.rows), [("тема", "Векторы"), ("урок", "Понятие")])

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
        body = {
            "file": SimpleUploadedFile("plan.csv", payload, content_type="text/csv"),
        }
        if mode is not None:
            body["mode"] = mode
        return self.client.post(
            f"{reverse('plannode-import')}?course={(course or self.course).pk}",
            body,
            format="multipart",
        )

    def titles(self):
        return self.structure()

    def test_import_creates_the_tree(self):
        response = self.upload(SAMPLE)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json(),
            {
                "created_rows": 5,
                "created_headers": 2,
                "created_lessons": 3,
                # столбца дат в этом файле не было, и ответ говорит об этом
                # прямо: молча отброшенный столбец выглядел бы применённым
                "dates_ignored": False,
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
        self.upload(SAMPLE)

        self.assertEqual(self.positions(), [0, 1])
        self.assertEqual(self.positions(self.node("Векторы")), [0])

    def test_replace_wipes_the_old_plan(self):
        self.build_sample()

        self.upload(SAMPLE, mode="replace")

        self.assertNotIn("Тригонометрия,", "".join(self.titles()))
        self.assertEqual(len(self.titles()), 5)

    def test_append_keeps_the_old_plan(self):
        self.build_sample()
        before = len(self.titles())

        response = self.upload(SAMPLE, mode="append")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(self.titles()), before + 5)
        self.assertEqual(self.titles()[0], "Тригонометрия")
        self.assertEqual(self.titles()[-1], "  Понятие вектора")
        self.assertEqual(self.positions(), [0, 1, 2, 3, 4, 5, 6])

    def test_append_ignores_the_id_column(self):
        """
        Иначе строки с уже существующими id встали бы дублями рядом с ними —
        и молча: append ничего не сверяет с планом.
        """
        section = self.add("Векторы", position=0, is_section=True)
        lesson = self.add("Понятие", parent=section, position=0)

        response = self.upload(
            HEAD + f"{lesson.pk},Векторы,Понятие\n", mode="append"
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.titles(), ["Векторы", "  Понятие", "Векторы", "  Понятие"]
        )

    def test_cp1251_file(self):
        response = self.upload(
            "id;Тема;Урок\n;Векторы;Понятие;\n", encoding="cp1251"
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.titles(), ["Векторы", "  Понятие"])

    def test_bom_file(self):
        response = self.upload("﻿" + HEAD + ",Векторы,Понятие\n")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.titles(), ["Векторы", "  Понятие"])

    def test_a_refused_file_changes_nothing(self):
        self.build_sample()
        before = self.titles()

        response = self.upload(HEAD + ",Векторы,\n", mode="replace")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "csv_section_row")
        self.assertEqual(self.titles(), before)

    def test_broken_file_leaves_everything_untouched(self):
        """Сбой на середине импорта не должен оставить полплана."""
        self.build_sample()
        before = self.titles()

        with patch.object(
            PlanNode.objects, "create", side_effect=RuntimeError("база упала")
        ):
            with self.assertRaises(RuntimeError):
                self.upload(SAMPLE)

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
        text = HEAD + "\n".join(f",Тема,Урок {index}" for index in range(2100))

        response = self.upload(text)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "file_unreadable")
        self.assertIn("2000", response.json()["detail"])
        self.assertFalse(
            PlanNode.objects.filter(course=self.course).exists()
        )

    def test_missing_file_is_rejected(self):
        response = self.client.post(
            f"{reverse('plannode-import')}?course={self.course.pk}",
            {"mode": "replace"},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)

    def test_bad_mode_is_rejected(self):
        self.assertEqual(self.upload(SAMPLE, mode="wipe").status_code, 400)

    def test_mode_is_required(self):
        """Умолчания у разрушительной операции нет: POST без mode сносил план."""
        self.build_sample()
        before = self.titles()

        response = self.upload(SAMPLE, mode=None)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "mode_required")
        self.assertEqual(self.titles(), before)

    def test_cannot_import_into_another_users_class(self):
        response = self.upload(SAMPLE, course=self.alien_class)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(PlanNode.objects.filter(course=self.alien_class).exists())

    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.upload(SAMPLE).status_code, 401)


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
        self.assertEqual(self.text(response).splitlines()[0], "id,Тема,Урок")

    def test_export_writes_one_row_per_lesson(self):
        trig, *_ = self.build_sample()
        sine = self.node("Синус суммы")

        lines = self.text(self.export()).splitlines()

        self.assertEqual(lines[1], f"{sine.pk},Тригонометрия,Синус суммы")
        # отдельной строки заголовка нет вовсе
        self.assertNotIn(f"{trig.pk},Тригонометрия,", lines)

    def test_a_lesson_outside_a_theme_has_an_empty_theme_cell(self):
        lesson = self.add("Повторение", position=0)

        lines = self.text(self.export()).splitlines()

        self.assertEqual(lines[1], f"{lesson.pk},,Повторение")

    def test_a_theme_without_lessons_does_not_reach_the_file(self):
        """
        Известный предел формата: строки без урока не существует.

        Обратный импорт такую тему удалит — предпросмотр показывает это
        числом удаляемых, и другого способа выразить пустую тему в файле,
        где одна строка это один урок, нет.
        """
        self.add("Пустая тема", position=0, is_section=True)

        self.assertEqual(self.text(self.export()).strip(), "id,Тема,Урок")

    def test_filename_carries_the_class_and_date(self):
        response = self.export()

        disposition = response["Content-Disposition"]
        self.assertIn("filename*=UTF-8''", disposition)
        self.assertIn("%D0%BF%D0%BB%D0%B0%D0%BD", disposition)  # «план»

    def test_export_of_an_empty_plan_is_just_the_header(self):
        self.assertEqual(self.text(self.export()).strip(), "id,Тема,Урок")

    def test_round_trip_through_replace_gives_the_same_plan(self):
        self.build_sample()
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

    def test_round_trip_keeps_lessons_outside_themes(self):
        """
        Урок вне темы — не только до первого заголовка.

        В трёхстолбцовом формате урок, стоящий после темы, был неотличим от
        урока внутри неё; здесь пустая ячейка темы говорит это прямо.
        """
        section = self.add("Векторы", position=0, is_section=True)
        self.add("Понятие", parent=section, position=0)
        self.add("Повторение", position=1)
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


class DatedColumnParseTests(SimpleTestCase):
    """
    Четвёртый столбец «Дата»: читается и отбрасывается.

    Дата в плане не живёт — её даёт раскладка, то есть расписание, — и
    приехать импортом ей некуда. Отклонять такой файл при этом нельзя:
    столбец пишет **наша же** выгрузка, и отказ означал бы, что выгруженное
    не импортируется, а это главное свойство формата.

    Угадывания тут не прибавилось: шапки ровно две, обе сравниваются
    дословно, и всё, что не совпало ни с одной, по-прежнему отклоняется.
    """

    def test_the_dated_header_is_accepted(self):
        parsed_plan = services.parse_plan_csv(
            HEAD_DATED + ",Векторы,Понятие вектора,2026-09-07\n"
        )

        self.assertEqual(parsed_plan.errors, [])
        self.assertEqual(
            parsed(parsed_plan.rows), [("тема", "Векторы"), ("урок", "Понятие вектора")]
        )

    def test_the_file_says_that_the_dates_were_dropped(self):
        # молча отброшенный столбец выглядит как применённый, а человек
        # правил в нём даты и ждёт, что они куда-то поехали
        dated = services.parse_plan_csv(HEAD_DATED + ",Векторы,Понятие,2026-09-07\n")
        plain = services.parse_plan_csv(HEAD + ",Векторы,Понятие\n")

        self.assertIs(dated.dates_ignored, True)
        self.assertIs(plain.dates_ignored, False)

    def test_an_empty_date_cell_is_fine(self):
        """Уроку могло не достаться часа — тогда ячейка пуста, и это не отказ."""
        parsed_plan = services.parse_plan_csv(HEAD_DATED + ",Векторы,Понятие,\n")

        self.assertEqual(parsed_plan.errors, [])
        self.assertEqual(parsed_plan.lessons, 1)

    def test_a_fourth_column_without_the_dated_header_is_still_refused(self):
        """
        Ширину объявляет шапка, а не первая попавшаяся строка.

        Иначе вернулось бы ровно то угадывание, ради отказа от которого
        формат и сузили: файл с лишним столбцом читался бы «как-нибудь».
        """
        self.assertEqual(
            codes(services.parse_plan_csv(HEAD + ",Векторы,Понятие,лишнее\n").errors),
            ["csv_bad_columns"],
        )

    def test_a_fifth_column_is_refused_even_with_the_dated_header(self):
        self.assertEqual(
            codes(
                services.parse_plan_csv(
                    HEAD_DATED + ",Векторы,Понятие,2026-09-07,лишнее\n"
                ).errors
            ),
            ["csv_bad_columns"],
        )

    def test_the_dated_header_alone_is_not_a_lesson(self):
        """Шапка остаётся шапкой: строк данных в таком файле ноль."""
        parsed_plan = services.parse_plan_csv(HEAD_DATED)

        self.assertEqual(parsed_plan.rows, [])
        self.assertEqual(parsed_plan.data_rows, 0)


class ExportWithDatesTests(PlanTestCase):
    """
    Выгрузка «с датами» — тот же файл, которому объявили четвёртый столбец.

    Не второй формат «для чтения»: такой файл ложится обратно импортом, и
    круговой прогон это стережёт. Второй формат разошёлся бы с импортом в
    первую же правку, и печатать план было бы не на чем.
    """

    def setUp(self):
        super().setUp()
        self.section = self.add("Тригонометрия", position=0, is_section=True)
        self.sine = self.add("Синус суммы", parent=self.section, position=0)
        self.cosine = self.add("Косинус суммы", parent=self.section, position=1)

    def add_slot(self, day, number=1):
        return Slot.objects.create(
            year=self.course.year,
            course=self.course,
            date=day,
            lesson_number=number,
        )

    def export(self, **params):
        return self.client.get(
            reverse("plannode-export"), {"course": self.course.pk, **params}
        )

    def lines(self, **params):
        return self.export(**params).content.decode("utf-8-sig").splitlines()

    def test_without_the_flag_the_file_is_the_old_one(self):
        self.add_slot(MONDAY)

        lines = self.lines()

        self.assertEqual(lines[0], "id,Тема,Урок")
        self.assertEqual(lines[1], f"{self.sine.pk},Тригонометрия,Синус суммы")

    def test_the_dates_come_from_the_layout(self):
        self.add_slot(MONDAY)
        self.add_slot(MONDAY + timedelta(days=1))

        lines = self.lines(dates="1")

        self.assertEqual(lines[0], "id,Тема,Урок,Дата")
        self.assertEqual(
            lines[1], f"{self.sine.pk},Тригонометрия,Синус суммы,2026-09-07"
        )
        self.assertEqual(
            lines[2], f"{self.cosine.pk},Тригонометрия,Косинус суммы,2026-09-08"
        )

    def test_a_lesson_without_an_hour_gets_an_empty_cell(self):
        """
        Пусто — это не «дата неизвестна», а «часа этому уроку не досталось».

        План бывает длиннее расписания, и такие строки лежат в раскладке
        как `no_slot`. Прочерк сказал бы то, чего раскладка не говорит.
        """
        self.add_slot(MONDAY)

        lines = self.lines(dates="1")

        self.assertEqual(
            lines[2], f"{self.cosine.pk},Тригонометрия,Косинус суммы,"
        )

    def test_a_plan_without_a_schedule_exports_empty_cells(self):
        lines = self.lines(dates="1")

        self.assertEqual(lines[0], "id,Тема,Урок,Дата")
        self.assertTrue(all(line.endswith(",") for line in lines[1:]), lines)

    def test_the_dated_file_imports_back_unchanged(self):
        """
        Круговой прогон — то, ради чего столбец принимается, а не отклоняется.

        Файл с датами уходит обратно тем же `sync`, и план от этого не
        меняется ни строчкой: ноль созданных, ноль удалённых.
        """
        self.add_slot(MONDAY)
        self.add_slot(MONDAY + timedelta(days=1))
        before = self.titles_with_notes()

        exported = self.export(dates="1").content
        response = self.client.post(
            f"{reverse('plannode-import')}?course={self.course.pk}",
            {
                "file": SimpleUploadedFile(
                    "план.csv", exported, content_type="text/csv"
                ),
                "mode": "sync",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["created"], 0)
        self.assertEqual(body["deleted"], 0)
        self.assertIs(body["dates_ignored"], True)
        self.assertEqual(self.titles_with_notes(), before)

    def test_editing_a_date_in_the_file_changes_nothing(self):
        """
        Дата приезжает обратно ничем, и это надо было закрепить тестом.

        Место даты — в расписании: правка её в таблице плана не должна ни
        двигать часы, ни отклонять файл. Иначе столбец обещал бы то, чего
        не делает.
        """
        slot = self.add_slot(MONDAY)

        self.client.post(
            f"{reverse('plannode-import')}?course={self.course.pk}",
            {
                "file": SimpleUploadedFile(
                    "план.csv",
                    (
                        HEAD_DATED
                        + f"{self.sine.pk},Тригонометрия,Синус суммы,2030-01-01\n"
                        + f"{self.cosine.pk},Тригонометрия,Косинус суммы,2030-01-02\n"
                    ).encode(),
                    content_type="text/csv",
                ),
                "mode": "sync",
            },
            format="multipart",
        )

        slot.refresh_from_db()
        self.assertEqual(slot.date, MONDAY)
