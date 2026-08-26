"""
Урок как запись о том, что было, а не только клетка сетки.

На уроке появились «что прошли» и «кто вёл», а работы теперь привязываются
к нему. Отсюда единственное новое правило, и оно защитное: **массовая
операция сносит только пустые клетки**. Урок, на котором что-то отметили,
стал историей, и «перекопировать неделю на год» не должно её стирать —
восстановить будет неоткуда.

Одиночное удаление при этом свободно, и это осознанно: нажать на клетку и
удалить её — обдуманное действие, а заданная работа его переживает
(`Work.lesson` — SET_NULL).
"""

from datetime import timedelta

from calendars import services as calendar_services
from calendars.models import DayException
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from schools.testing import (
    live_year,
    MONDAY,
    SchoolTestMixin,
    assign,
    make_course,
    make_node,
    make_slot,
    make_work,
    make_year,
)

from .models import Slot
from .services import sweepable


class LessonRecordTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        assign(self.user, self.course)
        self.topic = make_node(self.user, self.course, "Синус суммы")

    def clear(self, only_regular=True):
        return self.client.delete(
            reverse("slot-bulk")
            + f"?course={self.course.pk}&start={MONDAY}&end={MONDAY + timedelta(days=6)}"
            + f"&only_regular={only_regular}"
        )


class RecordTests(LessonRecordTestCase):
    def test_the_lesson_remembers_what_was_covered_and_who_taught_it(self):
        # запись идёт по прошедшему часу, а зашитый год стоит в будущем:
        # курсу нужен живой, иначе записывать нечего
        course = make_course(self.school, live_year(self.school), "9Б Живой")
        assign(self.user, course)
        topic = make_node(self.user, course, "Синус суммы")
        slot = make_slot(self.user, course, timezone.localdate() - timedelta(days=1))

        response = self.client.patch(
            reverse("slot-detail", args=[slot.pk]),
            {"lesson": topic.pk, "taught_by": self.colleague.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["lesson_title"], "Синус суммы")
        slot.refresh_from_db()
        self.assertEqual(slot.lesson, topic)
        self.assertEqual(slot.taught_by, self.colleague)

    def test_a_plan_lesson_of_another_course_cannot_be_named(self):
        other = make_course(self.school, self.year, "10А")
        theirs = make_node(self.colleague, other, "Чужая тема")
        slot = make_slot(self.user, self.course)

        response = self.client.patch(
            reverse("slot-detail", args=[slot.pk]),
            {"lesson": theirs.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)

    def test_deleting_the_plan_row_leaves_the_lesson_and_forgets_the_link(self):
        """Строку плана удалили, а урок был: связь уходит, факт остаётся."""
        slot = make_slot(self.user, self.course)
        slot.lesson = self.topic
        slot.save(update_fields=["lesson"])

        self.topic.delete()

        slot.refresh_from_db()
        self.assertIsNone(slot.lesson_id)

    def test_a_work_hangs_on_the_lesson_it_was_set_at(self):
        slot = make_slot(self.user, self.course)
        work = make_work(self.user, self.course)

        response = self.client.patch(
            reverse("work-detail", args=[work.pk]),
            {"slot": slot.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(list(slot.works.all()), [work])

    def test_deleting_the_lesson_keeps_the_work(self):
        slot = make_slot(self.user, self.course)
        work = make_work(self.user, self.course, slot=slot)

        self.client.delete(reverse("slot-detail", args=[slot.pk]))

        work.refresh_from_db()
        self.assertIsNone(work.slot_id)


class SweepTests(LessonRecordTestCase):
    """Что переживает массовую чистку, а что нет."""

    def test_an_empty_lesson_is_swept(self):
        make_slot(self.user, self.course)

        self.assertEqual(self.clear().json()["deleted"], 1)

    def test_a_lesson_that_remembers_the_topic_survives(self):
        slot = make_slot(self.user, self.course)
        slot.lesson = self.topic
        slot.save(update_fields=["lesson"])

        self.assertEqual(self.clear().json()["deleted"], 0)
        self.assertTrue(Slot.objects.filter(pk=slot.pk).exists())

    def test_a_lesson_with_a_substitute_survives(self):
        slot = make_slot(self.user, self.course)
        slot.taught_by = self.colleague
        slot.save(update_fields=["taught_by"])

        self.assertEqual(self.clear().json()["deleted"], 0)

    def test_a_lesson_with_a_work_survives(self):
        slot = make_slot(self.user, self.course)
        make_work(self.user, self.course, slot=slot)

        self.assertEqual(self.clear().json()["deleted"], 0)

    def test_without_only_regular_everything_goes(self):
        """Явная просьба «снести всё» — это уже не массовая уборка."""
        slot = make_slot(self.user, self.course)
        slot.lesson = self.topic
        slot.save(update_fields=["lesson"])

        self.assertEqual(self.clear(only_regular=False).json()["deleted"], 1)

    def test_replace_does_not_overwrite_a_lesson_with_a_record(self):
        """
        Раскатать неделю на год — самая массовая из операций, и именно её
        боятся: она проходит по всему году и стёрла бы историю разом.
        """
        source = make_slot(self.user, self.course, MONDAY, 1)
        kept = make_slot(self.user, self.course, MONDAY + timedelta(days=7), 4)
        kept.lesson = self.topic
        kept.save(update_fields=["lesson"])

        self.client.post(
            reverse("slot-copy"),
            {
                "course_id": self.course.pk,
                "source_start": MONDAY.isoformat(),
                "source_end": (MONDAY + timedelta(days=6)).isoformat(),
                "target_start": (MONDAY + timedelta(days=7)).isoformat(),
                "target_end": (MONDAY + timedelta(days=13)).isoformat(),
                "mode": "replace",
            },
            format="json",
        )

        self.assertTrue(Slot.objects.filter(pk=kept.pk).exists())
        self.assertTrue(Slot.objects.filter(pk=source.pk).exists())


class LessonFieldsTests(SchoolTestMixin, APITestCase):
    """
    Сторож над списком того, что считается записью.

    Правило «массовая операция сносит только пустые клетки» стоит ровно
    столько, сколько полон список. Пока он был написан руками — да ещё в
    двух местах сразу, — следующая вещь, повешенная на занятие, не попадала
    бы ни в один из них и уезжала бы под «очистить период» молча.

    Обратные связи теперь считаются записью сами, а собственные поля
    обязаны назваться: либо время (`GRID_FIELDS`), либо запись
    (`RECORD_FIELDS`). Незаписанное поле валит этот тест, а не чужой год.
    """

    def test_every_field_of_the_lesson_says_what_it_is(self):
        named = Slot.GRID_FIELDS | Slot.RECORD_FIELDS
        actual = {field.name for field in Slot._meta.get_fields() if field.concrete}

        self.assertEqual(
            actual - named,
            set(),
            "новое поле занятия не названо ни временем, ни записью: "
            "решите, переживает ли оно массовую чистку, и допишите его в "
            "Slot.GRID_FIELDS или Slot.RECORD_FIELDS",
        )
        self.assertEqual(named - actual, set(), "в списке поле, которого нет")

    def test_every_table_hanging_off_the_lesson_protects_it(self):
        """Не список, а обход модели: новая таблица защищена с рождения."""
        conditions = Slot.empty_conditions()

        for relation in Slot._meta.related_objects:
            self.assertIn(
                f"{relation.field.related_query_name()}__isnull",
                conditions,
                f"{relation.name} не мешает массовой чистке",
            )

    def test_the_sweep_and_the_lesson_agree_on_what_a_record_is(self):
        """Один вопрос — один ответ, и спрашивают его одним условием."""
        year = make_year(self.school)
        course = make_course(self.school, year, "9Б Алгебра")
        assign(self.user, course)
        empty = make_slot(self.user, course, MONDAY, 1)
        recorded = make_slot(self.user, course, MONDAY, 2)
        recorded.taught_by = self.colleague
        recorded.save(update_fields=["taught_by"])

        swept = set(sweepable(Slot.objects.filter(course=course)))

        self.assertEqual({slot.pk for slot in swept}, {empty.pk})
        self.assertFalse(empty.has_record())
        self.assertTrue(recorded.has_record())


class MoveTests(LessonRecordTestCase):
    """
    Перенос занятия: одно движение, две записи.

    Соблазн переписать дату велик, а цена его невидима до конца года:
    администрация читает календарную ось — сколько сорвано и чем закрыто, —
    и переписанная дата делает год идеально ровным. Поэтому старое место
    остаётся отменённым, новое появляется дополнительным, а всё, что
    занятие накопило, переезжает вместе с ним.
    """

    def setUp(self):
        super().setUp()
        self.slot = make_slot(self.user, self.course, MONDAY, 1)
        self.saturday = MONDAY + timedelta(days=5)

    def move(self, slot=None, **body):
        return self.client.post(
            reverse("slot-move", args=[(slot or self.slot).pk]),
            {"date": self.saturday.isoformat(), "lesson_number": 3, **body},
            format="json",
        )

    def test_the_old_place_keeps_the_scar(self):
        response = self.move(reason="учитель на конференции")

        self.assertEqual(response.status_code, 201, response.content)
        self.slot.refresh_from_db()
        self.assertTrue(self.slot.is_cancelled)
        self.assertEqual(self.slot.reason, "учитель на конференции")

    def test_the_new_place_is_an_extra_lesson(self):
        """Чтобы «отменено 1 · добавлено 1» сложилось в компенсацию."""
        moved = Slot.objects.get(pk=self.move().json()["id"])

        self.assertEqual((moved.date, moved.lesson_number), (self.saturday, 3))
        self.assertTrue(moved.is_extra)
        self.assertFalse(moved.is_cancelled)
        self.assertEqual(moved.course, self.course)

    def test_what_the_lesson_remembered_travels_with_it(self):
        self.slot.lesson = self.topic
        self.slot.taught_by = self.colleague
        self.slot.save(update_fields=["lesson", "taught_by"])

        moved = Slot.objects.get(pk=self.move().json()["id"])

        self.assertEqual(moved.lesson, self.topic)
        self.assertEqual(moved.taught_by, self.colleague)

    def test_the_place_left_behind_remembers_nothing(self):
        """Занятие не состоялось в среду — записи о среде быть не может."""
        self.slot.lesson = self.topic
        self.slot.save(update_fields=["lesson"])

        self.move()

        self.slot.refresh_from_db()
        self.assertIsNone(self.slot.lesson)

    def test_the_work_set_at_that_lesson_travels_too(self):
        work = make_work(self.user, self.course, title="Домашняя", slot=self.slot)

        moved_id = self.move().json()["id"]

        work.refresh_from_db()
        self.assertEqual(work.slot_id, moved_id)

    def test_moving_nowhere_is_refused(self):
        response = self.move(
            date=MONDAY.isoformat(), lesson_number=self.slot.lesson_number
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "slot_move_same_place")

    def test_an_occupied_hour_refuses_the_move(self):
        """Правила переноса не мягче правил создания: их считает один код."""
        other = make_course(self.school, self.year, "8А Алгебра")
        assign(self.user, other)
        make_slot(self.user, other, self.saturday, 3)

        response = self.move()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "slot_number_taken")

    def test_nothing_moves_when_the_target_is_refused(self):
        other = make_course(self.school, self.year, "8А Алгебра")
        assign(self.user, other)
        make_slot(self.user, other, self.saturday, 3)

        self.move()

        self.slot.refresh_from_db()
        self.assertFalse(self.slot.is_cancelled)

    def test_a_date_outside_the_year_is_refused(self):
        response = self.move(date=(self.year.end_date + timedelta(days=1)).isoformat())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "slot_outside_year")


class MoveSeriesTests(LessonRecordTestCase):
    """
    Второй вид переноса: не сорвался час, а сдвинулся ряд.

    Разовый перенос пишет отмену и дополнительное занятие, и это верно ровно
    тогда, когда занятие **не состоялось**. Расписание же меняют и насовсем
    — «вторник третьим часом теперь идёт средой вторым», — и тридцать отмен
    с тридцатью дополнительными объявили бы тридцать срывов, которых не
    было. Именно эти два числа читает администрация, поэтому у постоянной
    правки своя запись: дата переписывается, флаги не ставятся.

    Ряд здесь тот же, что у удаления ряда: курс, день недели, номер, — от
    этого часа и до конца года.
    """

    def setUp(self):
        super().setUp()
        # три понедельника подряд первым часом: ряд, который и переезжает
        self.mondays = [MONDAY + timedelta(days=7 * week) for week in range(3)]
        self.row = [make_slot(self.user, self.course, day, 1) for day in self.mondays]
        self.slot = self.row[0]
        self.wednesday = MONDAY + timedelta(days=2)

    def move(self, slot=None, **body):
        return self.client.post(
            reverse("slot-move", args=[(slot or self.slot).pk]),
            {
                "date": self.wednesday.isoformat(),
                "lesson_number": 2,
                "mode": "series",
                **body,
            },
            format="json",
        )

    def test_the_whole_row_changes_its_day_and_number(self):
        response = self.move()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"moved": 3, "skipped": 0, "kept": 0})
        for slot, monday in zip(self.row, self.mondays):
            slot.refresh_from_db()
            self.assertEqual(slot.date, monday + timedelta(days=2))
            self.assertEqual(slot.lesson_number, 2)

    def test_nothing_is_cancelled_and_nothing_is_extra(self):
        """Ради этого всё и затевалось: срыва не было, и следа быть не должно."""
        self.move()

        for slot in self.row:
            slot.refresh_from_db()
            self.assertFalse(slot.is_cancelled)
            self.assertFalse(slot.is_extra)
            self.assertEqual(slot.reason, "")

    def test_no_second_lesson_appears(self):
        self.assertEqual(Slot.objects.filter(course=self.course).count(), 3)

        self.move()

        self.assertEqual(Slot.objects.filter(course=self.course).count(), 3)

    def test_the_past_of_the_row_stays_where_it_was(self):
        """Расписание меняют вперёд: прошедшие часы — уже история."""
        past = make_slot(self.user, self.course, MONDAY - timedelta(days=7), 1)

        self.move()

        past.refresh_from_db()
        self.assertEqual(past.date, MONDAY - timedelta(days=7))
        self.assertEqual(past.lesson_number, 1)

    def test_another_weekday_and_another_number_are_not_this_row(self):
        tuesday = make_slot(self.user, self.course, MONDAY + timedelta(days=1), 1)
        fifth = make_slot(self.user, self.course, self.mondays[1], 5)

        self.move()

        for stranger, where in ((tuesday, MONDAY + timedelta(days=1)), (fifth, self.mondays[1])):
            stranger.refresh_from_db()
            self.assertEqual(stranger.date, where)

    def test_only_the_number_may_change(self):
        """«Тот же день, но третьим часом» — такая же постоянная правка."""
        response = self.move(date=MONDAY.isoformat(), lesson_number=3)

        self.assertEqual(response.status_code, 200, response.content)
        for slot, monday in zip(self.row, self.mondays):
            slot.refresh_from_db()
            self.assertEqual((slot.date, slot.lesson_number), (monday, 3))

    def test_an_hour_with_a_record_stays_on_the_day_it_happened(self):
        recorded = self.row[2]
        recorded.taught_by = self.colleague
        recorded.save(update_fields=["taught_by"])

        response = self.move()

        self.assertEqual(response.json(), {"moved": 2, "skipped": 0, "kept": 1})
        recorded.refresh_from_db()
        self.assertEqual(recorded.date, self.mondays[2])

    def test_a_cancelled_hour_of_the_row_stays_too(self):
        """Отменённый час — след срыва, и он привязан к своему дню."""
        self.row[1].is_cancelled = True
        self.row[1].save(update_fields=["is_cancelled"])

        response = self.move()

        self.assertEqual(response.json()["kept"], 1)
        self.row[1].refresh_from_db()
        self.assertEqual(self.row[1].date, self.mondays[1])

    def test_an_occupied_place_is_skipped_and_counted(self):
        """
        Ряд длиной в год почти всегда во что-нибудь упрётся.

        «Не переехало ничего, потому что 16 сентября занято» — худший из
        возможных ответов, поэтому неделя пропускается и называется числом.
        """
        other = make_course(self.school, self.year, "10А")
        make_slot(self.user, other, self.mondays[1] + timedelta(days=2), 2)

        response = self.move()

        self.assertEqual(response.json(), {"moved": 2, "skipped": 1, "kept": 0})
        self.row[1].refresh_from_db()
        self.assertEqual(self.row[1].date, self.mondays[1])

    def test_a_holiday_week_leaves_its_hour_alone(self):
        holiday = self.mondays[2] + timedelta(days=2)
        DayException.objects.create(
            year=self.year,
            start_date=holiday,
            end_date=holiday,
            kind=calendar_services.KIND_HOLIDAY,
            title="Праздник",
        )

        response = self.move()

        self.assertEqual(response.json(), {"moved": 2, "skipped": 1, "kept": 0})
        self.row[2].refresh_from_db()
        self.assertEqual(self.row[2].date, self.mondays[2])

    def test_the_dragged_hour_is_judged_strictly(self):
        """
        По этому часу щёлкнули, и молча оставить его на месте нельзя.

        Хвост ряда пропускает занятое, а сам перетащенный час — нет: это
        то самое действие, которое человек попросил, и отказ на него он
        должен увидеть.
        """
        other = make_course(self.school, self.year, "10А")
        make_slot(self.user, other, self.wednesday, 2)

        response = self.move()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "slot_number_taken")

    def test_a_refusal_rolls_the_whole_row_back(self):
        other = make_course(self.school, self.year, "10А")
        make_slot(self.user, other, self.wednesday, 2)

        self.move()

        for slot, monday in zip(self.row, self.mondays):
            slot.refresh_from_db()
            self.assertEqual((slot.date, slot.lesson_number), (monday, 1))

    def test_a_target_in_another_week_is_refused(self):
        """
        Постоянная правка — это смена дня недели, а не сдвиг года на девять дней.

        Угадывать за человека, что он имел в виду, дороже названного отказа.
        """
        response = self.move(date=(self.wednesday + timedelta(days=7)).isoformat())

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "slot_move_series_week")

    def test_a_recorded_hour_moves_alone_or_not_at_all(self):
        self.slot.taught_by = self.colleague
        self.slot.save(update_fields=["taught_by"])

        response = self.move()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "slot_move_series_recorded")

    def test_an_extra_hour_has_no_row(self):
        """Дополнительный час разовый по определению — как и у повтора."""
        extra = make_slot(self.user, self.course, self.mondays[0], 4, is_extra=True)

        response = self.move(slot=extra)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "slot_move_series_one_off")

    def test_without_a_mode_the_move_stays_what_it_always_was(self):
        """Молчащий клиент обязан получить прежний разовый перенос."""
        response = self.client.post(
            reverse("slot-move", args=[self.slot.pk]),
            {"date": self.wednesday.isoformat(), "lesson_number": 2},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.slot.refresh_from_db()
        self.assertTrue(self.slot.is_cancelled)
        self.assertTrue(Slot.objects.get(pk=response.json()["id"]).is_extra)


class MoveKeepsTheOrderTests(SchoolTestMixin, APITestCase):
    """
    Порядок записей строгий и на календарной оси тоже.

    Запись напрямую очередь не ломает: записать можно только следующий
    незакрытый час. А перенос двигает не строку плана, а дату — и ломает её
    с другого конца. Занятие, уехавшее за спину соседней записи, оставляет
    ровно ту дыру, которую кнопка «так и было» сделать не даёт.

    Отвечает на оба способа сломать одна проверка (`Slot.broken_record`):
    незакрытый час позади последней записи и две записи, у которых даты
    идут вперёд, а строки плана назад. Второе без первого достижимо —
    отменённые часы дыр не образуют.
    """

    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.year = live_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        assign(self.user, self.course)
        self.rows = [
            make_node(self.user, self.course, f"Урок {number}")
            for number in range(1, 4)
        ]
        self.past = [
            make_slot(self.user, self.course, self.today - timedelta(days=days), 1)
            for days in (30, 20)
        ]
        for slot, row in zip(self.past, self.rows):
            slot.lesson = row
            slot.save(update_fields=["lesson"])

        self.ahead = make_slot(
            self.user, self.course, self.today + timedelta(days=10), 1
        )

    def move(self, slot, date, number=1):
        return self.client.post(
            reverse("slot-move", args=[slot.pk]),
            {"date": date.isoformat(), "lesson_number": number},
            format="json",
        )

    def test_a_hole_behind_the_last_record_is_refused(self):
        """Пустой час между двумя записанными — это и есть дыра."""
        response = self.move(self.ahead, self.today - timedelta(days=25))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "slot_move_breaks_order")

    def test_the_refusal_rolls_the_whole_move_back(self):
        self.move(self.ahead, self.today - timedelta(days=25))

        self.ahead.refresh_from_db()
        self.assertFalse(self.ahead.is_cancelled)
        self.assertEqual(Slot.objects.filter(course=self.course).count(), 3)

    def test_a_record_overtaking_another_is_refused(self):
        """Даты идут вперёд, а строки плана назад — записи обогнали друг друга."""
        response = self.move(self.past[0], self.today - timedelta(days=10))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "slot_move_breaks_order")

    def test_moving_ahead_of_everything_recorded_is_allowed(self):
        response = self.move(self.past[1], self.today - timedelta(days=5))

        self.assertEqual(response.status_code, 201, response.content)

    def test_the_future_moves_freely(self):
        response = self.move(self.ahead, self.today + timedelta(days=20))

        self.assertEqual(response.status_code, 201, response.content)


class RecordedSlotsAreNotSweptTests(LessonRecordTestCase):
    """
    Занятие с записью не удаляется ни поодиночке, ни массово.

    Массовых операций правило касалось всегда — `sweepable` пропускает всё,
    на чём есть запись, — а одиночное удаление было в нём единственной
    дырой: клетку сносили, запись уходила вместе с ней, строка плана
    возвращалась в общую очередь и получала другую дату.
    """

    def setUp(self):
        super().setUp()
        self.slot = make_slot(self.user, self.course, MONDAY, 1)
        self.slot.lesson = self.topic
        self.slot.save(update_fields=["lesson"])

    def test_deleting_a_recorded_lesson_is_refused(self):
        response = self.client.delete(reverse("slot-detail", args=[self.slot.pk]))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "slot_delete_recorded")
        self.assertTrue(Slot.objects.filter(pk=self.slot.pk).exists())

    def test_the_answer_names_the_lesson_and_the_day(self):
        body = self.client.delete(reverse("slot-detail", args=[self.slot.pk])).json()

        self.assertEqual(body["params"]["title"], self.topic.title)
        self.assertEqual(body["params"]["date"], str(MONDAY))

    def test_an_empty_lesson_is_still_deleted(self):
        empty = make_slot(self.user, self.course, MONDAY + timedelta(days=1), 1)

        response = self.client.delete(reverse("slot-detail", args=[empty.pk]))

        self.assertEqual(response.status_code, 204, response.content)

    def test_a_bulk_delete_walks_around_it(self):
        response = self.clear()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(Slot.objects.filter(pk=self.slot.pk).exists())

    def test_copying_with_replace_walks_around_it_too(self):
        """Замена — та же массовая операция: историю она не трогает."""
        source = MONDAY + timedelta(days=7)
        make_slot(self.user, self.course, source, 2)

        response = self.client.post(
            reverse("slot-copy"),
            {
                "course_id": self.course.pk,
                "source_start": source.isoformat(),
                "source_end": (source + timedelta(days=6)).isoformat(),
                "target_start": MONDAY.isoformat(),
                "target_end": (MONDAY + timedelta(days=6)).isoformat(),
                "mode": "replace",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["deleted"], 0)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.lesson_id, self.topic.pk)
