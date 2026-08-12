from datetime import date, timedelta
from urllib.parse import urlencode

from calendars import services as calendar_services
from calendars.models import DayException, SchoolYear
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import LessonSlot, SchoolClass

User = get_user_model()

YEAR_START = date(2026, 9, 1)
YEAR_END = date(2027, 5, 31)
MONDAY = date(2026, 9, 7)  # первый полный понедельник года


def days(count):
    return timedelta(days=count)


class SlotTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="teacher@example.com")
        self.other = User.objects.create_user(email="other@example.com")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}"
        )

        self.year = SchoolYear.objects.create(
            owner=self.user, name="2026/2027", start_date=YEAR_START, end_date=YEAR_END
        )
        self.school_class = SchoolClass.objects.create(
            owner=self.user, year=self.year, name="9Б"
        )

        self.alien_year = SchoolYear.objects.create(
            owner=self.other, name="2026/2027", start_date=YEAR_START, end_date=YEAR_END
        )
        self.alien_class = SchoolClass.objects.create(
            owner=self.other, year=self.alien_year, name="9А"
        )

    def make_slot(self, slot_date, number, school_class=None, **flags):
        school_class = school_class or self.school_class
        return LessonSlot.objects.create(
            year=school_class.year,
            school_class=school_class,
            date=slot_date,
            lesson_number=number,
            **flags,
        )

    def post_slot(self, slot_date, number, school_class=None, **extra):
        return self.client.post(
            reverse("lessonslot-list"),
            {
                "school_class": (school_class or self.school_class).pk,
                "date": slot_date,
                "lesson_number": number,
                **extra,
            },
            format="json",
        )

    def slots_on(self, slot_date, school_class=None):
        return sorted(
            LessonSlot.objects.filter(
                school_class=school_class or self.school_class, date=slot_date
            ).values_list("lesson_number", flat=True)
        )


class SlotCrudTests(SlotTestCase):
    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.client.get(reverse("lessonslot-list")).status_code, 401)

    def test_create_fills_year_from_the_class(self):
        response = self.post_slot("2026-09-07", 1)

        self.assertEqual(response.status_code, 201, response.content)
        slot = LessonSlot.objects.get()
        self.assertEqual(slot.year, self.year)
        self.assertFalse(slot.is_cancelled)
        self.assertFalse(slot.is_extra)
        self.assertIsNone(response.json()["warning"])

    def test_slot_on_a_non_study_day_is_allowed_but_warns(self):
        DayException.objects.create(
            year=self.year,
            start_date=date(2026, 10, 26),
            end_date=date(2026, 11, 3),
            kind=calendar_services.KIND_VACATION,
            title="Осенние каникулы",
        )

        response = self.post_slot("2026-10-28", 1)

        self.assertEqual(response.status_code, 201, response.content)
        warning = response.json()["warning"]
        self.assertEqual(warning["code"], "slot_not_study_day")
        self.assertEqual(warning["params"]["status"], "vacation")
        self.assertEqual(warning["params"]["title"], "Осенние каникулы")

    def test_weekend_slot_warns_too(self):
        response = self.post_slot("2026-09-12", 1)  # суббота

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            response.json()["warning"]["params"]["status"], "weekend"
        )

    def test_date_outside_the_year_is_rejected(self):
        response = self.post_slot("2026-08-31", 1)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "slot_outside_year")

    def test_year_must_match_the_class(self):
        other_year = SchoolYear.objects.create(
            owner=self.user,
            name="2027/2028",
            start_date=date(2027, 9, 1),
            end_date=date(2028, 5, 31),
        )

        response = self.post_slot("2026-09-07", 1, year=other_year.pk)

        # a year without classes is not even in the field queryset,
        # so this is a plain field error and never reaches validate()
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("year", response.json())

    def test_cannot_create_a_slot_for_another_users_class(self):
        response = self.post_slot("2026-09-07", 1, school_class=self.alien_class)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(LessonSlot.objects.exists())

    def test_duplicate_number_in_the_same_day_is_rejected(self):
        self.post_slot("2026-09-07", 1)

        response = self.post_slot("2026-09-07", 1)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["non_field_errors"],
            ["This class already has a lesson with this number on that day."],
        )
        self.assertEqual(LessonSlot.objects.count(), 1)

    def test_same_number_on_another_day_is_fine(self):
        self.post_slot("2026-09-07", 1)

        self.assertEqual(self.post_slot("2026-09-08", 1).status_code, 201)

    def test_same_number_for_another_class_on_another_day_is_fine(self):
        """Один номер у двух классов в один день запрещён — см. test_agenda.py."""
        second = SchoolClass.objects.create(owner=self.user, year=self.year, name="9В")
        self.post_slot("2026-09-07", 1)

        response = self.post_slot("2026-09-08", 1, school_class=second)

        self.assertEqual(response.status_code, 201, response.content)

    def test_lesson_number_out_of_range_is_rejected(self):
        self.assertEqual(self.post_slot("2026-09-07", 0).status_code, 400)
        self.assertEqual(self.post_slot("2026-09-07", 11).status_code, 400)

    def test_cancel_and_restore(self):
        slot = self.make_slot(MONDAY, 1)
        url = reverse("lessonslot-detail", args=[slot.pk])

        cancel = self.client.patch(
            url, {"is_cancelled": True, "reason": "Болезнь"}, format="json"
        )
        self.assertEqual(cancel.status_code, 200, cancel.content)
        slot.refresh_from_db()
        self.assertTrue(slot.is_cancelled)
        self.assertEqual(slot.reason, "Болезнь")

        restore = self.client.patch(
            url, {"is_cancelled": False, "reason": ""}, format="json"
        )
        self.assertEqual(restore.status_code, 200, restore.content)
        slot.refresh_from_db()
        self.assertFalse(slot.is_cancelled)
        self.assertEqual(slot.reason, "")

    def test_patch_keeps_its_own_number(self):
        """Правка урока не должна ловить его же на уникальности."""
        slot = self.make_slot(MONDAY, 1)

        response = self.client.patch(
            reverse("lessonslot-detail", args=[slot.pk]),
            {"is_extra": True, "reason": "Замена"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)

    def test_delete(self):
        slot = self.make_slot(MONDAY, 1)

        response = self.client.delete(reverse("lessonslot-detail", args=[slot.pk]))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(LessonSlot.objects.exists())

    def test_deleting_the_class_removes_its_slots(self):
        self.make_slot(MONDAY, 1)

        self.client.delete(reverse("schoolclass-detail", args=[self.school_class.pk]))

        self.assertFalse(LessonSlot.objects.exists())


class SlotIsolationTests(SlotTestCase):
    def setUp(self):
        super().setUp()
        self.alien_slot = self.make_slot(MONDAY, 1, school_class=self.alien_class)
        self.mine = self.make_slot(MONDAY, 2)

    def test_list_shows_only_own_slots(self):
        response = self.client.get(reverse("lessonslot-list"))

        self.assertEqual([item["id"] for item in response.json()], [self.mine.pk])

    def test_alien_slot_is_not_found(self):
        url = reverse("lessonslot-detail", args=[self.alien_slot.pk])

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.patch(url, {"is_cancelled": True}, format="json").status_code, 404
        )
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertTrue(LessonSlot.objects.filter(pk=self.alien_slot.pk).exists())

    def test_filter_by_class(self):
        second = SchoolClass.objects.create(owner=self.user, year=self.year, name="9В")
        expected = self.make_slot(MONDAY, 3, school_class=second)

        response = self.client.get(reverse("lessonslot-list"), {"class": second.pk})

        self.assertEqual([item["id"] for item in response.json()], [expected.pk])

    def test_filter_by_period(self):
        later = self.make_slot(MONDAY + days(10), 1)

        response = self.client.get(
            reverse("lessonslot-list"),
            {"start": (MONDAY + days(5)).isoformat(), "end": (MONDAY + days(20)).isoformat()},
        )

        self.assertEqual([item["id"] for item in response.json()], [later.pk])

    def test_garbage_filters_return_nothing(self):
        self.assertEqual(
            self.client.get(reverse("lessonslot-list"), {"class": "abc"}).json(), []
        )
        self.assertEqual(
            self.client.get(reverse("lessonslot-list"), {"start": "вчера"}).json(), []
        )


class CopyTests(SlotTestCase):
    def setUp(self):
        super().setUp()
        # неделя-источник: понедельник 1 и 2 уроки, среда 3, пятница 4
        self.make_slot(MONDAY, 1)
        self.make_slot(MONDAY, 2)
        self.make_slot(MONDAY + days(2), 3)
        self.make_slot(MONDAY + days(4), 4)

    def copy(self, **overrides):
        payload = {
            "class_id": self.school_class.pk,
            "source_start": MONDAY.isoformat(),
            "source_end": (MONDAY + days(6)).isoformat(),
            "target_start": (MONDAY + days(7)).isoformat(),
            "target_end": (MONDAY + days(20)).isoformat(),
            "mode": "merge",
        }
        payload.update(overrides)
        return self.client.post(reverse("lessonslot-copy"), payload, format="json")

    def test_week_is_copied_onto_matching_weekdays(self):
        response = self.copy()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json(),
            {"created": 8, "skipped": 0, "deleted": 0, "conflicts": []},
        )
        self.assertEqual(self.slots_on(MONDAY + days(7)), [1, 2])
        self.assertEqual(self.slots_on(MONDAY + days(9)), [3])
        self.assertEqual(self.slots_on(MONDAY + days(14)), [1, 2])
        self.assertEqual(self.slots_on(MONDAY + days(18)), [4])
        # в выходные ничего не приехало
        self.assertEqual(self.slots_on(MONDAY + days(12)), [])

    def test_copy_skips_vacation_days(self):
        DayException.objects.create(
            year=self.year,
            start_date=MONDAY + days(7),
            end_date=MONDAY + days(13),
            kind=calendar_services.KIND_VACATION,
            title="Каникулы",
        )

        response = self.copy()

        # первая неделя цели выпала целиком, поехала только вторая
        self.assertEqual(
            response.json(),
            {"created": 4, "skipped": 4, "deleted": 0, "conflicts": []},
        )
        self.assertEqual(self.slots_on(MONDAY + days(7)), [])
        self.assertEqual(self.slots_on(MONDAY + days(14)), [1, 2])

    def test_copy_skips_a_single_holiday(self):
        DayException.objects.create(
            year=self.year,
            start_date=MONDAY + days(9),
            end_date=MONDAY + days(9),
            kind=calendar_services.KIND_HOLIDAY,
            title="Праздник",
        )

        response = self.copy()

        self.assertEqual(response.json()["skipped"], 1)
        self.assertEqual(self.slots_on(MONDAY + days(9)), [])

    def test_transferred_workday_receives_lessons(self):
        """Перенос делает субботу учебной — уроки на неё поставить можно."""
        saturday = MONDAY + days(5)
        self.make_slot(saturday, 5)
        DayException.objects.create(
            year=self.year,
            start_date=MONDAY + days(12),
            end_date=MONDAY + days(12),
            kind=calendar_services.KIND_WORKDAY,
            title="Отработка",
        )

        self.copy()

        self.assertEqual(self.slots_on(MONDAY + days(12)), [5])

    def test_two_week_source_keeps_the_cycle(self):
        # вторая неделя источника: понедельник только 7-й урок
        self.make_slot(MONDAY + days(7), 7)

        response = self.copy(
            source_end=(MONDAY + days(13)).isoformat(),
            target_start=(MONDAY + days(14)).isoformat(),
            target_end=(MONDAY + days(41)).isoformat(),
        )

        self.assertEqual(response.status_code, 200, response.content)
        # чётные недели повторяют первую, нечётные — вторую
        self.assertEqual(self.slots_on(MONDAY + days(14)), [1, 2])
        self.assertEqual(self.slots_on(MONDAY + days(21)), [7])
        self.assertEqual(self.slots_on(MONDAY + days(28)), [1, 2])
        self.assertEqual(self.slots_on(MONDAY + days(35)), [7])

    def test_merge_keeps_existing_slots_and_skips_conflicts(self):
        self.make_slot(MONDAY + days(7), 1, is_extra=True, reason="Замена")

        response = self.copy()

        self.assertEqual(response.json()["skipped"], 1)
        self.assertEqual(self.slots_on(MONDAY + days(7)), [1, 2])
        kept = LessonSlot.objects.get(date=MONDAY + days(7), lesson_number=1)
        self.assertTrue(kept.is_extra)

    def test_replace_wipes_regular_slots_first(self):
        stale = self.make_slot(MONDAY + days(7), 9)

        response = self.copy(mode="replace")

        self.assertEqual(response.json()["deleted"], 1)
        self.assertFalse(LessonSlot.objects.filter(pk=stale.pk).exists())
        self.assertEqual(self.slots_on(MONDAY + days(7)), [1, 2])

    def test_replace_keeps_extra_and_cancelled(self):
        extra = self.make_slot(MONDAY + days(8), 6, is_extra=True, reason="Кружок")
        cancelled = self.make_slot(MONDAY + days(7), 1, is_cancelled=True, reason="Актировка")

        response = self.copy(mode="replace")

        self.assertTrue(LessonSlot.objects.filter(pk=extra.pk).exists())
        self.assertTrue(LessonSlot.objects.filter(pk=cancelled.pk).exists())
        # первый урок понедельника занят отменённым — его пропустили
        self.assertEqual(response.json()["skipped"], 1)
        self.assertEqual(self.slots_on(MONDAY + days(7)), [1, 2])

    def test_extra_and_cancelled_are_not_copied_from_the_source(self):
        self.make_slot(MONDAY + days(1), 1, is_extra=True, reason="Замена")
        self.make_slot(MONDAY + days(1), 2, is_cancelled=True, reason="Болезнь")

        self.copy()

        self.assertEqual(self.slots_on(MONDAY + days(8)), [])

    def test_copy_into_another_users_class_is_rejected(self):
        response = self.copy(class_id=self.alien_class.pk)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(LessonSlot.objects.filter(school_class=self.alien_class).count(), 0)

    def test_reversed_period_is_rejected(self):
        response = self.copy(target_end=(MONDAY + days(1)).isoformat())

        self.assertEqual(response.status_code, 400, response.content)

    def test_copy_outside_the_year_creates_nothing(self):
        response = self.copy(
            target_start="2027-06-01", target_end="2027-06-14"
        )

        self.assertEqual(response.json()["created"], 0)


class BulkDeleteTests(SlotTestCase):
    def setUp(self):
        super().setUp()
        self.regular = self.make_slot(MONDAY, 1)
        self.extra = self.make_slot(MONDAY, 2, is_extra=True, reason="Замена")
        self.cancelled = self.make_slot(MONDAY + days(1), 1, is_cancelled=True, reason="Болезнь")
        self.outside = self.make_slot(MONDAY + days(30), 1)

    def bulk(self, **params):
        query = {
            "class": self.school_class.pk,
            "start": MONDAY.isoformat(),
            "end": (MONDAY + days(6)).isoformat(),
            **params,
        }
        # параметры именно в строке запроса: тело у DELETE отдавать не принято
        return self.client.delete(f"{reverse('lessonslot-bulk')}?{urlencode(query)}")

    def test_deletes_everything_in_the_period(self):
        response = self.bulk()

        self.assertEqual(response.json(), {"deleted": 3})
        self.assertEqual(list(LessonSlot.objects.all()), [self.outside])

    def test_only_regular_keeps_extra_and_cancelled(self):
        response = self.bulk(only_regular="true")

        self.assertEqual(response.json(), {"deleted": 1})
        self.assertFalse(LessonSlot.objects.filter(pk=self.regular.pk).exists())
        self.assertTrue(LessonSlot.objects.filter(pk=self.extra.pk).exists())
        self.assertTrue(LessonSlot.objects.filter(pk=self.cancelled.pk).exists())

    def test_another_users_class_is_rejected(self):
        alien_slot = self.make_slot(MONDAY, 1, school_class=self.alien_class)

        response = self.bulk(**{"class": self.alien_class.pk})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertTrue(LessonSlot.objects.filter(pk=alien_slot.pk).exists())

    def test_missing_parameters_are_rejected(self):
        response = self.client.delete(
            f"{reverse('lessonslot-bulk')}?class={self.school_class.pk}"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("start", response.json())


class StatsTests(SlotTestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        # для past/remaining нужен год, внутри которого лежит сегодняшний день
        self.current_year = SchoolYear.objects.create(
            owner=self.user,
            name="текущий",
            start_date=self.today - days(60),
            end_date=self.today + days(60),
        )
        self.current_class = SchoolClass.objects.create(
            owner=self.user, year=self.current_year, name="7А"
        )

        self.make_slot(self.today - days(7), 1, school_class=self.current_class)
        self.make_slot(self.today - days(1), 1, school_class=self.current_class)
        self.make_slot(self.today, 1, school_class=self.current_class)
        self.make_slot(self.today + days(3), 1, school_class=self.current_class)
        self.make_slot(
            self.today + days(4), 2, school_class=self.current_class, is_extra=True, reason="Кружок"
        )
        self.make_slot(
            self.today - days(2), 3, school_class=self.current_class,
            is_cancelled=True, reason="Болезнь",
        )
        self.make_slot(
            self.today - days(3), 4, school_class=self.current_class,
            is_cancelled=True, reason="Болезнь",
        )
        self.make_slot(
            self.today + days(5), 5, school_class=self.current_class,
            is_cancelled=True, reason="Актировка",
        )

    def stats(self, school_class=None):
        return self.client.get(
            reverse("lessonslot-stats"),
            {"class": (school_class or self.current_class).pk},
        ).json()

    def test_total_is_split_into_past_and_remaining(self):
        data = self.stats()

        self.assertEqual(data["total"], 5)
        self.assertEqual(data["past"], 2)
        self.assertEqual(data["remaining"], 3)
        self.assertEqual(data["total"], data["past"] + data["remaining"])

    def test_today_counts_as_remaining(self):
        data = self.stats()

        self.assertEqual(data["remaining"], 3)  # сегодня, +3 и +4

    def test_cancelled_are_out_of_total(self):
        data = self.stats()

        self.assertEqual(data["cancelled"], 3)
        self.assertEqual(
            data["cancelled_by_reason"], {"Болезнь": 2, "Актировка": 1}
        )

    def test_extra_counts_only_live_lessons(self):
        data = self.stats()

        self.assertEqual(data["extra"], 1)

    def test_stats_are_scoped_to_the_class(self):
        self.make_slot(MONDAY, 1)

        self.assertEqual(self.stats()["total"], 5)
        self.assertEqual(self.stats(self.school_class)["total"], 1)

    def test_stats_of_another_users_class_are_empty(self):
        self.make_slot(MONDAY, 1, school_class=self.alien_class)

        data = self.stats(self.alien_class)

        self.assertEqual(data["total"], 0)
        self.assertEqual(data["cancelled"], 0)

    def test_stats_without_a_class_cover_all_own_slots(self):
        self.make_slot(MONDAY, 1)

        data = self.client.get(reverse("lessonslot-stats")).json()

        self.assertEqual(data["total"], 6)
