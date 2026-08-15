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
from rest_framework.test import APITestCase
from schools.testing import (
    MONDAY,
    SchoolTestMixin,
    assign,
    make_course,
    make_node,
    make_slot,
    make_work,
    make_year,
)

from .models import Lesson


class LessonRecordTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        assign(self.user, self.course)
        self.topic = make_node(self.user, self.course, "Синус суммы")

    def clear(self, only_regular=True):
        return self.client.delete(
            reverse("lesson-bulk")
            + f"?course={self.course.pk}&start={MONDAY}&end={MONDAY + timedelta(days=6)}"
            + f"&only_regular={only_regular}"
        )


class RecordTests(LessonRecordTestCase):
    def test_the_lesson_remembers_what_was_covered_and_who_taught_it(self):
        lesson = make_slot(self.user, self.course)

        response = self.client.patch(
            reverse("lesson-detail", args=[lesson.pk]),
            {"covered": self.topic.pk, "taught_by": self.colleague.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["covered_title"], "Синус суммы")
        lesson.refresh_from_db()
        self.assertEqual(lesson.covered, self.topic)
        self.assertEqual(lesson.taught_by, self.colleague)

    def test_a_plan_lesson_of_another_course_cannot_be_named(self):
        other = make_course(self.school, self.year, "10А")
        theirs = make_node(self.colleague, other, "Чужая тема")
        lesson = make_slot(self.user, self.course)

        response = self.client.patch(
            reverse("lesson-detail", args=[lesson.pk]),
            {"covered": theirs.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)

    def test_deleting_the_plan_row_leaves_the_lesson_and_forgets_the_link(self):
        """Строку плана удалили, а урок был: связь уходит, факт остаётся."""
        lesson = make_slot(self.user, self.course)
        lesson.covered = self.topic
        lesson.save(update_fields=["covered"])

        self.topic.delete()

        lesson.refresh_from_db()
        self.assertIsNone(lesson.covered_id)

    def test_a_work_hangs_on_the_lesson_it_was_set_at(self):
        lesson = make_slot(self.user, self.course)
        work = make_work(self.user, self.course)

        response = self.client.patch(
            reverse("work-detail", args=[work.pk]),
            {"lesson": lesson.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(list(lesson.works.all()), [work])

    def test_deleting_the_lesson_keeps_the_work(self):
        lesson = make_slot(self.user, self.course)
        work = make_work(self.user, self.course, lesson=lesson)

        self.client.delete(reverse("lesson-detail", args=[lesson.pk]))

        work.refresh_from_db()
        self.assertIsNone(work.lesson_id)


class SweepTests(LessonRecordTestCase):
    """Что переживает массовую чистку, а что нет."""

    def test_an_empty_lesson_is_swept(self):
        make_slot(self.user, self.course)

        self.assertEqual(self.clear().json()["deleted"], 1)

    def test_a_lesson_that_remembers_the_topic_survives(self):
        lesson = make_slot(self.user, self.course)
        lesson.covered = self.topic
        lesson.save(update_fields=["covered"])

        self.assertEqual(self.clear().json()["deleted"], 0)
        self.assertTrue(Lesson.objects.filter(pk=lesson.pk).exists())

    def test_a_lesson_with_a_substitute_survives(self):
        lesson = make_slot(self.user, self.course)
        lesson.taught_by = self.colleague
        lesson.save(update_fields=["taught_by"])

        self.assertEqual(self.clear().json()["deleted"], 0)

    def test_a_lesson_with_a_work_survives(self):
        lesson = make_slot(self.user, self.course)
        make_work(self.user, self.course, lesson=lesson)

        self.assertEqual(self.clear().json()["deleted"], 0)

    def test_without_only_regular_everything_goes(self):
        """Явная просьба «снести всё» — это уже не массовая уборка."""
        lesson = make_slot(self.user, self.course)
        lesson.covered = self.topic
        lesson.save(update_fields=["covered"])

        self.assertEqual(self.clear(only_regular=False).json()["deleted"], 1)

    def test_replace_does_not_overwrite_a_lesson_with_a_record(self):
        """
        Раскатать неделю на год — самая массовая из операций, и именно её
        боятся: она проходит по всему году и стёрла бы историю разом.
        """
        source = make_slot(self.user, self.course, MONDAY, 1)
        kept = make_slot(self.user, self.course, MONDAY + timedelta(days=7), 4)
        kept.covered = self.topic
        kept.save(update_fields=["covered"])

        self.client.post(
            reverse("lesson-copy"),
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

        self.assertTrue(Lesson.objects.filter(pk=kept.pk).exists())
        self.assertTrue(Lesson.objects.filter(pk=source.pk).exists())
