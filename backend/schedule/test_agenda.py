"""Занятость номера урока у одного учителя и сводное расписание."""

from datetime import date

from calendars import services as calendar_services
from calendars.models import DayException
from django.core.exceptions import ValidationError
from django.urls import reverse

from schools.testing import assign

from .models import Slot, Course
from .test_slots import MONDAY, SlotTestCase, days


class OccupiedSlotTests(SlotTestCase):
    def setUp(self):
        super().setUp()
        self.second = Course.objects.create(
            school=self.school, year=self.year, name="10А"
        )
        assign(self.user, self.second)

    def test_two_classes_cannot_share_a_lesson_number(self):
        self.make_slot(MONDAY, 3)

        response = self.post_slot("2026-09-07", 3, course=self.second)

        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual(body["code"], "slot_number_taken")
        self.assertEqual(body["params"]["class_name"], "9Б")
        self.assertEqual(body["params"]["number"], 3)
        self.assertEqual(Slot.objects.count(), 1)

    def test_another_number_on_the_same_day_is_free(self):
        self.make_slot(MONDAY, 3)

        response = self.post_slot("2026-09-07", 4, course=self.second)

        self.assertEqual(response.status_code, 201, response.content)

    def test_cancelled_lesson_frees_the_slot(self):
        busy = self.make_slot(MONDAY, 3)

        self.client.patch(
            reverse("slot-detail", args=[busy.pk]),
            {"is_cancelled": True, "reason": "Болезнь"},
            format="json",
        )
        response = self.post_slot("2026-09-07", 3, course=self.second)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Slot.objects.filter(is_cancelled=False).count(), 1)

    def test_cannot_restore_a_lesson_into_a_taken_slot(self):
        cancelled = self.make_slot(MONDAY, 3, is_cancelled=True, reason="Болезнь")
        self.make_slot(MONDAY, 3, course=self.second)

        response = self.client.patch(
            reverse("slot-detail", args=[cancelled.pk]),
            {"is_cancelled": False},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["params"]["class_name"], "10А")

    def test_editing_a_lesson_does_not_conflict_with_itself(self):
        slot = self.make_slot(MONDAY, 3)

        response = self.client.patch(
            reverse("slot-detail", args=[slot.pk]),
            {"reason": "просто правка"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)

    def test_another_teacher_is_not_affected(self):
        self.make_slot(MONDAY, 3, course=self.alien_class)

        response = self.post_slot("2026-09-07", 3)

        self.assertEqual(response.status_code, 201, response.content)

    def test_other_year_of_the_same_teacher_is_not_affected(self):
        """Проверка ограничена одним учебным годом."""
        other_year = self.year.__class__.objects.create(
            school=self.school,
            name="2027/2028",
            start_date=date(2027, 9, 1),
            end_date=date(2028, 5, 31),
        )
        other_class = Course.objects.create(
            school=self.school, year=other_year, name="9Б"
        )
        self.make_slot(date(2027, 9, 6), 3, course=other_class)

        response = self.post_slot("2027-09-06", 3, course=other_class)

        # тот же класс — ловит unique_together, а не занятость
        self.assertEqual(response.status_code, 400)
        self.assertIn("non_field_errors", response.json())

    def test_model_clean_catches_the_conflict_too(self):
        self.make_slot(MONDAY, 3)
        duplicate = Slot(
            year=self.year,
            course=self.second,
            date=MONDAY,
            lesson_number=3,
        )

        with self.assertRaises(ValidationError) as caught:
            duplicate.full_clean()

        self.assertIn("lesson_number", caught.exception.message_dict)

    def test_model_clean_allows_a_cancelled_duplicate(self):
        self.make_slot(MONDAY, 3)
        duplicate = Slot(
            year=self.year,
            course=self.second,
            date=MONDAY,
            lesson_number=3,
            is_cancelled=True,
            reason="Отменён заранее",
        )

        duplicate.full_clean()  # не должно бросить


class CopyConflictTests(SlotTestCase):
    def setUp(self):
        super().setUp()
        self.second = Course.objects.create(
            school=self.school, year=self.year, name="10А"
        )
        # источник: понедельник, уроки 1 и 2
        self.make_slot(MONDAY, 1)
        self.make_slot(MONDAY, 2)

    def copy(self, **overrides):
        payload = {
            "course_id": self.course.pk,
            "source_start": MONDAY.isoformat(),
            "source_end": (MONDAY + days(6)).isoformat(),
            "target_start": (MONDAY + days(7)).isoformat(),
            "target_end": (MONDAY + days(13)).isoformat(),
            "mode": "merge",
        }
        payload.update(overrides)
        return self.client.post(reverse("slot-copy"), payload, format="json")

    def test_conflicting_slots_are_skipped_and_reported(self):
        self.make_slot(MONDAY + days(7), 1, course=self.second)

        response = self.copy()

        data = response.json()
        self.assertEqual(data["created"], 1)
        self.assertEqual(data["skipped"], 1)
        self.assertEqual(len(data["conflicts"]), 1)
        self.assertEqual(
            data["conflicts"][0],
            {
                "date": (MONDAY + days(7)).isoformat(),
                "lesson_number": 1,
                "class_name": "10А",
                "message": "2026-09-14, lesson 1 is taken by 10А",
            },
        )
        self.assertEqual(self.slots_on(MONDAY + days(7)), [2])

    def test_cancelled_lesson_of_another_class_does_not_block(self):
        self.make_slot(
            MONDAY + days(7), 1, course=self.second, is_cancelled=True, reason="Болезнь"
        )

        response = self.copy()

        self.assertEqual(response.json()["created"], 2)
        self.assertEqual(response.json()["conflicts"], [])

    def test_replace_does_not_free_another_class_slot(self):
        self.make_slot(MONDAY + days(7), 1, course=self.second)
        self.make_slot(MONDAY + days(7), 2)

        response = self.copy(mode="replace")

        data = response.json()
        self.assertEqual(data["deleted"], 1)  # снесли только свой обычный урок
        self.assertEqual(data["created"], 1)
        self.assertEqual(len(data["conflicts"]), 1)
        self.assertTrue(
            Slot.objects.filter(course=self.second, lesson_number=1).exists()
        )


class CopyEverythingTests(SlotTestCase):
    """Копирование недели целиком, без указания класса."""

    def setUp(self):
        super().setUp()
        self.second = Course.objects.create(
            school=self.school, year=self.year, name="10А"
        )

        # неделя-источник: у 9Б понедельник 1-й и среда 2-й, у 10А понедельник 3-й
        self.make_slot(MONDAY, 1)
        self.make_slot(MONDAY + days(2), 2)
        self.make_slot(MONDAY, 3, course=self.second)
        # это копироваться не должно
        self.make_slot(MONDAY + days(1), 4, is_extra=True, reason="Замена")
        self.make_slot(
            MONDAY + days(1), 5, course=self.second, is_cancelled=True, reason="Болезнь"
        )

    def copy(self, **overrides):
        payload = {
            "source_start": MONDAY.isoformat(),
            "source_end": (MONDAY + days(6)).isoformat(),
            "target_start": (MONDAY + days(7)).isoformat(),
            "target_end": (MONDAY + days(13)).isoformat(),
            "mode": "merge",
        }
        payload.update(overrides)
        return self.client.post(reverse("slot-copy"), payload, format="json")

    def test_all_classes_are_copied_at_once(self):
        response = self.copy()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["created"], 3)
        self.assertEqual(self.slots_on(MONDAY + days(7)), [1])
        self.assertEqual(self.slots_on(MONDAY + days(9)), [2])
        self.assertEqual(self.slots_on(MONDAY + days(7), self.second), [3])

    def test_cancelled_and_extra_stay_home(self):
        self.copy()

        self.assertEqual(self.slots_on(MONDAY + days(8)), [])
        self.assertEqual(self.slots_on(MONDAY + days(8), self.second), [])

    def test_non_study_days_are_skipped_for_every_class(self):
        DayException.objects.create(
            year=self.year,
            start_date=MONDAY + days(7),
            end_date=MONDAY + days(7),
            kind=calendar_services.KIND_HOLIDAY,
            title="Праздник",
        )

        response = self.copy()

        # понедельник выпал: не поехали 1-й у 9Б и 3-й у 10А
        self.assertEqual(response.json()["created"], 1)
        self.assertEqual(response.json()["skipped"], 2)

    def test_occupied_number_of_another_class_is_reported(self):
        self.make_slot(MONDAY + days(7), 1, course=self.second)

        response = self.copy()

        data = response.json()
        self.assertEqual(data["created"], 2)
        self.assertEqual(len(data["conflicts"]), 1)
        self.assertEqual(data["conflicts"][0]["class_name"], "10А")

    def test_replace_clears_regular_slots_of_all_classes(self):
        self.make_slot(MONDAY + days(9), 8)
        self.make_slot(MONDAY + days(9), 9, course=self.second)
        kept = self.make_slot(
            MONDAY + days(9), 7, course=self.second, is_extra=True, reason="Кружок"
        )

        response = self.copy(mode="replace")

        self.assertEqual(response.json()["deleted"], 2)
        self.assertTrue(Slot.objects.filter(pk=kept.pk).exists())
        self.assertEqual(self.slots_on(MONDAY + days(9)), [2])

    def test_a_colleagues_course_is_untouched(self):
        """Копируется своё: расписание чужого курса ни при чём."""
        theirs = Course.objects.create(
            school=self.school, year=self.year, name="11Г"
        )
        assign(self.colleague, theirs)
        kept = Slot.objects.create(
            year=self.year, course=theirs, date=MONDAY, lesson_number=7
        )

        self.copy()

        self.assertEqual(Slot.objects.filter(course=theirs).count(), 1)
        self.assertEqual(Slot.objects.get(pk=kept.pk).lesson_number, 7)

    def test_classes_of_a_year_outside_the_target_are_skipped(self):
        other_year = self.year.__class__.objects.create(
            school=self.school,
            name="2027/2028",
            start_date=date(2027, 9, 1),
            end_date=date(2028, 5, 31),
        )
        future = Course.objects.create(
            school=self.school, year=other_year, name="11В"
        )
        self.make_slot(date(2027, 9, 6), 1, course=future)

        self.copy()

        self.assertEqual(Slot.objects.filter(course=future).count(), 1)


class AgendaTests(SlotTestCase):
    def setUp(self):
        super().setUp()
        self.second = Course.objects.create(
            school=self.school, year=self.year, name="10А"
        )
        DayException.objects.create(
            year=self.year,
            start_date=MONDAY + days(7),
            end_date=MONDAY + days(11),
            kind=calendar_services.KIND_VACATION,
            title="Осенние каникулы",
        )

        self.make_slot(MONDAY, 1)
        self.make_slot(MONDAY, 2, course=self.second)
        self.make_slot(MONDAY + days(1), 3, is_cancelled=True, reason="Болезнь")
        self.make_slot(MONDAY + days(2), 4, course=self.second, is_extra=True, reason="Кружок")

    def agenda(self, start=None, end=None):
        return self.client.get(
            reverse("slot-agenda"),
            {
                "start": (start or MONDAY).isoformat(),
                "end": (end or MONDAY + days(13)).isoformat(),
            },
        )

    def test_lessons_of_all_classes_are_grouped_by_date(self):
        data = self.agenda().json()

        monday = data["lessons"][MONDAY.isoformat()]
        self.assertEqual(
            [(item["lesson_number"], item["course_name"]) for item in monday],
            [(1, "9Б"), (2, "10А")],
        )
        self.assertEqual(len(data["lessons"]), 3)

    def test_lesson_carries_flags_and_reason(self):
        data = self.agenda().json()

        cancelled = data["lessons"][(MONDAY + days(1)).isoformat()][0]
        self.assertTrue(cancelled["is_cancelled"])
        self.assertEqual(cancelled["reason"], "Болезнь")

        extra = data["lessons"][(MONDAY + days(2)).isoformat()][0]
        self.assertTrue(extra["is_extra"])
        self.assertEqual(extra["course_id"], self.second.pk)

    def test_cancelled_and_replacement_share_one_slot(self):
        """
        Отменённый урок и поставленный вместо него виден оба: сводному
        расписанию нужно нарисовать в одном окне и отмену, и замену.
        """
        cancelled = self.make_slot(
            MONDAY + days(3), 5, is_cancelled=True, reason="Болезнь"
        )
        replacement = self.make_slot(MONDAY + days(3), 5, course=self.second)

        lessons = self.agenda().json()["lessons"][(MONDAY + days(3)).isoformat()]

        self.assertEqual(
            {(item["id"], item["is_cancelled"]) for item in lessons},
            {(cancelled.pk, True), (replacement.pk, False)},
        )
        self.assertEqual({item["lesson_number"] for item in lessons}, {5})

    def test_days_carry_the_calendar_markup(self):
        data = self.agenda().json()

        self.assertTrue(data["days"][MONDAY.isoformat()]["is_study"])
        self.assertEqual(data["days"][MONDAY.isoformat()]["status"], "study")

        vacation = data["days"][(MONDAY + days(7)).isoformat()]
        self.assertFalse(vacation["is_study"])
        self.assertEqual(vacation["status"], calendar_services.STATUS_VACATION)
        self.assertEqual(vacation["title"], "Осенние каникулы")

        weekend = data["days"][(MONDAY + days(5)).isoformat()]
        self.assertEqual(weekend["status"], calendar_services.STATUS_WEEKEND)

    def test_every_date_of_the_period_is_present(self):
        data = self.agenda().json()

        self.assertEqual(len(data["days"]), 14)

    def test_dates_outside_any_year_are_marked(self):
        data = self.agenda(start=date(2026, 8, 20), end=date(2026, 9, 2)).json()

        self.assertEqual(data["days"]["2026-08-20"]["status"], "outside")
        self.assertFalse(data["days"]["2026-08-20"]["is_study"])
        self.assertTrue(data["days"]["2026-09-01"]["is_study"])

    def test_lessons_of_a_course_i_do_not_lead_are_invisible(self):
        """Своё расписание — это уроки своих курсов, и ничьи больше."""
        theirs = Course.objects.create(
            school=self.school, year=self.year, name="11Д"
        )
        assign(self.colleague, theirs)
        Slot.objects.create(
            year=self.year, course=theirs, date=MONDAY, lesson_number=5
        )

        data = self.agenda().json()

        numbers = [item["lesson_number"] for item in data["lessons"][MONDAY.isoformat()]]
        self.assertEqual(numbers, [1, 2])

    def test_period_is_required(self):
        response = self.client.get(reverse("slot-agenda"))

        self.assertEqual(response.status_code, 400)

    def test_reversed_period_is_rejected(self):
        response = self.agenda(start=MONDAY + days(5), end=MONDAY)

        self.assertEqual(response.status_code, 400)

    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.agenda().status_code, 401)
