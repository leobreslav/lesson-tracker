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

    def redo(self):
        return self.client.post(
            f"{reverse('plannode-redo')}?course={self.course.pk}", {}, format="json"
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
        """
        «Вернул не то» не должно быть тупиком — но возвращает это `redo`.

        Возвращала это вторая отмена, и ровно поэтому отменить больше одного
        действия было нельзя: нажатие через раз шло назад, а через раз
        вперёд. Тупика по-прежнему нет, просто у двух разных движений теперь
        две разные кнопки, и каждая называет, что сделает.
        """
        self.lesson("Первый", position=0)
        node = self.lesson("Второй", position=1)

        self.client.delete(reverse("plannode-detail", args=[node.pk]))
        self.undo()
        self.assertEqual(self.titles(), ["Первый", "Второй"])

        answer = self.redo()

        self.assertEqual(answer.status_code, 200, answer.content)
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


class UndoDoesNotDestroyARecordTests(SnapshotTestCase):
    """
    Пятая дверь к удалению проведённой строки — и она была открыта.

    Четыре остальные закрыты давно: одиночное удаление и пакетное отвечают
    `plan_delete_taught`, импорт в обоих режимах и взятие с полки —
    `plan_import_taught`. Отмена не отвечала ничем: `Slot.lesson` — это
    `SET_NULL`, поэтому удаление строки не отказывает, а **молча**
    развязывает связь, и час, который был проведён и записан, остаётся без
    записи. Пост-условие про очередь этого не ловит: `broken_record` ищет
    незакрытый час среди закрытых, а развязанный последний час дыры не
    образует — то есть после потери всё выглядит здоровым.

    Случай узкий: строку завели **после** снимка, по ней провели урок,
    потом нажали отмену. Узкий он ровно потому, что опасный: учитель
    отменяет лишнюю строку, а теряет журнальную запись урока.
    """

    def setUp(self):
        super().setUp()
        from datetime import timedelta

        from schedule.models import Slot
        from schools.testing import make_slot

        self.Slot = Slot
        # снимок, к которому будет возвращать отмена: в нём есть «Первый»
        # и нет «Второго»
        self.first = self.lesson("Первый", position=0)
        self.client.post(
            reverse("plannode-list"),
            {"course": self.course.pk, "title": "Второй", "position": 1},
            format="json",
        )
        self.second = PlanNode.objects.get(course=self.course, title="Второй")

        self.slot = make_slot(
            self.user, self.course, timezone.now().date() - timedelta(days=1), 1
        )
        self.slot.lesson = self.second
        self.slot.save(update_fields=["lesson"])

    def test_undoing_a_row_that_has_since_been_taught_is_refused(self):
        answer = self.undo()

        self.assertEqual(answer.status_code, 400, answer.content)
        self.assertEqual(answer.json()["code"], "plan_undo_would_lose_record")

    def test_the_record_survives_the_refusal(self):
        """
        Главное тут не код отказа, а то, что запись осталась на месте.

        `restore` атомарен, значит отказ посреди восстановления обязан
        откатить и то, что успели воскресить, — иначе план остался бы в
        состоянии, которого не просил никто.
        """
        self.undo()

        self.slot.refresh_from_db()
        self.assertEqual(self.slot.lesson_id, self.second.pk)
        self.assertEqual(self.titles(), ["Первый", "Второй"])

    def test_a_row_nobody_taught_still_goes(self):
        """
        Отказ узкий, а не «отмена на курсе с занятиями не работает».

        Строка без записи удаляется отменой как раньше: закрыт проход к
        проведённому уроку, а не отмена вообще.
        """
        self.slot.lesson = None
        self.slot.save(update_fields=["lesson"])

        answer = self.undo()

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.titles(), ["Первый"])


class UndoBringsBackTheBankMarkupTests(SnapshotTestCase):
    """
    Разметка задачника переживает отмену — как переживают её вложения.

    `bank.Introduction` держится за строку плана `CASCADE`: удалили строку —
    пометка «этот урок вводит это понятие» ушла. Отмена возвращала строку с
    прежним номером, и этого хватало вложениям (снимок держит их сам), но не
    пометке: её не было ни в снимке, ни где-либо ещё. То есть отмена
    удаления возвращала урок без половины того, что про него знали.

    Разница между двумя связями решением не была: про вложения подумали, про
    задачник — нет. Чтобы третьей такой связи не появилось молча, стоит
    сторож `EveryRelationToAPlanRowSurvivesUndoOrRefusesItTests`.
    """

    def setUp(self):
        super().setUp()
        from bank.models import OBJECT, Introduction, Tag
        from bank.topics import introduce

        self.Introduction = Introduction
        self.node = self.lesson("Синус суммы")
        self.tag = Tag.objects.create(kind=OBJECT, name="синус суммы")
        introduce(self.course, self.node, self.tag)

    def marks(self):
        return {
            (row.tag_id, row.node_id)
            for row in self.Introduction.objects.filter(course=self.course)
        }

    def test_a_deleted_lesson_comes_back_with_its_markup(self):
        self.client.delete(reverse("plannode-detail", args=[self.node.pk]))
        self.assertEqual(self.marks(), set(), "каскад должен был унести пометку")

        answer = self.undo()

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.marks(), {(self.tag.pk, self.node.pk)})

    def test_a_mark_made_after_the_snapshot_goes_away(self):
        """
        Состояние восстанавливается целиком, а не дополняется.

        Иначе отмена умела бы возвращать пометки, но не снимать их, и
        «вернуть как было» означало бы «как было, плюс всё, что успели».
        """
        from bank.models import OBJECT, Tag
        from bank.topics import introduce

        second = self.lesson("Косинус суммы", position=1)
        # снимок: одна пометка
        self.client.patch(
            reverse("plannode-detail", args=[second.pk]),
            {"title": "Косинус разности"},
            format="json",
        )
        late = Tag.objects.create(kind=OBJECT, name="косинус разности")
        introduce(self.course, second, late)

        self.undo()

        self.assertEqual(self.marks(), {(self.tag.pk, self.node.pk)})

    def test_a_mark_moved_after_the_snapshot_comes_back_to_its_lesson(self):
        """
        Понятие вводится однажды, и отмена возвращает его тому уроку.

        Перевесили пометку на соседний урок, передумали — отмена обязана
        вернуть её на место, а не завести вторую: `one_lesson_introduces_a_tag`
        такого не пустит, и восстановление легло бы отказом базы.
        """
        from bank.topics import introduce

        second = self.lesson("Косинус суммы", position=1)
        self.client.patch(
            reverse("plannode-detail", args=[second.pk]),
            {"title": "Косинус разности"},
            format="json",
        )
        introduce(self.course, second, self.tag)

        answer = self.undo()

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.marks(), {(self.tag.pk, self.node.pk)})


class ARefusedEditLeavesNoStepTests(SnapshotTestCase):
    """
    Отвергнутая правка не оставляет следа в журнале.

    Снимок снимается **до** правки — иначе он отвечал бы на «как стало», а не
    на «как было», — и у него свой атомарный блок. Пока вызов стоял снаружи
    транзакции записи, отказ ниже снимок не уносил: правка не состоялась, а
    шаг в журнале появился.

    Стоит это трёх разных бед, и третья живёт дольше всех. Кнопка отмены
    предлагает отменить действие, которого не было, — и, нажатая, отменяет
    предыдущее настоящее. Пустые шаги вытесняют настоящие из двадцати, что
    держит `prune`. А если отвергнутую правку пробовал не ведущий курса,
    снимок ложится с `by_lead=False`, живёт девяносто дней и показывается
    учителю пометкой «в вашем плане поработал администратор» — про правку,
    которой не было.
    """

    def steps(self):
        return history.PlanSnapshot.objects.filter(course=self.course).count()

    def test_a_bad_direction_does_not_grow_the_journal(self):
        node = self.lesson("Синус суммы")
        before = self.steps()

        answer = self.client.post(
            reverse("plannode-move", args=[node.pk]),
            {"direction": "вбок"},
            format="json",
        )

        self.assertEqual(answer.status_code, 400, answer.content)
        self.assertEqual(self.steps(), before)

    def test_a_refused_delete_does_not_grow_the_journal(self):
        """Отказ приходит после снимка — значит транзакция обязана его унести."""
        from datetime import timedelta

        from schools.testing import make_slot

        node = self.lesson("Синус суммы")
        slot = make_slot(
            self.user, self.course, timezone.now().date() - timedelta(days=1), 1
        )
        slot.lesson = node
        slot.save(update_fields=["lesson"])
        before = self.steps()

        answer = self.client.delete(reverse("plannode-detail", args=[node.pk]))

        self.assertEqual(answer.status_code, 400, answer.content)
        self.assertEqual(self.steps(), before)

    def test_a_refused_batch_delete_does_not_grow_the_journal(self):
        node = self.lesson("Синус суммы")
        section = self.lesson("Тригонометрия", position=1, section=True)
        before = self.steps()

        # тема в пачке не удаляется: у неё спрашивают про уроки отдельно
        answer = self.client.post(
            f"{reverse('plannode-delete-many')}?course={self.course.pk}",
            {"ids": [node.pk, section.pk]},
            format="json",
        )

        self.assertEqual(answer.status_code, 400, answer.content)
        self.assertEqual(self.steps(), before)

    def test_a_successful_edit_still_leaves_its_step(self):
        """
        Обратная сторона: транзакция не должна съесть настоящий снимок.

        Проверка нужна ровно потому, что первая мысль при этой правке —
        «снять снимок после записи»: тогда отказ его действительно не
        оставит, но и отменять будет нечего.
        """
        node = self.lesson("Синус суммы")
        before = self.steps()

        answer = self.client.patch(
            reverse("plannode-detail", args=[node.pk]),
            {"title": "Синус"},
            format="json",
        )

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(self.steps(), before + 1)


class WalkingTheHistoryTests(SnapshotTestCase):
    """
    Отмена ходит по ленте состояний, а не переключает два последних.

    Замечание пришло от учителя и звучало дословно: «если ты нажал undo, то
    последним действием должно считаться предпоследнее, а не последнее.
    Потому что в текущем виде undo не помогает отменить более одного
    действия, зацикливаясь на undo: undo».

    Так и было, и причина в устройстве: журнал хранит состояния **перед**
    действиями, состояние после последнего живёт в самом плане, а указателя
    «где мы сейчас на этой ленте» не было вовсе. Отмена подменяла его тем,
    что дописывала в журнал ещё один снимок, — и следующая отмена целилась
    уже в него.
    """

    def add(self, title):
        return self.client.post(
            reverse("plannode-list"),
            {"course": self.course.pk, "title": title},
            format="json",
        )

    def three(self):
        self.lesson("Первый", position=0)
        for title in ("Второй", "Третий"):
            self.add(title)

    def steps(self):
        return self.client.get(
            f"{reverse('plannode-plan-history')}?course={self.course.pk}"
        ).json()

    def test_two_undos_in_a_row_walk_two_steps_back(self):
        self.three()

        self.undo()
        self.assertEqual(self.titles(), ["Первый", "Второй"])
        self.undo()
        self.assertEqual(self.titles(), ["Первый"])

    def test_the_walk_stops_at_the_oldest_state(self):
        """Дойдя до начала ленты, отмена отказывает, а не ходит по кругу."""
        self.three()

        for _ in range(3):
            self.undo()

        answer = self.undo()

        self.assertEqual(answer.status_code, 400, answer.content)
        self.assertEqual(answer.json()["code"], "plan_nothing_to_undo")

    def test_walking_back_writes_to_the_journal_once(self):
        """
        Двенадцать шагов назад стоят одной записи, а не двенадцати.

        Раньше каждое нажатие клало снимок, и двадцать нажатий выносили из
        журнала всю настоящую историю — двадцать держится на план. То есть
        человек, нажимавший «отменить», терял возможность отменить.
        """
        self.three()
        before = history.PlanSnapshot.objects.filter(course=self.course).count()

        self.undo()
        self.undo()

        after = history.PlanSnapshot.objects.filter(course=self.course).count()
        self.assertEqual(after, before + 1)

    def test_walking_forward_brings_the_steps_back(self):
        """«Отменил двенадцать, а решил вернуться на два»."""
        self.three()
        self.undo()
        self.undo()
        self.assertEqual(self.titles(), ["Первый"])

        self.redo()
        self.assertEqual(self.titles(), ["Первый", "Второй"])
        self.redo()
        self.assertEqual(self.titles(), ["Первый", "Второй", "Третий"])

    def test_a_full_round_trip_leaves_no_trace(self):
        """
        Отменил и вернул — журнал такой же, каким был.

        Снимок, снятый ради самого хода, к этому моменту хранит то же
        состояние, что и живой план. Оставить его значило бы предложить
        «отменить отмену» — то самое, с чего началось замечание.
        """
        self.three()
        before = list(
            history.PlanSnapshot.objects.filter(course=self.course)
            .order_by("id")
            .values_list("pk", flat=True)
        )

        self.undo()
        self.undo()
        self.redo()
        self.redo()

        after = list(
            history.PlanSnapshot.objects.filter(course=self.course)
            .order_by("id")
            .values_list("pk", flat=True)
        )
        self.assertEqual(after, before)
        self.assertEqual(self.titles(), ["Первый", "Второй", "Третий"])

    def test_at_the_end_of_the_tape_there_is_nothing_to_bring_back(self):
        self.three()

        answer = self.redo()

        self.assertEqual(answer.status_code, 400, answer.content)
        self.assertEqual(answer.json()["code"], "plan_nothing_to_redo")

    def test_an_edit_cuts_off_the_branch_ahead(self):
        """
        Отошли назад и стали писать оттуда — вперёд возвращать больше некуда.

        Так ведёт себя всякая отмена, и неожиданностью это не будет; важно,
        что кнопка «Вернуть» при этом исчезает, а не обещает ветку, которой
        у плана уже нет.
        """
        self.three()
        self.undo()
        self.undo()

        self.add("Другой")

        answer = self.redo()
        self.assertEqual(answer.status_code, 400, answer.content)
        self.assertEqual(answer.json()["code"], "plan_nothing_to_redo")
        self.assertEqual(self.titles(), ["Первый", "Другой"])

    def test_the_buttons_name_what_they_will_do(self):
        """
        Сервер говорит цели обеих кнопок, и «Вернуть» называет **действие**.

        Считать это на клиенте нельзя: правило непростое, а второй его
        расчёт разъехался бы молча. Ровно так и жила прежняя кнопка — брала
        самый свежий снимок и после отмены предлагала «отменить отмену».
        """
        self.three()

        fresh = self.steps()
        self.assertEqual(fresh["undo"]["action"], "create")
        self.assertIsNone(fresh["redo"])

        self.undo()

        walking = self.steps()
        self.assertEqual(walking["undo"]["action"], "create")
        self.assertEqual(
            walking["redo"]["action"],
            "create",
            "«Вернуть» называет действие, которое вернёт, а не снимок хода",
        )

    def test_the_abandoned_branch_is_not_offered(self):
        """Брошенное не показывается в списке: обещать его сервер не станет."""
        self.three()
        self.undo()
        self.undo()
        self.add("Другой")

        actions = [step["action"] for step in self.steps()["steps"]]

        self.assertNotIn("undo", actions)
