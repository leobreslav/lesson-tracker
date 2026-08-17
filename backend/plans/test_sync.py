"""
Синхронизация плана по id и предпросмотр импорта.

Смысл режима — в одном свойстве: **обновление не трогает содержание**.
Replace и append читают файл как весь план целиком, поэтому переписанная
строка — это новая строка, а новая строка пуста; sync узнаёт строку по id и
правит у неё только то, что в файле вообще есть — название, заметку и место
в дереве.

Поэтому почти каждый тест здесь заканчивается проверкой, что четыре поля
содержания и вложения на месте: остальное (порядок, создание, удаление)
можно было бы получить и без нового режима.

Тема в файле своего id не носит — её строки не существует, есть только
столбец «Тема» у урока. Какой теме плана соответствует блок файла, решают
уроки внутри него (`adopt_section`), и отсюда два поведения, которым здесь
посвящены отдельные тесты: переименование во всех строках переименовывает
тему, а переименование в части строк делит её надвое.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from files.models import Attachment
from schools.testing import make_attachment, make_course, make_stored_file

from . import services
from .models import PlanNode
from .tests import PlanTestCase

BODY = "Пусть $a^2 + b^2 = c^2$.\n\nТогда всё сходится.\n"


class SyncTestCase(PlanTestCase):
    """Небольшой план с содержанием и вложением у одного урока."""

    def setUp(self):
        super().setUp()
        self.section = self.add("Тригонометрия", position=0, is_section=True)
        self.sine = self.add("Синус суммы", parent=self.section, position=0)
        self.cosine = self.add("Косинус суммы", parent=self.section, position=1)
        self.loose = self.add("Повторение", position=1)

        self.sine.objectives = "Понять формулу"
        self.sine.body = BODY
        self.sine.homework = "№ 12–14"
        self.sine.save()

        self.stored = make_stored_file(self.school, self.user)
        self.attachment = make_attachment(self.sine, self.stored)

    # --- утилиты ---

    def send(self, text, *, mode="sync", url="plannode-import", course=None):
        return self.client.post(
            f"{reverse(url)}?course={(course or self.course).pk}",
            {
                "file": SimpleUploadedFile(
                    "plan.csv", text.encode(), content_type="text/csv"
                ),
                "mode": mode,
            },
            format="multipart",
        )

    def preview(self, text, *, mode="sync", course=None):
        return self.send(text, mode=mode, url="plannode-import-preview", course=course)

    def export(self, **params):
        return self.client.get(
            reverse("plannode-export"), {"course": self.course.pk, **params}
        ).content.decode("utf-8-sig")

    def structure(self):
        """Дерево как «уровень + название», в порядке отображения."""
        rows = []
        for branch in services.get_tree(self.owner()):
            rows.append(branch.node.title)
            rows.extend(f"  {child.title}" for child in branch.children)
        return rows

    def file(self, *lines):
        """Файл единственного формата: шапка и строки уроков."""
        return "id,Тема,Урок\n" + "\n".join(lines) + "\n"

    def whole_plan(self, **changes):
        """
        Весь план файлом — то же, что отдал бы экспорт.

        Именованные замены избавляют тесты от переписывания четырёх строк
        ради одной: `whole_plan(sine="Синус суммы двух углов")`.
        """
        rows = {
            "sine": (self.sine.pk, "Тригонометрия", "Синус суммы"),
            "cosine": (self.cosine.pk, "Тригонометрия", "Косинус суммы"),
            "loose": (self.loose.pk, "", "Повторение"),
        }
        lines = []
        for name, (pk, theme, title) in rows.items():
            if name in changes and changes[name] is None:
                continue
            title = changes.get(name, title)
            lines.append(f"{pk},{theme},{title}")
        return self.file(*lines)


class SyncKeepsContentTests(SyncTestCase):
    def test_renaming_a_lesson_keeps_its_content_and_files(self):
        response = self.send(self.whole_plan(sine="Синус суммы двух углов"))

        self.assertEqual(response.status_code, 200, response.content)
        self.sine.refresh_from_db()
        self.assertEqual(self.sine.title, "Синус суммы двух углов")
        self.assertEqual(self.sine.body, BODY)
        self.assertEqual(self.sine.objectives, "Понять формулу")
        self.assertEqual(self.sine.homework, "№ 12–14")
        self.assertEqual(list(self.sine.attachments.all()), [self.attachment])

    def test_the_row_keeps_its_id_rather_than_being_recreated(self):
        """Пересозданная строка потеряла бы содержание молча."""
        self.send(self.whole_plan())

        self.assertTrue(PlanNode.objects.filter(pk=self.sine.pk).exists())
        self.assertEqual(PlanNode.objects.filter(course=self.course).count(), 4)

    def test_a_note_survives_the_file(self):
        """
        Столбца заметки в формате нет вовсе, значит sync её не трогает.

        Это то же правило, что у содержания и вложений: файл правит
        структуру и названия, остальное остаётся в системе. Заметку
        убрали из формата потому, что в таблице её никто не заполнял, а
        колонку возили в каждой строке.
        """
        self.sine.note = "повторить перед контрольной"
        self.sine.save(update_fields=["note"])
        self.section.note = "четыре урока, контрольная в конце"
        self.section.save(update_fields=["note"])

        self.send(self.whole_plan(sine="Синус суммы двух углов"))

        self.sine.refresh_from_db()
        self.section.refresh_from_db()
        self.assertEqual(self.sine.note, "повторить перед контрольной")
        self.assertEqual(self.section.note, "четыре урока, контрольная в конце")


class SyncSectionTests(SyncTestCase):
    """Тему в файле называют уроки, а не отдельная строка."""

    def test_renaming_a_theme_everywhere_renames_the_section(self):
        response = self.send(
            self.file(
                f"{self.sine.pk},Тригонометрические формулы,Синус суммы",
                f"{self.cosine.pk},Тригонометрические формулы,Косинус суммы",
                f"{self.loose.pk},,Повторение",
            )
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["created"], 0)
        self.assertEqual(response.json()["deleted"], 0)
        # та же самая строка плана, а не новая с тем же названием
        self.section.refresh_from_db()
        self.assertEqual(self.section.title, "Тригонометрические формулы")

    def test_renaming_a_theme_in_part_of_the_rows_splits_it(self):
        """
        Ожидаемое следствие протягивания: значение сменилось — начался блок.

        Скрыть это нечем (файл не говорит, что имелась в виду та же тема),
        поэтому предпросмотр называет число новых тем прямо.
        """
        response = self.send(
            self.file(
                f"{self.sine.pk},Тригонометрия,Синус суммы",
                f"{self.cosine.pk},Тригонометрия (вторая половина),Косинус суммы",
                f"{self.loose.pk},,Повторение",
            )
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.structure(),
            [
                "Тригонометрия",
                "  Синус суммы",
                "Тригонометрия (вторая половина)",
                "  Косинус суммы",
                "Повторение",
            ],
        )
        self.section.refresh_from_db()
        self.assertEqual(list(self.section.children.all()), [self.sine])

    def test_the_split_is_visible_in_the_preview(self):
        body = self.preview(
            self.file(
                f"{self.sine.pk},Тригонометрия,Синус суммы",
                f"{self.cosine.pk},Тригонометрия (вторая половина),Косинус суммы",
                f"{self.loose.pk},,Повторение",
            )
        ).json()

        self.assertEqual(body["create_sections"], 1)
        self.assertEqual(body["create_lessons"], 0)
        self.assertEqual(body["delete"], 0)

    def test_a_theme_without_lessons_is_deleted(self):
        """
        Пустую тему файл выразить не может — строки без урока не бывает.

        Значит sync её не находит и удаляет; это видно в предпросмотре, и
        другого честного поведения тут нет.
        """
        empty = self.add("Резерв", position=2, is_section=True)

        response = self.send(self.whole_plan())

        self.assertEqual(response.json()["deleted"], 1)
        self.assertFalse(PlanNode.objects.filter(pk=empty.pk).exists())


class SyncStructureTests(SyncTestCase):
    def test_a_row_without_an_id_is_created(self):
        response = self.send(
            self.file(
                f"{self.sine.pk},Тригонометрия,Синус суммы",
                f"{self.cosine.pk},Тригонометрия,Косинус суммы",
                ",Тригонометрия,Тангенс суммы",
                f"{self.loose.pk},,Повторение",
            )
        )

        self.assertEqual(response.json()["created"], 1)
        self.assertEqual(
            self.structure(),
            [
                "Тригонометрия",
                "  Синус суммы",
                "  Косинус суммы",
                "  Тангенс суммы",
                "Повторение",
            ],
        )

    def test_an_id_missing_from_the_file_is_deleted(self):
        response = self.send(self.whole_plan(cosine=None))

        self.assertEqual(response.json()["deleted"], 1)
        self.assertFalse(PlanNode.objects.filter(pk=self.cosine.pk).exists())

    def test_the_order_of_the_file_becomes_the_order_of_the_plan(self):
        """Массовую перестановку в таблице делать удобнее, чем мышью."""
        self.send(
            self.file(
                f"{self.loose.pk},,Повторение",
                f"{self.cosine.pk},Тригонометрия,Косинус суммы",
                f"{self.sine.pk},Тригонометрия,Синус суммы",
            )
        )

        self.assertEqual(
            self.structure(),
            ["Повторение", "Тригонометрия", "  Косинус суммы", "  Синус суммы"],
        )

    def test_a_lesson_can_leave_a_section_that_goes_away(self):
        """
        Урок переезжает наверх, а его тема исчезает — в одном файле.

        Каскад по родителю унёс бы урок вместе с темой, поэтому родителей
        меняют раньше, чем удаляют.
        """
        self.send(
            # пустая ячейка темы — это «вынести наверх»
            self.file(
                f"{self.sine.pk},,Синус суммы",
                f"{self.loose.pk},,Повторение",
            )
        )

        self.sine.refresh_from_db()
        self.assertIsNone(self.sine.parent_id)
        self.assertEqual(self.sine.body, BODY)
        self.assertFalse(PlanNode.objects.filter(pk=self.section.pk).exists())

    def test_a_new_theme_takes_the_lessons_written_under_it(self):
        self.send(
            self.file(
                f"{self.sine.pk},Тригонометрия,Синус суммы",
                f"{self.cosine.pk},Новая тема,Косинус суммы",
                f"{self.loose.pk},,Повторение",
            )
        )

        self.assertEqual(
            self.structure(),
            [
                "Тригонометрия",
                "  Синус суммы",
                "Новая тема",
                "  Косинус суммы",
                "Повторение",
            ],
        )

    def test_a_deleted_lesson_takes_its_only_file_with_it(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.send(self.whole_plan(sine=None))

        self.assertFalse(Attachment.objects.filter(pk=self.attachment.pk).exists())


class SyncRefusalTests(SyncTestCase):
    """Файл принимается целиком или не принимается вовсе."""

    def assertUntouched(self, response, code):
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], code)
        self.assertEqual(
            self.structure(),
            ["Тригонометрия", "  Синус суммы", "  Косинус суммы", "Повторение"],
        )

    def test_an_id_from_another_plan_is_refused(self):
        alien = self.add("Чужой урок", course=self.alien_class, teacher=self.stranger)

        response = self.send(self.file(f"{alien.pk},,Синус суммы"))

        self.assertUntouched(response, "csv_id_unknown")
        self.assertTrue(PlanNode.objects.filter(pk=alien.pk).exists())

    def test_a_row_of_another_course_is_refused(self):
        """План принадлежит курсу: чужой курс — чужие id, и они не значат ничего."""
        other = make_course(self.school, year=self.course.year, name="9Д")
        theirs = self.add("Их урок", course=other, teacher=self.colleague)

        response = self.send(self.file(f"{theirs.pk},,Синус суммы"))

        self.assertUntouched(response, "csv_id_unknown")
        self.assertTrue(PlanNode.objects.filter(pk=theirs.pk).exists())

    def test_an_id_that_never_existed_is_refused(self):
        response = self.send(self.file("9999999,,Синус суммы"))

        self.assertUntouched(response, "csv_id_unknown")

    def test_the_same_id_twice_is_refused(self):
        response = self.send(
            self.file(
                f"{self.sine.pk},Тригонометрия,Синус суммы",
                f"{self.sine.pk},,Он же ещё раз",
            )
        )

        self.assertUntouched(response, "csv_id_duplicate")

    def test_a_section_id_on_a_lesson_row_is_refused(self):
        """У темы есть дети; молча превратив её в урок, мы их осиротим."""
        response = self.send(self.file(f"{self.section.pk},,Тригонометрия"))

        self.assertUntouched(response, "csv_id_kind_changed")

    def test_a_file_without_a_single_id_has_nothing_to_sync(self):
        """
        Раньше хватало столбца id, даже пустого целиком: sync превращался в
        replace — снести всё, создать заново, потеряв содержание.
        """
        response = self.send(
            self.file(",Тригонометрия,Синус суммы", ",,Повторение")
        )

        self.assertUntouched(response, "csv_nothing_to_sync")

    def test_a_file_of_the_old_format_is_refused_before_the_mode_matters(self):
        response = self.send("Тема,Урок\nВекторы,\n,Понятие\n")

        self.assertUntouched(response, "csv_header_invalid")

    def test_a_failure_in_the_middle_rolls_the_whole_file_back(self):
        from unittest.mock import patch

        before = self.structure()
        text = self.file(
            f"{self.sine.pk},Тригонометрия переименованная,Синус суммы",
            f"{self.cosine.pk},Тригонометрия переименованная,Косинус суммы",
            ",,Новый урок",
            f"{self.loose.pk},,Повторение",
        )

        with patch.object(
            PlanNode.objects, "create", side_effect=RuntimeError("база упала")
        ):
            with self.assertRaises(RuntimeError):
                self.send(text)

        self.assertEqual(self.structure(), before)
        self.section.refresh_from_db()
        self.assertEqual(self.section.title, "Тригонометрия")


class RoundTripTests(SyncTestCase):
    def test_export_then_sync_changes_nothing(self):
        before = self.structure()

        response = self.send(self.export())

        self.assertEqual(response.status_code, 200, response.content)
        # ноль созданных и ноль удалённых: файл описывает ровно тот план,
        # из которого он получен
        self.assertEqual(
            response.json(), {"created": 0, "updated": 4, "deleted": 0}
        )
        self.assertEqual(self.structure(), before)
        self.sine.refresh_from_db()
        self.assertEqual(self.sine.body, BODY)
        self.assertEqual(self.sine.attachments.count(), 1)

    def test_the_second_round_trip_changes_nothing_either(self):
        """Идемпотентность: id не переезжают, темы не пересоздаются."""
        self.send(self.export())
        pks = list(
            PlanNode.objects.filter(course=self.course)
            .order_by("pk")
            .values_list("pk", flat=True)
        )

        response = self.send(self.export())

        self.assertEqual(response.json()["created"], 0)
        self.assertEqual(
            list(
                PlanNode.objects.filter(course=self.course)
                .order_by("pk")
                .values_list("pk", flat=True)
            ),
            pks,
        )


class PreviewTests(SyncTestCase):
    def test_preview_changes_nothing(self):
        before = self.structure()

        self.preview(self.file(f"{self.loose.pk},,Повторение"))

        self.assertEqual(self.structure(), before)
        self.assertEqual(PlanNode.objects.filter(course=self.course).count(), 4)

    def test_preview_says_how_the_file_was_read(self):
        body = self.preview(self.export()).json()

        self.assertEqual(body["rows"], 3)
        self.assertEqual(body["lessons"], 3)
        self.assertEqual(body["sections"], 1)

    def test_preview_counts_the_three_kinds_of_change(self):
        body = self.preview(
            self.file(
                f"{self.sine.pk},Тригонометрия,Синус суммы",
                ",,Тангенс суммы",
            )
        ).json()

        self.assertEqual(body["create"], 1)
        self.assertEqual(body["create_lessons"], 1)
        # тема жива: её назвал урок с id
        self.assertEqual(body["update"], 2)
        # уходят «Косинус суммы» и «Повторение»
        self.assertEqual(body["delete"], 2)
        self.assertEqual(body["errors"], [])

    def test_preview_names_the_rows_whose_content_would_be_lost(self):
        body = self.preview(self.file(f"{self.cosine.pk},Тригонометрия,Косинус суммы")).json()

        self.assertEqual(body["with_content"], 1)
        self.assertEqual(body["with_attachments"], 1)
        self.assertEqual(body["files_lost"], 1)
        self.assertEqual(
            body["delete_with_content"],
            [
                {
                    "id": self.sine.pk,
                    "title": "Синус суммы",
                    "has_content": True,
                    "has_attachments": True,
                }
            ],
        )

    def test_preview_of_replace_counts_the_whole_plan(self):
        body = self.preview(
            self.file(",Векторы,Понятие"), mode="replace"
        ).json()

        self.assertEqual(body["mode"], "replace")
        self.assertEqual(body["create"], 2)
        self.assertEqual(body["create_sections"], 1)
        self.assertEqual(body["delete"], 4)
        self.assertEqual(body["delete_lessons"], 3)
        self.assertEqual(body["delete_sections"], 1)
        self.assertEqual(body["with_content"], 1)
        self.assertEqual(body["files_lost"], 1)

    def test_preview_of_append_loses_nothing(self):
        body = self.preview(self.file(",Векторы,Понятие"), mode="append").json()

        self.assertEqual(body["delete"], 0)
        self.assertEqual(body["with_content"], 0)
        self.assertEqual(body["delete_with_content"], [])

    def test_a_shared_file_is_not_counted_as_lost(self):
        """Тот же объект висит на строке шаблона — байты никуда не денутся."""
        template = self.make_template_row()
        make_attachment(template, self.stored)

        body = self.preview(
            self.file(f"{self.cosine.pk},Тригонометрия,Косинус суммы")
        ).json()

        self.assertEqual(body["with_attachments"], 1)
        self.assertEqual(body["files_lost"], 0)

    def test_preview_lists_every_bad_id_at_once(self):
        body = self.preview(self.file("9999998,,Первый", "9999999,,Второй")).json()

        self.assertEqual([error["code"] for error in body["errors"]],
                         ["csv_id_unknown", "csv_id_unknown"])
        self.assertEqual(body["errors"][0]["params"]["row"], 2)

    def test_preview_reports_a_broken_file_instead_of_refusing(self):
        """
        Предпросмотр ни от чего не отказывается: показать весь список
        полезнее, чем 400 на первой ошибке.
        """
        body = self.preview(self.file(",Векторы,", "412,,")).json()

        self.assertEqual(
            [error["code"] for error in body["errors"]],
            ["csv_section_row", "csv_row_empty"],
        )
        self.assertEqual(body["delete"], 0)

    def test_preview_says_when_there_is_nothing_to_sync(self):
        body = self.preview(self.file(",Векторы,Понятие")).json()

        self.assertEqual([error["code"] for error in body["errors"]],
                         ["csv_nothing_to_sync"])
        self.assertEqual(body["delete"], 0)

    def make_template_row(self):
        from library.models import PlanTemplateRow
        from schools.testing import make_template

        template = make_template(self.school, self.user, rows=((False, "Урок"),))
        return PlanTemplateRow.objects.get(template=template)
