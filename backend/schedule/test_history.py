"""
Отмена последнего действия в расписании.

Проверяется не «снимок снялся», а то, ради чего он снимается: удалённый час
возвращается **тем же самым**, созданное действием исчезает, а действие,
прошедшее по нескольким курсам, отменяется целиком.

Полноту вызовов сторожит `test_history_wiring.py` — здесь про поведение.
"""

from datetime import timedelta

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import (
    MONDAY,
    SchoolTestMixin,
    assign,
    make_course,
    make_node,
    make_slot,
    make_user,
    make_year,
)

from . import history
from .models import Attendance, Slot
from .test_debts import DebtTestCase


class ScheduleUndoTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year, name="9Б")
        assign(self.user, self.course)
        self.slot = make_slot(self.user, self.course, day=MONDAY, number=1)

    def undo(self, **body):
        return self.client.post(
            f"{reverse('slot-undo')}?course={self.course.pk}", body, format="json"
        )

    def steps(self):
        return self.client.get(
            f"{reverse('slot-history')}?course={self.course.pk}"
        ).data["steps"]

    # --- то, ради чего всё это ---

    def test_a_deleted_lesson_comes_back_with_the_very_same_id(self):
        """
        Не «похожий час на том же месте», а тот самый.

        На занятии висят посещаемость и заданные работы, и клетка с новым
        номером — это уже не она: журнал ушёл бы каскадом, работы потеряли
        бы привязку. Тот же довод, по которому строка плана воскресает со
        своим id.
        """
        gone = self.slot.pk
        answer = self.client.delete(reverse("slot-detail", args=[gone]))
        self.assertEqual(answer.status_code, 204)
        self.assertFalse(Slot.objects.filter(pk=gone).exists())

        self.assertEqual(self.undo().status_code, 200)
        self.assertTrue(Slot.objects.filter(pk=gone).exists())

    def test_undo_takes_away_what_the_action_created(self):
        """Ряд до конца года заводит тридцать часов — отмена убирает все."""
        answer = self.client.post(
            reverse("slot-repeat"),
            {
                "course": self.course.pk,
                "date": str(MONDAY),
                "lesson_number": 3,
                "until": str(MONDAY + timedelta(days=28)),
            },
            format="json",
        )
        self.assertEqual(answer.status_code, 200, answer.data)
        grown = Slot.objects.filter(course=self.course).count()
        self.assertGreater(grown, 1)

        self.assertEqual(self.undo().status_code, 200)
        self.assertEqual(Slot.objects.filter(course=self.course).count(), 1)

    def test_the_journal_comes_back_with_the_resurrected_lesson(self):
        """
        Посещаемость уходит вместе с часом каскадом, и снимок её несёт.

        Иначе отмена вернула бы клетку, но не то, что в ней было записано, —
        а это и есть работа, которую человек отменять не просил.
        """
        student = make_user(self.school, "pupil@example.com", student=True)
        Attendance.objects.create(
            slot=self.slot, student=student, status=Attendance.Status.PRESENT
        )

        self.client.delete(reverse("slot-detail", args=[self.slot.pk]))
        self.assertEqual(Attendance.objects.count(), 0)

        self.undo()
        back = Attendance.objects.get()
        self.assertEqual(back.slot_id, self.slot.pk)
        self.assertEqual(back.student_id, student.pk)

    def test_the_journal_of_a_lesson_that_never_moved_is_left_alone(self):
        """
        Отменяют действие **с расписанием**, а не работу в журнале.

        Час всё это время стоял на месте, а после снимка ему отметили
        присутствие. Откат расписания стирать эту отметку не вправе: человек
        отменял не её.
        """
        second = make_slot(self.user, self.course, day=MONDAY, number=2)
        self.client.delete(reverse("slot-detail", args=[second.pk]))

        student = make_user(self.school, "pupil@example.com", student=True)
        Attendance.objects.create(
            slot=self.slot, student=student, status=Attendance.Status.ABSENT
        )

        self.undo()

        self.assertEqual(Attendance.objects.count(), 1)
        self.assertEqual(Attendance.objects.get().status, Attendance.Status.ABSENT)

    def test_nothing_to_undo_is_a_refusal_and_not_a_silent_success(self):
        """Молчаливый ноль читается как «отменил» — и человек уходит ни с чем."""
        answer = self.undo()

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "slot_nothing_to_undo")

    def test_the_undo_itself_can_be_undone(self):
        """«Вернул не то» не должно быть тупиком."""
        gone = self.slot.pk
        self.client.delete(reverse("slot-detail", args=[gone]))
        self.undo()
        self.assertTrue(Slot.objects.filter(pk=gone).exists())

        self.assertEqual(self.undo().status_code, 200)
        self.assertFalse(Slot.objects.filter(pk=gone).exists())

    def test_the_button_can_name_what_it_will_undo(self):
        """Безымянная отмена страшнее, чем полезна."""
        self.client.delete(reverse("slot-detail", args=[self.slot.pk]))

        steps = self.steps()
        self.assertEqual(steps[0]["action"], "delete")
        self.assertEqual(steps[0]["detail"], str(MONDAY))
        self.assertTrue(steps[0]["mine"])

    # --- действие на несколько курсов ---

    def test_a_school_wide_copy_is_undone_for_every_course_at_once(self):
        """
        Вернуть один курс из двух значит собрать расписание, которого не было.

        Копирование без курса идёт по всем, кого спрашивающий вправе править,
        и снимки у него лежат под одной партией.
        """
        other = make_course(self.school, self.year, name="9В")
        assign(self.user, other)
        # вторым часом, а не первым: учитель один на оба курса, и два
        # занятия в один номер — это его занятость, а не наш случай
        make_slot(self.user, other, day=MONDAY, number=2)

        answer = self.client.post(
            reverse("slot-copy"),
            {
                "source_start": str(MONDAY),
                "source_end": str(MONDAY + timedelta(days=6)),
                "target_start": str(MONDAY + timedelta(days=7)),
                "target_end": str(MONDAY + timedelta(days=13)),
            },
            format="json",
        )
        self.assertEqual(answer.status_code, 200, answer.data)
        self.assertEqual(Slot.objects.filter(course=self.course).count(), 2)
        self.assertEqual(Slot.objects.filter(course=other).count(), 2, answer.data)

        self.assertEqual(self.undo().status_code, 200)

        self.assertEqual(Slot.objects.filter(course=self.course).count(), 1)
        self.assertEqual(
            Slot.objects.filter(course=other).count(),
            1,
            "соседний курс остался с копией: партия отменилась наполовину",
        )

    # --- хранение ---

    def test_only_the_last_steps_are_kept(self):
        """
        Двадцать шагов на курс — та же граница, что у плана.

        Отменяют почти всегда последние минуты, а стек без границы растёт
        вместе с годом.
        """
        for number in range(2, history.KEEP_PER_COURSE + 5):
            # по дням, а не по номерам: уроков в дне не больше десяти
            make_slot(
                self.user, self.course, day=MONDAY + timedelta(days=number), number=1
            ).delete()
            history.take(self.course, self.user, "delete", str(number))

        self.assertEqual(
            history.SlotSnapshot.objects.filter(course=self.course).count(),
            history.KEEP_PER_COURSE,
        )

    # --- экран расписания курса не знает ---

    def test_the_last_step_is_found_without_naming_a_course(self):
        """
        Учебный план всегда открыт на одном курсе, расписание — нет.

        На «Моём расписании» за пять минут правят три курса подряд, и
        «отменить последнее» там значит последнее вообще. Курс поэтому не
        спрашивается, а находится по самому свежему снимку.
        """
        other = make_course(self.school, self.year, name="9Г")
        assign(self.user, other)
        far = make_slot(self.user, other, day=MONDAY, number=4)

        self.client.delete(reverse("slot-detail", args=[far.pk]))

        steps = self.client.get(reverse("slot-history")).data["steps"]
        self.assertEqual(steps[0]["action"], "delete")

        self.assertEqual(
            self.client.post(reverse("slot-undo"), {}, format="json").status_code, 200
        )
        self.assertTrue(Slot.objects.filter(pk=far.pk).exists())

    def test_without_a_course_and_without_any_step_it_still_refuses(self):
        """Пустая история — тот же отказ, а не пятисотка на пустом месте."""
        answer = self.client.post(reverse("slot-undo"), {}, format="json")

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "slot_nothing_to_undo")

    # --- каждый пишущий путь возвращается, а не только удаление ---

    def test_a_cancelled_lesson_comes_back_uncancelled(self):
        """Правка часа — тоже действие, и она тоже отменяется."""
        answer = self.client.patch(
            reverse("slot-detail", args=[self.slot.pk]),
            {"is_cancelled": True, "reason": "заболел"},
            format="json",
        )
        self.assertEqual(answer.status_code, 200, answer.data)

        self.undo()

        self.slot.refresh_from_db()
        self.assertFalse(self.slot.is_cancelled)
        self.assertEqual(self.slot.reason, "")

    def test_a_move_is_undone_on_both_sides_at_once(self):
        """
        Перенос — одно движение, но **две** записи: старое место отменяется,
        на новом появляется дополнительный час. Отмена обязана убрать обе, а
        не одну: половина отменённого переноса — состояние, которого не было.
        """
        answer = self.client.post(
            reverse("slot-move", args=[self.slot.pk]),
            {
                "date": str(MONDAY + timedelta(days=1)),
                "lesson_number": 3,
                "reason": "перенос",
            },
            format="json",
        )
        # 201: перенос **создаёт** дополнительный час на новом месте
        self.assertEqual(answer.status_code, 201, answer.data)
        self.assertEqual(Slot.objects.filter(course=self.course).count(), 2)

        self.undo()

        self.assertEqual(Slot.objects.filter(course=self.course).count(), 1)
        self.slot.refresh_from_db()
        self.assertFalse(self.slot.is_cancelled, "старое место осталось отменённым")

    def test_a_room_given_to_the_whole_row_is_taken_back(self):
        """Кабинет ставят ряду одним движением — и снимают одним же."""
        from .models import Room

        room = Room.objects.create(school=self.school, name="214")
        later = make_slot(
            self.user, self.course, day=MONDAY + timedelta(days=7), number=1
        )

        answer = self.client.post(
            reverse("slot-room", args=[self.slot.pk]),
            {"room": room.pk, "mode": "series"},
            format="json",
        )
        self.assertEqual(answer.status_code, 200, answer.data)
        later.refresh_from_db()
        self.assertEqual(later.room_id, room.pk)

        self.undo()

        for one in (self.slot, later):
            one.refresh_from_db()
            self.assertIsNone(one.room_id)

    def test_a_bulk_sweep_is_undone(self):
        """Массовая уборка сносит пачку — отмена возвращает её целиком."""
        for day in range(1, 4):
            make_slot(self.user, self.course, day=MONDAY + timedelta(days=day), number=1)
        self.assertEqual(Slot.objects.filter(course=self.course).count(), 4)

        answer = self.client.delete(
            f"{reverse('slot-bulk')}?course={self.course.pk}"
            f"&start={MONDAY}&end={MONDAY + timedelta(days=7)}&only_regular=true"
        )
        self.assertEqual(answer.status_code, 200, answer.data)
        self.assertEqual(Slot.objects.filter(course=self.course).count(), 0)

        self.undo()

        self.assertEqual(Slot.objects.filter(course=self.course).count(), 4)

    # --- чего отмена делать не станет ---

    def test_undo_refuses_to_take_away_what_was_recorded_after_the_snapshot(self):
        """
        Отмена — не задняя дверь в обход «занятие с записью не удаляют».

        Между снимком и нажатием на новой клетке могли отметить присутствие —
        вторым человеком или в соседней вкладке. Молча унести это значит
        потерять работу, которую никто не отменял, поэтому тут отказ, а не
        тихий успех.
        """
        student = make_user(self.school, "pupil@example.com", student=True)

        answer = self.client.post(
            reverse("slot-list"),
            {
                "course": self.course.pk,
                "date": str(MONDAY + timedelta(days=1)),
                "lesson_number": 2,
            },
            format="json",
        )
        self.assertEqual(answer.status_code, 201, answer.data)
        fresh = Slot.objects.get(pk=answer.data["id"])

        Attendance.objects.create(
            slot=fresh, student=student, status=Attendance.Status.PRESENT
        )

        refused = self.undo()

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.data["code"], "slot_undo_would_lose_work")
        self.assertTrue(Slot.objects.filter(pk=fresh.pk).exists())
        self.assertEqual(Attendance.objects.count(), 1)

    def test_the_record_itself_comes_back(self):
        """
        Связь часа со строкой плана — то, ради чего половина правил очереди.

        Проверяется на самой механике, а не через ручку: записать можно
        только прошедший час и только подсказанную строку, и городить ради
        одного поля живой курс с прошлым значило бы проверять правила
        записи, а не возврат.
        """
        row = make_node(self.user, self.course, title="Первый урок")
        self.slot.lesson = row
        self.slot.save(update_fields=["lesson"])

        history.take(self.course, self.user, "edit", str(self.slot.date))

        self.slot.lesson = None
        self.slot.save(update_fields=["lesson"])

        history.restore(history.last_for(self.course))

        self.slot.refresh_from_db()
        self.assertEqual(self.slot.lesson_id, row.pk)


class ClosingUndoTests(DebtTestCase):
    """
    Отмена там, где на кону сама запись: закрытие долгов и очередь.

    Обвязка взята у тестов долгов (`DebtTestCase`) — живой год, прошедшие
    часы, строки плана. Свою заводить незачем: она отличалась бы от той, на
    которой правила записи и проверяются.
    """

    def undo(self):
        return self.client.post(
            f"{reverse('slot-undo')}?course={self.course.pk}", {}, format="json"
        )

    def test_closing_the_debts_in_one_go_is_undone_in_one_go(self):
        """
        Пачку закрыли одним движением — и отменяют её одним же.

        Половина отменённой пачки хуже неотменённой: непонятно, какая
        половина, а очередь записей строгая и дырок не прощает.
        """
        owed = self.slot_on(2)
        also = self.slot_on(1, number=2)

        answer = self.client.post(
            reverse("slot-close"),
            {
                "closed": [
                    {"slot": owed.pk, "lesson": self.first.pk},
                    {"slot": also.pk, "lesson": self.second.pk},
                ]
            },
            format="json",
        )
        self.assertEqual(answer.status_code, 200, answer.data)
        for one, row in ((owed, self.first), (also, self.second)):
            one.refresh_from_db()
            self.assertEqual(one.lesson_id, row.pk)

        self.assertEqual(self.undo().status_code, 200)

        for one in (owed, also):
            one.refresh_from_db()
            self.assertIsNone(one.lesson_id, "запись пережила отмену закрытия")

    def test_a_restore_that_would_break_the_queue_is_refused(self):
        """
        Пост-условие очереди стоит и на откате — и это не формальность.

        Дырка — это **пропуск между записями**, а не любой незакрытый час:
        часы до первой записи «до начала учёта» и никому ничего не должны.
        Поэтому их тут три: закрыли все, а откат снимает запись у среднего.

        Собрать такое ручками нельзя: снимок берётся перед каждым действием,
        и каждое действие само проверяет очередь — то есть снимок всегда
        описывает исправное расписание. Дырка строится **мимо ручек**, прямо
        в базе: так проверяется, что откат спрашивает очередь сам, а не
        полагается на исправность снимка. Первая же правка, обошедшая
        журнал, иначе внесла бы дыру, и нашёл бы её не тест, а человек,
        которому очередь отказалась записывать следующий час.
        """
        third = make_node(self.user, self.course, "Тангенс суммы", position=2)
        first_hour = self.slot_on(3)
        middle = self.slot_on(2, number=2)
        last_hour = self.slot_on(1, number=3)

        answer = self.client.post(
            reverse("slot-close"),
            {
                "closed": [
                    {"slot": first_hour.pk, "lesson": self.first.pk},
                    {"slot": middle.pk, "lesson": self.second.pk},
                    {"slot": last_hour.pk, "lesson": third.pk},
                ]
            },
            format="json",
        )
        self.assertEqual(answer.status_code, 200, answer.data)

        # дырка ровно посередине: запись — пропуск — запись
        middle.lesson = None
        middle.save(update_fields=["lesson"])
        history.take(self.course, self.user, "edit", str(middle.date))

        # а в базе всё снова подряд — значит откат её сломает
        middle.lesson = self.second
        middle.save(update_fields=["lesson"])

        refused = self.undo()

        self.assertEqual(refused.status_code, 400, refused.data)
        self.assertEqual(refused.data["code"], "slot_order_broken")
        middle.refresh_from_db()
        self.assertEqual(
            middle.lesson_id, self.second.pk, "откат применился, хотя был отклонён"
        )


class TheButtonFlipsToBringBackTests(ScheduleUndoTests):
    """
    Отмена в расписании односкоростная, и второе нажатие обязано это сказать.

    Движение «вернуть отменённое» было и раньше — им служило второе нажатие
    «Отменить», — но называлось оно отменой. Наружу это выходило надписью
    «Отменить: отмену» и расписанием, которое качалось между двумя
    состояниями: понять, куда попадёшь, было нельзя.

    Глубже одного шага тут по-прежнему не ходят, и это решение, а не
    недоделка: расписание правят и отменяют в одну минуту, а путь, которым
    интерфейс не пользуется, никто не проверяет.
    """

    def redo(self):
        return self.client.post(
            f"{reverse('slot-redo')}?course={self.course.pk}", {}, format="json"
        )

    def targets(self):
        return self.client.get(
            f"{reverse('slot-history')}?course={self.course.pk}"
        ).json()

    def test_after_an_undo_the_button_offers_to_bring_it_back(self):
        gone = self.slot.pk
        self.client.delete(reverse("slot-detail", args=[gone]))
        self.undo()

        targets = self.targets()

        self.assertIsNone(targets["undo"], "глубже одного шага тут не ходят")
        self.assertEqual(
            targets["redo"]["action"],
            "delete",
            "«Вернуть» называет отменённое действие, а не саму отмену",
        )

    def test_bringing_it_back_undoes_the_undo(self):
        gone = self.slot.pk
        self.client.delete(reverse("slot-detail", args=[gone]))
        self.undo()
        self.assertTrue(Slot.objects.filter(pk=gone).exists())

        answer = self.redo()

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertFalse(Slot.objects.filter(pk=gone).exists())

    def test_the_journal_does_not_grow_from_flipping(self):
        """
        Переключение туда-обратно не копит снимки.

        Держится их двадцать на курс, и, клади возврат свой снимок, десяток
        нажатий вытеснил бы всю настоящую историю — то есть человек, игравший
        кнопкой, остался бы без возможности отменить что-либо вообще.
        """
        self.client.delete(reverse("slot-detail", args=[self.slot.pk]))
        before = history.SlotSnapshot.objects.filter(course=self.course).count()

        for _ in range(4):
            self.undo()
            self.redo()

        after = history.SlotSnapshot.objects.filter(course=self.course).count()
        self.assertEqual(after, before)

    def test_with_no_undo_behind_it_there_is_nothing_to_bring_back(self):
        self.client.delete(reverse("slot-detail", args=[self.slot.pk]))

        answer = self.redo()

        self.assertEqual(answer.status_code, 400, answer.content)
        self.assertEqual(answer.json()["code"], "slot_nothing_to_redo")

    def test_an_edit_after_the_undo_cuts_the_branch(self):
        """Правка между отменой и возвратом обрывает ветку — как везде."""
        gone = self.slot.pk
        self.client.delete(reverse("slot-detail", args=[gone]))
        self.undo()
        make_slot(self.user, self.course, day=MONDAY + timedelta(days=3), number=2)
        self.client.delete(
            reverse(
                "slot-detail",
                args=[Slot.objects.filter(course=self.course).exclude(pk=gone).first().pk],
            )
        )

        answer = self.redo()

        self.assertEqual(answer.status_code, 400, answer.content)
        self.assertEqual(answer.json()["code"], "slot_nothing_to_redo")
