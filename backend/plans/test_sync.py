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
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from files.models import Attachment
from schools.testing import make_attachment, make_stored_file

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

    def file_with_ids(self, *lines):
        return "id,Тема,Урок,Заметка\n" + "\n".join(lines) + "\n"


class SyncKeepsContentTests(SyncTestCase):
    def test_renaming_a_lesson_keeps_its_content_and_files(self):
        response = self.send(
            self.file_with_ids(
                f"{self.section.pk},Тригонометрия,,",
                f"{self.sine.pk},Тригонометрия,Синус суммы двух углов,",
                f"{self.cosine.pk},Тригонометрия,Косинус суммы,",
                f"{self.loose.pk},,Повторение,",
            )
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.sine.refresh_from_db()
        self.assertEqual(self.sine.title, "Синус суммы двух углов")
        self.assertEqual(self.sine.body, BODY)
        self.assertEqual(self.sine.objectives, "Понять формулу")
        self.assertEqual(self.sine.homework, "№ 12–14")
        self.assertEqual(list(self.sine.attachments.all()), [self.attachment])

    def test_the_row_keeps_its_id_rather_than_being_recreated(self):
        """Пересозданная строка потеряла бы содержание молча."""
        self.send(
            self.file_with_ids(
                f"{self.section.pk},Тригонометрия,,",
                f"{self.sine.pk},Тригонометрия,Синус суммы,",
                f"{self.cosine.pk},Тригонометрия,Косинус суммы,",
                f"{self.loose.pk},,Повторение,",
            )
        )

        self.assertTrue(PlanNode.objects.filter(pk=self.sine.pk).exists())
        self.assertEqual(PlanNode.objects.filter(course=self.course).count(), 4)

    def test_notes_are_updated(self):
        self.send(
            self.file_with_ids(
                f"{self.section.pk},Тригонометрия,,",
                f"{self.sine.pk},Тригонометрия,Синус суммы,повторить перед контрольной",
                f"{self.cosine.pk},Тригонометрия,Косинус суммы,",
                f"{self.loose.pk},,Повторение,",
            )
        )

        self.sine.refresh_from_db()
        self.assertEqual(self.sine.note, "повторить перед контрольной")


class SyncStructureTests(SyncTestCase):
    def test_a_row_without_an_id_is_created(self):
        response = self.send(
            self.file_with_ids(
                f"{self.section.pk},Тригонометрия,,",
                f"{self.sine.pk},Тригонометрия,Синус суммы,",
                f"{self.cosine.pk},Тригонометрия,Косинус суммы,",
                ",Тригонометрия,Тангенс суммы,добавлен вручную",
                f"{self.loose.pk},,Повторение,",
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
        response = self.send(
            self.file_with_ids(
                f"{self.section.pk},Тригонометрия,,",
                f"{self.sine.pk},Тригонометрия,Синус суммы,",
                f"{self.loose.pk},,Повторение,",
            )
        )

        self.assertEqual(response.json()["deleted"], 1)
        self.assertFalse(PlanNode.objects.filter(pk=self.cosine.pk).exists())

    def test_the_order_of_the_file_becomes_the_order_of_the_plan(self):
        """Массовую перестановку в таблице делать удобнее, чем мышью."""
        self.send(
            self.file_with_ids(
                f"{self.loose.pk},,Повторение,",
                f"{self.section.pk},Тригонометрия,,",
                f"{self.cosine.pk},Тригонометрия,Косинус суммы,",
                f"{self.sine.pk},Тригонометрия,Синус суммы,",
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
            # пустая ячейка темы у строки с id — это «вынести наверх»
            self.file_with_ids(
                f"{self.sine.pk},,Синус суммы,",
                f"{self.loose.pk},,Повторение,",
            )
        )

        self.sine.refresh_from_db()
        self.assertIsNone(self.sine.parent_id)
        self.assertEqual(self.sine.body, BODY)
        self.assertFalse(PlanNode.objects.filter(pk=self.section.pk).exists())

    def test_a_new_section_takes_the_lessons_written_under_it(self):
        self.send(
            self.file_with_ids(
                f"{self.section.pk},Тригонометрия,,",
                f"{self.sine.pk},Тригонометрия,Синус суммы,",
                ",Новая тема,,",
                f"{self.cosine.pk},Новая тема,Косинус суммы,",
                f"{self.loose.pk},,Повторение,",
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
            self.send(
                self.file_with_ids(
                    f"{self.section.pk},Тригонометрия,,",
                    f"{self.cosine.pk},Тригонометрия,Косинус суммы,",
                    f"{self.loose.pk},,Повторение,",
                )
            )

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

        response = self.send(
            self.file_with_ids(
                f"{self.section.pk},Тригонометрия,,",
                f"{alien.pk},,Синус суммы,",
            )
        )

        self.assertUntouched(response, "csv_id_unknown")
        self.assertTrue(PlanNode.objects.filter(pk=alien.pk).exists())

    def test_a_colleagues_row_in_the_same_course_is_refused(self):
        """Курс общий, план — нет: id коллеги в моём плане не значит ничего."""
        theirs = self.add("Их урок", teacher=self.colleague)

        response = self.send(
            self.file_with_ids(
                f"{self.section.pk},Тригонометрия,,",
                f"{theirs.pk},,Синус суммы,",
            )
        )

        self.assertUntouched(response, "csv_id_unknown")
        self.assertTrue(PlanNode.objects.filter(pk=theirs.pk).exists())

    def test_an_id_that_never_existed_is_refused(self):
        response = self.send(
            self.file_with_ids(
                f"{self.section.pk},Тригонометрия,,",
                "9999999,,Синус суммы,",
            )
        )

        self.assertUntouched(response, "csv_id_unknown")

    def test_the_same_id_twice_is_refused(self):
        response = self.send(
            self.file_with_ids(
                f"{self.section.pk},Тригонометрия,,",
                f"{self.sine.pk},Тригонометрия,Синус суммы,",
                f"{self.sine.pk},,Он же ещё раз,",
            )
        )

        self.assertUntouched(response, "csv_id_duplicate")

    def test_a_section_cannot_become_a_lesson(self):
        """У темы есть дети; молча превратив её в урок, мы их осиротим."""
        response = self.send(
            self.file_with_ids(
                f"{self.section.pk},,Тригонометрия,",
                f"{self.sine.pk},Тригонометрия,Синус суммы,",
            )
        )

        self.assertUntouched(response, "csv_id_kind_changed")

    def test_a_file_without_ids_cannot_be_synced(self):
        response = self.send("Тема,Урок,Заметка\nВекторы,,\n,Понятие,\n")

        self.assertUntouched(response, "csv_ids_required")

    def test_a_failure_in_the_middle_rolls_the_whole_file_back(self):
        from unittest.mock import patch

        before = self.structure()
        text = self.file_with_ids(
            f"{self.section.pk},Тригонометрия переименованная,,",
            f"{self.sine.pk},Тригонометрия,Синус суммы,",
            f"{self.cosine.pk},Тригонометрия,Косинус суммы,",
            ",,Новый урок,",
            f"{self.loose.pk},,Повторение,",
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
        self.assertEqual(
            response.json(), {"created": 0, "updated": 4, "deleted": 0, "warnings": []}
        )
        self.assertEqual(self.structure(), before)
        self.sine.refresh_from_db()
        self.assertEqual(self.sine.body, BODY)
        self.assertEqual(self.sine.attachments.count(), 1)

    def test_a_plan_exported_without_ids_still_imports_the_old_way(self):
        response = self.send(self.export(with_ids="false"), mode="replace")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["created_lessons"], 3)


class PreviewTests(SyncTestCase):
    def test_preview_changes_nothing(self):
        before = self.structure()

        self.preview(self.file_with_ids(f"{self.loose.pk},,Повторение,"))

        self.assertEqual(self.structure(), before)
        self.assertEqual(PlanNode.objects.filter(course=self.course).count(), 4)

    def test_preview_counts_the_three_kinds_of_change(self):
        body = self.preview(
            self.file_with_ids(
                f"{self.section.pk},Тригонометрия,,",
                f"{self.sine.pk},Тригонометрия,Синус суммы,",
                ",,Тангенс суммы,",
            )
        ).json()

        self.assertEqual(body["create"], 1)
        self.assertEqual(body["update"], 2)
        # уходят «Косинус суммы» и «Повторение»
        self.assertEqual(body["delete"], 2)
        self.assertEqual(body["errors"], [])

    def test_preview_names_the_rows_whose_content_would_be_lost(self):
        body = self.preview(
            self.file_with_ids(f"{self.section.pk},Тригонометрия,,")
        ).json()

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
        body = self.preview("Тема,Урок,Заметка\nВекторы,,\n,Понятие,\n",
                            mode="replace").json()

        self.assertEqual(body["mode"], "replace")
        self.assertFalse(body["has_ids"])
        self.assertEqual(body["create"], 2)
        self.assertEqual(body["delete"], 4)
        self.assertEqual(body["delete_lessons"], 3)
        self.assertEqual(body["delete_sections"], 1)
        self.assertEqual(body["with_content"], 1)
        self.assertEqual(body["files_lost"], 1)

    def test_preview_of_append_loses_nothing(self):
        body = self.preview("Тема,Урок,Заметка\nВекторы,,\n,Понятие,\n",
                            mode="append").json()

        self.assertEqual(body["delete"], 0)
        self.assertEqual(body["with_content"], 0)
        self.assertEqual(body["delete_with_content"], [])

    def test_a_shared_file_is_not_counted_as_lost(self):
        """Тот же объект висит на строке шаблона — байты никуда не денутся."""
        template = self.make_template_row()
        make_attachment(template, self.stored)

        body = self.preview(
            self.file_with_ids(f"{self.section.pk},Тригонометрия,,")
        ).json()

        self.assertEqual(body["with_attachments"], 1)
        self.assertEqual(body["files_lost"], 0)

    def test_preview_lists_every_bad_id_at_once(self):
        body = self.preview(
            self.file_with_ids("9999998,,Первый,", "9999999,,Второй,")
        ).json()

        self.assertEqual([error["code"] for error in body["errors"]],
                         ["csv_id_unknown", "csv_id_unknown"])
        self.assertEqual(body["errors"][0]["params"]["row"], 2)

    def make_template_row(self):
        from library.models import PlanTemplateRow
        from schools.testing import make_template

        template = make_template(self.school, self.user, rows=((False, "Урок"),))
        return PlanTemplateRow.objects.get(template=template)
