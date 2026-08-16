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
