from datetime import date, timedelta
from urllib.parse import urlencode

from calendars import services as calendar_services
from calendars.models import DayException, SchoolYear
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from schools.testing import (
    assign,
    MONDAY,
    YEAR_END,
    YEAR_START,
    SchoolTestMixin,
    make_course,
    make_node,
    make_slot,
    make_year,
)

from .models import Course, Slot


def days(count):
    return timedelta(days=count)


class SlotTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()

        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        assign(self.user, self.course)

        self.alien_year = make_year(self.alien_school)
        self.alien_class = make_course(self.alien_school, self.alien_year, "9А")

    def make_slot(self, slot_date, number, course=None, teacher=None, **flags):
        """
        Урок курса. Учителя у слота нет — есть назначение, и фикстура его
        ставит: урок в курсе, который никому не поручен, API не даёт завести.
        """
        course = course or self.course
        assign(teacher or self.user, course)
        return Slot.objects.create(
            year=course.year,
            course=course,
            date=slot_date,
            lesson_number=number,
            **flags,
        )

    def post_slot(self, slot_date, number, course=None, **extra):
        return self.client.post(
            reverse("slot-list"),
            {
                "course": (course or self.course).pk,
                "date": slot_date,
                "lesson_number": number,
                **extra,
            },
            format="json",
        )

    def slots_on(self, slot_date, course=None):
        return sorted(
            Slot.objects.filter(
                course=course or self.course, date=slot_date
            ).values_list("lesson_number", flat=True)
        )


class SlotCrudTests(SlotTestCase):
    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.client.get(reverse("slot-list")).status_code, 401)

    def test_create_fills_year_from_the_class(self):
        response = self.post_slot("2026-09-07", 1)

        self.assertEqual(response.status_code, 201, response.content)
        slot = Slot.objects.get()
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
            school=self.school,
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
        response = self.post_slot("2026-09-07", 1, course=self.alien_class)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(Slot.objects.exists())

    def test_duplicate_number_in_the_same_day_is_rejected(self):
        self.post_slot("2026-09-07", 1)

        response = self.post_slot("2026-09-07", 1)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["non_field_errors"],
            ["This course already has a lesson with that number that day."],
        )
        self.assertEqual(Slot.objects.count(), 1)

    def test_same_number_on_another_day_is_fine(self):
        self.post_slot("2026-09-07", 1)

        self.assertEqual(self.post_slot("2026-09-08", 1).status_code, 201)

    def test_same_number_for_another_class_on_another_day_is_fine(self):
        """Один номер у двух классов в один день запрещён — см. test_agenda.py."""
        second = Course.objects.create(
            school=self.school, year=self.year, name="9В")
        assign(self.user, second)
        self.post_slot("2026-09-07", 1)

        response = self.post_slot("2026-09-08", 1, course=second)

        self.assertEqual(response.status_code, 201, response.content)

    def test_lesson_number_out_of_range_is_rejected(self):
        self.assertEqual(self.post_slot("2026-09-07", 0).status_code, 400)
        self.assertEqual(self.post_slot("2026-09-07", 11).status_code, 400)

    def test_cancel_and_restore(self):
        slot = self.make_slot(MONDAY, 1)
        url = reverse("slot-detail", args=[slot.pk])

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
            reverse("slot-detail", args=[slot.pk]),
            {"is_extra": True, "reason": "Замена"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)

    def test_delete(self):
        slot = self.make_slot(MONDAY, 1)

        response = self.client.delete(reverse("slot-detail", args=[slot.pk]))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Slot.objects.exists())

    def test_a_course_in_use_refuses_to_be_deleted(self):
        """
        PROTECT, not CASCADE: an administrator must not wipe somebody's year.

        The answer names what is in the way, so the person knows whom to ask.
        """
        self.make_slot(MONDAY, 1)
        self.sign_in(self.admin)

        response = self.client.delete(reverse("course-detail", args=[self.course.pk]))

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "course_in_use")
        self.assertEqual(response.json()["params"]["slots"], 1)
        self.assertTrue(Slot.objects.exists())

    def test_an_unused_course_deletes_cleanly(self):
        self.sign_in(self.admin)

        response = self.client.delete(reverse("course-detail", args=[self.course.pk]))

        self.assertEqual(response.status_code, 204, response.content)


class SlotIsolationTests(SlotTestCase):
    """
    Расписание принадлежит курсу и **читается всей школой**.

    Поэтому граница здесь не «видно / не видно», а «правлю / не правлю»:
    урок чужого курса коллега читает (по расписанию школы живут все), но
    не трогает. Прячется расписание только от чужой школы.
    """

    def setUp(self):
        super().setUp()
        theirs = make_course(self.school, self.year, "10А")
        assign(self.colleague, theirs)
        self.alien_slot = Slot.objects.create(
            year=self.year, course=theirs, date=MONDAY, lesson_number=1
        )
        self.mine = self.make_slot(MONDAY, 2)

    def test_list_shows_only_slots_of_my_courses(self):
        response = self.client.get(reverse("slot-list"))

        self.assertEqual([item["id"] for item in response.json()], [self.mine.pk])

    def test_a_slot_of_another_course_is_readable_but_not_writable(self):
        url = reverse("slot-detail", args=[self.alien_slot.pk])

        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(
            self.client.patch(url, {"is_cancelled": True}, format="json").status_code, 403
        )
        self.assertEqual(self.client.delete(url).status_code, 403)
        self.assertTrue(Slot.objects.filter(pk=self.alien_slot.pk).exists())

    def test_a_slot_of_another_school_is_not_found(self):
        alien_course = make_course(self.alien_school, self.alien_year, "9В")
        alien = Slot.objects.create(
            year=self.alien_year, course=alien_course, date=MONDAY, lesson_number=1
        )
        url = reverse("slot-detail", args=[alien.pk])

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_filter_by_class(self):
        second = Course.objects.create(
            school=self.school, year=self.year, name="9В")
        expected = self.make_slot(MONDAY, 3, course=second)

        response = self.client.get(reverse("slot-list"), {"course": second.pk})

        self.assertEqual([item["id"] for item in response.json()], [expected.pk])

    def test_filter_by_period(self):
        later = self.make_slot(MONDAY + days(10), 1)

        response = self.client.get(
            reverse("slot-list"),
            {"start": (MONDAY + days(5)).isoformat(), "end": (MONDAY + days(20)).isoformat()},
        )

        self.assertEqual([item["id"] for item in response.json()], [later.pk])

    def test_garbage_filters_return_nothing(self):
        self.assertEqual(
            self.client.get(reverse("slot-list"), {"course": "abc"}).json(), []
        )
        self.assertEqual(
            self.client.get(reverse("slot-list"), {"start": "вчера"}).json(), []
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
            "course_id": self.course.pk,
            "source_start": MONDAY.isoformat(),
            "source_end": (MONDAY + days(6)).isoformat(),
            "target_start": (MONDAY + days(7)).isoformat(),
            "target_end": (MONDAY + days(20)).isoformat(),
            "mode": "merge",
        }
        payload.update(overrides)
        return self.client.post(reverse("slot-copy"), payload, format="json")

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
        kept = Slot.objects.get(date=MONDAY + days(7), lesson_number=1)
        self.assertTrue(kept.is_extra)

    def test_replace_wipes_regular_slots_first(self):
        stale = self.make_slot(MONDAY + days(7), 9)

        response = self.copy(mode="replace")

        self.assertEqual(response.json()["deleted"], 1)
        self.assertFalse(Slot.objects.filter(pk=stale.pk).exists())
        self.assertEqual(self.slots_on(MONDAY + days(7)), [1, 2])

    def test_replace_keeps_extra_and_cancelled(self):
        extra = self.make_slot(MONDAY + days(8), 6, is_extra=True, reason="Кружок")
        cancelled = self.make_slot(MONDAY + days(7), 1, is_cancelled=True, reason="Актировка")

        response = self.copy(mode="replace")

        self.assertTrue(Slot.objects.filter(pk=extra.pk).exists())
        self.assertTrue(Slot.objects.filter(pk=cancelled.pk).exists())
        # первый урок понедельника занят отменённым — его пропустили
        self.assertEqual(response.json()["skipped"], 1)
        self.assertEqual(self.slots_on(MONDAY + days(7)), [1, 2])

    def test_extra_and_cancelled_are_not_copied_from_the_source(self):
        self.make_slot(MONDAY + days(1), 1, is_extra=True, reason="Замена")
        self.make_slot(MONDAY + days(1), 2, is_cancelled=True, reason="Болезнь")

        self.copy()

        self.assertEqual(self.slots_on(MONDAY + days(8)), [])

    def test_copy_into_another_schools_course_is_rejected(self):
        response = self.copy(course_id=self.alien_class.pk)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Slot.objects.filter(course=self.alien_class).count(), 0)

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
            "course": self.course.pk,
            "start": MONDAY.isoformat(),
            "end": (MONDAY + days(6)).isoformat(),
            **params,
        }
        # параметры именно в строке запроса: тело у DELETE отдавать не принято
        return self.client.delete(f"{reverse('slot-bulk')}?{urlencode(query)}")

    def test_deletes_everything_in_the_period(self):
        response = self.bulk()

        self.assertEqual(response.json(), {"deleted": 3, "kept": 0})
        self.assertEqual(list(Slot.objects.all()), [self.outside])

    def test_only_regular_keeps_extra_and_cancelled(self):
        response = self.bulk(only_regular="true")

        # уцелевшие названы числом: ряд, из которого убрали половину,
        # иначе выглядит как неудавшееся удаление
        self.assertEqual(response.json(), {"deleted": 1, "kept": 2})
        self.assertFalse(Slot.objects.filter(pk=self.regular.pk).exists())
        self.assertTrue(Slot.objects.filter(pk=self.extra.pk).exists())
        self.assertTrue(Slot.objects.filter(pk=self.cancelled.pk).exists())

    def test_another_users_class_is_rejected(self):
        alien_slot = self.make_slot(MONDAY, 1, course=self.alien_class)

        response = self.bulk(**{"course": self.alien_class.pk})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertTrue(Slot.objects.filter(pk=alien_slot.pk).exists())

    def test_missing_parameters_are_rejected(self):
        response = self.client.delete(
            f"{reverse('slot-bulk')}?course={self.course.pk}"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("start", response.json())


class StatsTests(SlotTestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        # для past/remaining нужен год, внутри которого лежит сегодняшний день
        self.current_year = SchoolYear.objects.create(
            school=self.school,
            name="текущий",
            start_date=self.today - days(60),
            end_date=self.today + days(60),
        )
        self.current_class = Course.objects.create(
            school=self.school, year=self.current_year, name="7А"
        )

        self.make_slot(self.today - days(7), 1, course=self.current_class)
        self.make_slot(self.today - days(1), 1, course=self.current_class)
        self.make_slot(self.today, 1, course=self.current_class)
        self.make_slot(self.today + days(3), 1, course=self.current_class)
        self.make_slot(
            self.today + days(4), 2, course=self.current_class, is_extra=True, reason="Кружок"
        )
        self.make_slot(
            self.today - days(2), 3, course=self.current_class,
            is_cancelled=True, reason="Болезнь",
        )
        self.make_slot(
            self.today - days(3), 4, course=self.current_class,
            is_cancelled=True, reason="Болезнь",
        )
        self.make_slot(
            self.today + days(5), 5, course=self.current_class,
            is_cancelled=True, reason="Актировка",
        )

    def stats(self, course=None):
        return self.client.get(
            reverse("slot-stats"),
            {"course": (course or self.current_class).pk},
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
        self.assertEqual(self.stats(self.course)["total"], 1)

    def test_stats_of_another_schools_course_are_empty(self):
        self.make_slot(MONDAY, 1, course=self.alien_class, teacher=self.stranger)

        data = self.stats(self.alien_class)

        self.assertEqual(data["total"], 0)
        self.assertEqual(data["cancelled"], 0)

    def test_stats_without_a_class_cover_all_own_slots(self):
        self.make_slot(MONDAY, 1)

        data = self.client.get(reverse("slot-stats")).json()

        self.assertEqual(data["total"], 6)


class CopyEveryOtherWeekTests(SchoolTestMixin, APITestCase):
    """Шаг доезжает до сервера: «через неделю» — половина уроков."""

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        assign(self.user, self.course)
        make_slot(self.user, self.course, MONDAY, 1)
        make_slot(self.user, self.course, MONDAY + timedelta(days=2), 2)

    def copy(self, **extra):
        response = self.client.post(
            reverse("slot-copy"),
            {
                "course_id": self.course.pk,
                "source_start": MONDAY.isoformat(),
                "source_end": (MONDAY + timedelta(days=6)).isoformat(),
                "target_start": (MONDAY + timedelta(days=7)).isoformat(),
                "target_end": (MONDAY + timedelta(days=27)).isoformat(),
                "mode": "merge",
                **extra,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_every_week_is_the_default(self):
        self.assertEqual(self.copy()["created"], 6)

    def test_every_other_week_creates_half(self):
        """Три недели цели, чётность от источника: заполняется одна, вторая."""
        self.assertEqual(self.copy(step=2)["created"], 2)

    def test_a_step_of_three_is_refused(self):
        response = self.client.post(
            reverse("slot-copy"),
            {
                "course_id": self.course.pk,
                "source_start": MONDAY.isoformat(),
                "source_end": (MONDAY + timedelta(days=6)).isoformat(),
                "target_start": (MONDAY + timedelta(days=7)).isoformat(),
                "target_end": (MONDAY + timedelta(days=13)).isoformat(),
                "step": 3,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class RowDeleteTests(SlotTestCase):
    """
    Ряд убирается рядом же, а не периодом.

    Раскатали час на год и промахнулись номером — раньше выбор был между
    тридцатью четырьмя нажатиями и «очистить период», который сносит и
    десяток чужих часов заодно. Сетку строят рядами, разбирать её надо так
    же.
    """

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)
        # два ряда одного курса: вторничный третий час и он же в среду
        for shift in (0, 7, 14, 21):
            self.make_slot(MONDAY + days(shift + 1), 3)
            self.make_slot(MONDAY + days(shift + 2), 3)
        # и сосед по тому же дню недели, но другим номером
        self.make_slot(MONDAY + days(1), 5)

    def delete_row(self, **extra):
        query = {
            "course": self.course.pk,
            "start": (MONDAY + days(8)).isoformat(),
            "end": YEAR_END.isoformat(),
            "weekday": 1,
            "lesson_number": 3,
            "only_regular": "true",
            **extra,
        }
        return self.client.delete(f"{reverse('slot-bulk')}?{urlencode(query)}")

    def test_only_the_same_weekday_and_number_go(self):
        answer = self.delete_row().json()

        self.assertEqual(answer["deleted"], 3)
        left = sorted(
            (slot.date, slot.lesson_number) for slot in Slot.objects.all()
        )
        # первый вторник (до границы), все среды и сосед по номеру
        self.assertEqual(
            left,
            sorted(
                [(MONDAY + days(1), 3), (MONDAY + days(1), 5)]
                + [(MONDAY + days(shift + 2), 3) for shift in (0, 7, 14, 21)]
            ),
        )

    def test_a_recorded_hour_survives_and_is_counted(self):
        """Запись переживает массовую операцию — и говорит об этом числом."""
        node = make_node(self.user, self.course, "Синус суммы")
        recorded = Slot.objects.get(date=MONDAY + days(8), lesson_number=3)
        recorded.lesson = node
        recorded.save(update_fields=["lesson"])

        answer = self.delete_row().json()

        self.assertEqual((answer["deleted"], answer["kept"]), (2, 1))
        self.assertTrue(Slot.objects.filter(pk=recorded.pk).exists())


class RepeatTests(SlotTestCase):
    """
    Ряд уроков: «вторник, третий час, до конца года» одним движением.

    Путь к этому был один — нарисуй неделю, потом скопируй её на период, —
    и ради одного добавленного часа приходилось раскатывать всю неделю,
    натыкаясь на уже занятые места. Сетку же строят рядами, и решение тут
    одно, а не тридцать четыре.
    """

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def repeat(self, **extra):
        body = {
            "course": self.course.pk,
            "date": MONDAY.isoformat(),
            "lesson_number": 3,
            "until": (MONDAY + days(21)).isoformat(),
            **extra,
        }
        return self.client.post(reverse("slot-repeat"), body, format="json")

    def test_the_row_lands_on_the_same_weekday(self):
        answer = self.repeat().json()

        self.assertEqual(answer["created"], 4)
        placed = list(
            Slot.objects.filter(course=self.course).order_by("date").values_list("date", flat=True)
        )
        self.assertEqual(placed, [MONDAY + days(shift) for shift in (0, 7, 14, 21)])
        self.assertEqual({slot.lesson_number for slot in Slot.objects.all()}, {3})

    def test_every_other_week_puts_half(self):
        """Тот же шаг, что у копирования периода, только вдвое длиннее."""
        answer = self.repeat(step=2).json()

        self.assertEqual(answer["created"], 2)
        placed = list(
            Slot.objects.filter(course=self.course)
            .order_by("date")
            .values_list("date", flat=True)
        )
        self.assertEqual(placed, [MONDAY, MONDAY + days(14)])

    def test_a_break_is_skipped_and_counted(self):
        """Правило не знает, что там каникулы, — поэтому знает сервер."""
        DayException.objects.create(
            year=self.year,
            kind=DayException.Kind.VACATION,
            title="Осенние",
            start_date=MONDAY + days(7),
            end_date=MONDAY + days(11),
        )

        answer = self.repeat().json()

        self.assertEqual(answer["created"], 3)
        self.assertEqual(answer["skipped"], 1)
        self.assertNotIn(
            MONDAY + days(7),
            list(Slot.objects.values_list("date", flat=True)),
        )

    def test_the_first_date_is_taken_as_it_is(self):
        """
        По первой клетке щёлкнули сами, и урок в неучебный день бывает
        законным — отработка, суббота. Повторы человек задал правилом.
        """
        saturday = MONDAY + days(5)

        answer = self.repeat(date=saturday.isoformat(), until=(saturday + days(7)).isoformat())

        self.assertEqual(answer.json()["created"], 1)
        self.assertEqual(answer.json()["skipped"], 1)
        self.assertEqual(Slot.objects.get().date, saturday)

    def test_a_taken_hour_is_skipped_and_named(self):
        other = make_course(self.school, self.year, "9В")
        assign(self.user, other)
        Slot.objects.create(
            year=self.year, course=other, date=MONDAY + days(7), lesson_number=3
        )

        answer = self.repeat().json()

        self.assertEqual(answer["created"], 3)
        self.assertEqual(answer["skipped"], 1)
        self.assertEqual(answer["conflicts"][0]["class_name"], "9В")
        # ряд не отменяется целиком: за год он почти всегда во что-нибудь
        # упрётся, и «не создано ничего» было бы худшим ответом
        self.assertEqual(Slot.objects.filter(course=self.course).count(), 3)

    def test_the_row_stops_at_the_end_of_the_year(self):
        answer = self.repeat(until=(YEAR_END + days(60)).isoformat()).json()

        self.assertTrue(answer["created"] > 30, answer)
        self.assertLessEqual(
            max(Slot.objects.values_list("date", flat=True)), YEAR_END
        )

    def test_a_backwards_boundary_is_refused(self):
        answer = self.repeat(until=(MONDAY - days(7)).isoformat())

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.json()["code"], "period_reversed")

    def test_a_course_of_another_school_is_invisible(self):
        answer = self.repeat(course=self.alien_class.pk)

        self.assertEqual(answer.status_code, 400)
        self.assertFalse(Slot.objects.filter(course=self.alien_class).exists())
