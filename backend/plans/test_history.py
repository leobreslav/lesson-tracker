"""
Журнал состояний плана: отмена, откат чужой правки и что переживает файл.

Проверяется не «снимок снялся», а то, ради чего он снимается: удалённая
строка возвращается **с содержанием и вложениями**, чужая правка
откатывается через недели, а объект в бакете доживает до отката.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from files.models import Attachment, StoredFile
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin, assign, make_course, make_node, make_year

from . import history
from .models import PlanNode


class SnapshotTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        assign(self.user, self.course)
        self.client.force_authenticate(self.user)

    def lesson(self, title, **extra):
        return make_node(self.user, self.course, title, **extra)

    def titles(self):
        return list(
            PlanNode.objects.filter(course=self.course)
            .order_by("position", "id")
            .values_list("title", flat=True)
        )

    def undo(self, snapshot=None):
        body = {"snapshot": snapshot} if snapshot else {}
        return self.client.post(
            f"{reverse('plannode-undo')}?course={self.course.pk}", body, format="json"
        )


class UndoTests(SnapshotTestCase):
    def test_a_deleted_lesson_comes_back_with_its_content(self):
        """
        Главный случай: удалил урок зря.

        Урок — это прежде всего его текст, поэтому снимок хранит содержание
        целиком, а не отпечаток, как эталон.
        """
        node = self.lesson("Синус суммы")
        node.body = "Теорема и три примера"
        node.save(update_fields=["body"])

        self.client.delete(reverse("plannode-detail", args=[node.pk]))
        self.assertEqual(self.titles(), [])

        answer = self.undo()

        self.assertEqual(answer.status_code, 200, answer.content)
        back = PlanNode.objects.get(course=self.course)
        self.assertEqual(back.title, "Синус суммы")
        self.assertEqual(back.body, "Теорема и три примера")

    def test_the_row_keeps_its_own_id(self):
        """
        Воскрешают строку, а не заводят похожую.

        За строкой стоят вложения, эталон и связь с занятием; новая строка
        с новым номером — это не она.
        """
        node = self.lesson("Синус суммы")

        self.client.delete(reverse("plannode-detail", args=[node.pk]))
        self.undo()

        self.assertEqual(PlanNode.objects.get(course=self.course).pk, node.pk)

    def test_a_section_deleted_with_its_lessons_comes_back_whole(self):
        section = self.lesson("Тригонометрия", section=True)
        self.lesson("Синус", parent=section, position=0)
        self.lesson("Косинус", parent=section, position=1)

        self.client.delete(
            f"{reverse('plannode-detail', args=[section.pk])}?keep_children=false"
        )
        self.assertEqual(self.titles(), [])

        self.undo()

        self.assertEqual(self.titles(), ["Тригонометрия", "Синус", "Косинус"])
        back = PlanNode.objects.get(title="Синус")
        self.assertEqual(back.parent.title, "Тригонометрия")

    def test_a_replacing_import_is_undone_by_one_press(self):
        """Самый ценный случай: `replace` стирает план целиком."""
        for index, title in enumerate(["Первый", "Второй", "Третий"]):
            self.lesson(title, position=index)

        answer = self.client.post(
            f"{reverse('plannode-import')}?course={self.course.pk}",
            {
                "file": self.csv("id,Тема,Урок\n,,Совсем другой\n"),
                "mode": "replace",
            },
            format="multipart",
        )
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.titles(), ["Совсем другой"])

        self.undo()

        self.assertEqual(self.titles(), ["Первый", "Второй", "Третий"])

    def csv(self, text):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile("plan.csv", text.encode("utf-8"), "text/csv")

    def test_a_move_is_undone(self):
        first = self.lesson("Первый", position=0)
        self.lesson("Второй", position=1)

        self.client.post(reverse("plannode-move", args=[first.pk]), {"direction": "down"}, format="json")
        self.assertEqual(self.titles(), ["Второй", "Первый"])

        self.undo()

        self.assertEqual(self.titles(), ["Первый", "Второй"])

    def test_the_undo_itself_can_be_undone(self):
        """«Вернул не то» не должно быть тупиком."""
        self.lesson("Первый", position=0)
        node = self.lesson("Второй", position=1)

        self.client.delete(reverse("plannode-detail", args=[node.pk]))
        self.undo()
        self.assertEqual(self.titles(), ["Первый", "Второй"])

        self.undo()

        self.assertEqual(self.titles(), ["Первый"])

    def test_with_nothing_kept_it_says_so(self):
        answer = self.undo()

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.json()["code"], "plan_nothing_to_undo")


class HistoryListTests(SnapshotTestCase):
    def test_the_list_names_the_action_and_what_it_touched(self):
        """Без имени кнопка отмены страшнее, чем полезна."""
        node = self.lesson("Синус суммы")
        self.client.delete(reverse("plannode-detail", args=[node.pk]))

        answer = self.client.get(
            f"{reverse('plannode-plan-history')}?course={self.course.pk}"
        )

        step = answer.json()["steps"][0]
        self.assertEqual(step["action"], "delete")
        self.assertEqual(step["detail"], "Синус суммы")
        self.assertTrue(step["mine"])
        self.assertTrue(step["by_lead"])


class InterventionTests(SnapshotTestCase):
    """Правка чужого: снимок помечен, живёт дольше и откатывается учителем."""

    def setUp(self):
        super().setUp()
        self.lesson("Первый")
        self.client.force_authenticate(self.admin)

    def test_an_edit_by_somebody_else_is_marked(self):
        self.client.post(
            reverse("plannode-list"),
            {"course": self.course.pk, "title": "Дописано завучем"},
            format="json",
        )

        step = history.PlanSnapshot.objects.filter(course=self.course).first()
        self.assertFalse(step.by_lead)
        self.assertEqual(step.made_by, self.admin)

    def test_the_teacher_undoes_what_the_admin_did(self):
        self.client.post(
            reverse("plannode-list"),
            {"course": self.course.pk, "title": "Дописано завучем"},
            format="json",
        )
        self.assertIn("Дописано завучем", self.titles())

        self.client.force_authenticate(self.user)
        answer = self.undo()

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.titles(), ["Первый"])


class RetentionTests(SnapshotTestCase):
    def test_the_stack_keeps_the_last_steps_and_forgets_the_rest(self):
        for index in range(history.KEEP_PER_PLAN + 5):
            self.client.post(
                reverse("plannode-list"),
                {"course": self.course.pk, "title": f"Урок {index}"},
                format="json",
            )

        self.assertEqual(
            history.PlanSnapshot.objects.filter(course=self.course).count(),
            history.KEEP_PER_PLAN,
        )

    def test_an_intervention_outlives_the_stack(self):
        """
        Про чужую правку учитель узнаёт, когда откроет план, — а это бывает
        через неделю. Поэтому такой снимок не вытесняется обычными шагами.
        """
        self.client.force_authenticate(self.admin)
        self.client.post(
            reverse("plannode-list"),
            {"course": self.course.pk, "title": "Дописано завучем"},
            format="json",
        )
        alien = history.PlanSnapshot.objects.filter(by_lead=False).get()

        self.client.force_authenticate(self.user)
        for index in range(history.KEEP_PER_PLAN + 5):
            self.client.post(
                reverse("plannode-list"),
                {"course": self.course.pk, "title": f"Урок {index}"},
                format="json",
            )

        self.assertTrue(history.PlanSnapshot.objects.filter(pk=alien.pk).exists())

    def test_an_old_intervention_is_forgotten_too(self):
        self.client.force_authenticate(self.admin)
        self.client.post(
            reverse("plannode-list"),
            {"course": self.course.pk, "title": "Давнее"},
            format="json",
        )
        stale = history.PlanSnapshot.objects.filter(by_lead=False).get()
        history.PlanSnapshot.objects.filter(pk=stale.pk).update(
            made_at=timezone.now()
            - timedelta(days=history.KEEP_INTERVENTION_DAYS + 1)
        )

        self.client.force_authenticate(self.user)
        for index in range(history.KEEP_PER_PLAN + 1):
            self.client.post(
                reverse("plannode-list"),
                {"course": self.course.pk, "title": f"Урок {index}"},
                format="json",
            )

        self.assertFalse(history.PlanSnapshot.objects.filter(pk=stale.pk).exists())


class FilesSurviveTests(SnapshotTestCase):
    """
    Вложения возвращаются вместе со строкой — и объект в бакете доживает.

    Удаление строки уносит её вложения каскадом, а с последней ссылкой
    умирает и объект в R2. Поэтому снимок ссылается на `StoredFile` сам:
    пока он жив, объект не сносится, и откат возвращает не пустую скрепку,
    а работающий файл.
    """

    def setUp(self):
        super().setUp()
        from schools.testing import make_stored_file

        self.node = self.lesson("Синус суммы")
        self.stored = make_stored_file(self.school, self.user)
        Attachment.objects.create(
            plan_row=self.node,
            kind="file",
            stored_file=self.stored,
            title="Карточка",
        )

    def test_the_object_outlives_the_deletion(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(reverse("plannode-detail", args=[self.node.pk]))

        self.assertFalse(Attachment.objects.exists(), "ссылка ушла вместе со строкой")
        self.assertTrue(
            StoredFile.objects.filter(pk=self.stored.pk).exists(),
            "объект держит снимок: иначе откат вернул бы вложение с 404",
        )

    def test_undo_brings_the_attachment_back_to_the_same_object(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(reverse("plannode-detail", args=[self.node.pk]))

        answer = self.undo()

        self.assertEqual(answer.status_code, 200, answer.content)
        back = Attachment.objects.get()
        self.assertEqual(back.plan_row_id, self.node.pk)
        self.assertEqual(back.stored_file_id, self.stored.pk)
        self.assertEqual(back.title, "Карточка")

    def test_the_object_goes_when_the_last_snapshot_expires(self):
        """
        Снимок истёк — его ссылка тоже была ссылкой.

        Иначе журнал стал бы местом, где файлы живут вечно: удалили строку,
        снимок вытеснился, а объект в бакете остался никому не нужным.
        """
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(reverse("plannode-detail", args=[self.node.pk]))

        with self.captureOnCommitCallbacks(execute=True):
            history.PlanSnapshot.objects.filter(course=self.course).delete()

        self.assertFalse(StoredFile.objects.filter(pk=self.stored.pk).exists())


class BulkDeleteKeepsTheQueueTests(SnapshotTestCase):
    """
    Пачечное удаление очередь записей не ломает — и вот почему.

    Проверено вопросом, а не рассуждением: удаляется строка, стоящая
    **между двумя записанными**, и очередь после этого спрашивается прямо.
    Дыра — это незакрытый прошедший час, а часы удаление плана не трогает;
    обгон — это две записи, у которых даты идут вперёд, а строки плана
    назад, и удаление непроведённой строки взаимного порядка записанных не
    меняет.

    Проведённую строку в пачке отклоняет `plan_delete_taught` — это
    проверено в `test_recorded`, а здесь важно обратное: законное удаление
    не оставляет за собой сломанной очереди.
    """

    def setUp(self):
        super().setUp()
        from datetime import timedelta

        from schedule.models import Slot
        from schools.testing import make_slot

        self.Slot = Slot
        self.rows = [
            self.lesson(f"Урок {index}", position=index) for index in range(4)
        ]
        first = timezone.now().date() - timedelta(days=5)
        self.slots = [
            make_slot(self.user, self.course, first + timedelta(days=index), 1)
            for index in range(4)
        ]
        for slot, row in zip(self.slots[:2], self.rows[:2]):
            slot.lesson = row
            slot.save(update_fields=["lesson"])

    def delete_many(self, ids):
        return self.client.post(
            f"{reverse('plannode-delete-many')}?course={self.course.pk}",
            {"ids": ids},
            format="json",
        )

    def test_a_row_between_two_records_goes_without_breaking_the_queue(self):
        answer = self.delete_many([self.rows[2].pk])

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertIsNone(
            self.Slot.broken_record(self.course, timezone.now().date()),
            "очередь записей должна остаться очередью",
        )

    def test_the_records_keep_their_hours(self):
        """Удаление плана часов не касается: связь остаётся на своём дне."""
        self.delete_many([self.rows[2].pk, self.rows[3].pk])

        for slot, row in zip(self.slots[:2], self.rows[:2]):
            slot.refresh_from_db()
            self.assertEqual(slot.lesson_id, row.pk)
