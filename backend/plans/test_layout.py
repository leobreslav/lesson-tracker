"""Раскладка плана по слотам: чистый расчёт и эндпоинты."""

from datetime import date, timedelta

from calendars import services as calendar_services
from calendars.models import DayException, Term
from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from schedule.models import Course, LessonSlot
from schools.testing import assign, make_course

from . import services
from .models import PlanNode
from .test_services import lesson as fake_lesson
from .test_services import section as fake_section
from .tests import PlanTestCase

MONDAY = date(2026, 9, 7)


class FakeSlot:
    """Минимум полей, которых хватает build_layout."""

    def __init__(self, pk, day, lesson_number=1, is_extra=False):
        self.pk = pk
        self.date = day
        self.lesson_number = lesson_number
        self.is_extra = is_extra


def lessons(count, start=1):
    tree = services.build_tree(
        [fake_lesson(index, index - 1, title=f"Урок {index}") for index in range(start, start + count)]
    )
    return services.number_lessons(tree)


def slots(count, first=MONDAY):
    return [FakeSlot(100 + index, first + timedelta(days=index)) for index in range(count)]


class BuildLayoutTests(SimpleTestCase):
    def statuses(self, entries):
        return [entry.status for entry in entries]

    def test_equal_lengths_match_one_to_one(self):
        entries = services.build_layout(lessons(3), slots(3))

        self.assertEqual(self.statuses(entries), [services.STATUS_MATCHED] * 3)
        self.assertEqual(
            [(entry.lesson.number, entry.slot.pk) for entry in entries],
            [(1, 100), (2, 101), (3, 102)],
        )

    def test_plan_shorter_than_schedule(self):
        entries = services.build_layout(lessons(2), slots(4))

        self.assertEqual(
            self.statuses(entries),
            [services.STATUS_MATCHED] * 2 + [services.STATUS_NO_PLAN] * 2,
        )
        # лишние слоты остаются на своих местах и без урока
        self.assertIsNone(entries[2].lesson)
        self.assertEqual(entries[2].slot.pk, 102)

    def test_plan_longer_than_schedule(self):
        entries = services.build_layout(lessons(4), slots(2))

        self.assertEqual(
            self.statuses(entries),
            [services.STATUS_MATCHED] * 2 + [services.STATUS_NO_SLOT] * 2,
        )
        # лишние уроки идут в конец и без слота
        self.assertIsNone(entries[3].slot)
        self.assertEqual(entries[3].lesson.number, 4)

    def test_empty_plan(self):
        entries = services.build_layout([], slots(2))

        self.assertEqual(self.statuses(entries), [services.STATUS_NO_PLAN] * 2)

    def test_empty_schedule(self):
        entries = services.build_layout(lessons(2), [])

        self.assertEqual(self.statuses(entries), [services.STATUS_NO_SLOT] * 2)

    def test_both_empty(self):
        self.assertEqual(services.build_layout([], []), [])

    def test_section_title_comes_from_the_folder(self):
        nodes = [
            fake_section(1, 0, "Тригонометрия"),
            fake_lesson(11, 0, parent_id=1, title="Синус"),
            fake_lesson(2, 1, title="Повторение"),
        ]
        plan = services.number_lessons(services.build_tree(nodes))

        entries = services.build_layout(plan, slots(2))

        self.assertEqual(entries[0].lesson.section.title, "Тригонометрия")
        # урок вне папки темы не имеет
        self.assertIsNone(entries[1].lesson.section)


class LayoutSummaryTests(SimpleTestCase):
    def setUp(self):
        self.today = date(2026, 9, 10)

    def test_counts_split_by_today(self):
        entries = services.build_layout(lessons(5), slots(5))

        summary = services.layout_summary(entries, self.today)

        self.assertEqual(summary["slots_total"], 5)
        self.assertEqual(summary["lessons_total"], 5)
        self.assertEqual(summary["balance"], 0)
        self.assertEqual(summary["past_slots"], 3)  # 7, 8, 9 сентября
        self.assertEqual(summary["remaining_slots"], 2)
        self.assertEqual(summary["past_lessons"], 3)
        self.assertEqual(summary["remaining_lessons"], 2)
        self.assertEqual(summary["last_lesson_date"], MONDAY + timedelta(days=4))

    def test_balance_is_negative_when_the_plan_does_not_fit(self):
        summary = services.layout_summary(
            services.build_layout(lessons(6), slots(4)), self.today
        )

        self.assertEqual(summary["balance"], -2)
        # последнего урока в году нет: план не помещается
        self.assertIsNone(summary["last_lesson_date"])
        self.assertEqual(summary["remaining_lessons"], 3)

    def test_spare_slots_give_positive_balance(self):
        summary = services.layout_summary(
            services.build_layout(lessons(2), slots(5)), self.today
        )

        self.assertEqual(summary["balance"], 3)
        self.assertEqual(summary["last_lesson_date"], MONDAY + timedelta(days=1))

    def test_extra_and_cancelled_counters(self):
        with_extra = slots(3)
        with_extra[1].is_extra = True

        summary = services.layout_summary(
            services.build_layout(lessons(3), with_extra), self.today, cancelled_count=4
        )

        self.assertEqual(summary["extra_count"], 1)
        self.assertEqual(summary["cancelled_count"], 4)

    def test_empty_everything(self):
        summary = services.layout_summary([], self.today)

        self.assertEqual(summary["lessons_total"], 0)
        self.assertEqual(summary["slots_total"], 0)
        self.assertEqual(summary["balance"], 0)
        self.assertIsNone(summary["last_lesson_date"])


class LayoutApiTestCase(PlanTestCase):
    """Общая подготовка: план из семи уроков и слоты по дням."""

    def setUp(self):
        super().setUp()
        self.trig, self.vectors, self.stereo = self.build_sample()  # 7 уроков плана
        self.slot_date = MONDAY

    def add_slot(self, day=None, number=1, course=None, **flags):
        return LessonSlot.objects.create(
            teacher=self.user,
            year=(course or self.course).year,
            course=course or self.course,
            date=day or self.slot_date,
            lesson_number=number,
            **flags,
        )

    def fill_slots(self, count, course=None):
        """По одному слоту в день, начиная с понедельника."""
        return [
            self.add_slot(MONDAY + timedelta(days=index), course=course)
            for index in range(count)
        ]

    def layout(self, params=None):
        return self.client.get(
            reverse("plannode-layout"),
            {"course": self.course.pk, **(params or {})},
        )

    def summary(self):
        return self.client.get(
            reverse("plannode-layout-summary"), {"course": self.course.pk}
        )

    def pairs(self, response=None):
        data = (response or self.layout()).json()
        return [
            (
                entry["status"],
                entry["slot"] and entry["slot"]["date"],
                entry["plan_row"] and entry["plan_row"]["title"],
            )
            for entry in data["entries"]
        ]


class LayoutApiTests(LayoutApiTestCase):
    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.layout().status_code, 401)

    def test_class_parameter_is_required(self):
        self.assertEqual(
            self.client.get(reverse("plannode-layout")).status_code, 400
        )

    def test_another_users_class_is_not_found(self):
        response = self.client.get(
            reverse("plannode-layout"), {"course": self.alien_class.pk}
        )

        self.assertEqual(response.status_code, 404)

    def test_layout_matches_plan_to_slots_in_order(self):
        self.fill_slots(3)

        self.assertEqual(
            self.pairs(),
            [
                ("matched", "2026-09-07", "Синус суммы"),
                ("matched", "2026-09-08", "Косинус суммы"),
                ("matched", "2026-09-09", "Понятие вектора"),
                ("no_slot", None, "Сложение векторов"),
                ("no_slot", None, "Повторение"),
                ("no_slot", None, "Контрольная работа"),
                ("no_slot", None, "Аксиомы"),
            ],
        )

    def test_spare_slots_are_free(self):
        self.fill_slots(9)

        pairs = self.pairs()

        self.assertEqual(pairs[6], ("matched", "2026-09-13", "Аксиомы"))
        self.assertEqual(pairs[7], ("no_plan", "2026-09-14", None))
        self.assertEqual(pairs[8], ("no_plan", "2026-09-15", None))

    def test_section_title_is_reported(self):
        self.fill_slots(5)

        entries = self.layout().json()["entries"]

        self.assertEqual(entries[0]["plan_row"]["section_title"], "Тригонометрия")
        self.assertIsNone(entries[4]["plan_row"]["section_title"])

    def test_cancelling_a_slot_shifts_everything_after_it(self):
        created = self.fill_slots(4)
        before = self.pairs()

        self.client.patch(
            reverse("lessonslot-detail", args=[created[1].pk]),
            {"is_cancelled": True, "reason": "Болезнь"},
            format="json",
        )

        after = self.pairs()
        self.assertEqual(before[1], ("matched", "2026-09-08", "Косинус суммы"))
        # отменённый слот выпал, всё после него подтянулось на одну позицию
        self.assertEqual(after[1], ("matched", "2026-09-09", "Косинус суммы"))
        self.assertEqual(after[2], ("matched", "2026-09-10", "Понятие вектора"))

    def test_restoring_a_slot_puts_the_layout_back(self):
        created = self.fill_slots(4)
        before = self.pairs()
        url = reverse("lessonslot-detail", args=[created[1].pk])

        self.client.patch(url, {"is_cancelled": True, "reason": "Болезнь"}, format="json")
        self.client.patch(url, {"is_cancelled": False, "reason": ""}, format="json")

        self.assertEqual(self.pairs(), before)

    def test_extra_slot_adds_a_position(self):
        self.fill_slots(3)

        self.add_slot(MONDAY, number=2, is_extra=True, reason="Замена")

        pairs = self.pairs()
        self.assertEqual(len(pairs), 7)
        self.assertEqual(pairs[1], ("matched", "2026-09-07", "Косинус суммы"))
        self.assertTrue(self.layout().json()["entries"][1]["slot"]["is_extra"])

    def test_inserting_a_lesson_shifts_the_rest_including_the_past(self):
        """Правка задним числом честно двигает всю раскладку."""
        self.fill_slots(7)
        before = self.pairs()

        self.client.post(
            reverse("plannode-list"),
            {
                "course": self.course.pk,
                "parent": self.trig.pk,
                "title": "Вставка",
                "after": self.node("Синус суммы").pk,
            },
            format="json",
        )

        after = self.pairs()
        self.assertEqual(before[1], ("matched", "2026-09-08", "Косинус суммы"))
        self.assertEqual(after[1], ("matched", "2026-09-08", "Вставка"))
        self.assertEqual(after[2], ("matched", "2026-09-09", "Косинус суммы"))
        self.assertEqual(after[-1], ("no_slot", None, "Аксиомы"))

    def test_period_filter_cuts_the_ready_layout(self):
        self.fill_slots(7)

        response = self.layout({"from": "2026-09-09", "to": "2026-09-10"})

        self.assertEqual(
            self.pairs(response),
            [
                ("matched", "2026-09-09", "Понятие вектора"),
                ("matched", "2026-09-10", "Сложение векторов"),
            ],
        )

    def test_garbage_period_is_ignored(self):
        self.fill_slots(2)

        response = self.layout({"from": "2026-13-45"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["entries"]), 7)

    def test_empty_plan_and_schedule_do_not_break(self):
        PlanNode.objects.filter(teacher=self.user, course=self.course).delete()

        response = self.layout()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["entries"], [])

    def test_other_classes_slots_are_not_used(self):
        second = Course.objects.create(
            school=self.school, year=self.course.year, name="10А"
        )
        self.fill_slots(2, course=second)

        self.assertEqual(
            [entry[0] for entry in self.pairs()], ["no_slot"] * 7
        )


class LayoutTermTests(LayoutApiTestCase):
    """Группировка раскладки по четвертям."""

    def setUp(self):
        super().setUp()
        self.first = Term.objects.create(
            year=self.course.year,
            name="1 четверть",
            start_date=MONDAY,
            end_date=MONDAY + timedelta(days=4),
        )
        self.second = Term.objects.create(
            year=self.course.year,
            name="2 четверть",
            start_date=MONDAY + timedelta(days=7),
            end_date=MONDAY + timedelta(days=11),
        )

    def test_entries_carry_the_term(self):
        self.fill_slots(9)

        entries = self.layout().json()["entries"]

        by_date = {entry["slot"]["date"]: entry for entry in entries if entry["slot"]}
        self.assertEqual(by_date["2026-09-07"]["term_name"], "1 четверть")
        self.assertEqual(by_date["2026-09-14"]["term_name"], "2 четверть")
        # выходные между четвертями ни в один терм не входят
        self.assertIsNone(by_date["2026-09-12"]["term_id"])

    def test_summary_counts_each_term(self):
        self.fill_slots(9)

        rows = self.summary().json()["terms"]

        self.assertEqual(
            [(row["name"], row["slots"], row["lessons"], row["balance"]) for row in rows],
            [
                ("1 четверть", 5, 5, 0),
                ("2 четверть", 2, 0, 2),
                ("вне термов", 2, 2, 0),
            ],
        )
        self.assertEqual(rows[0]["start"], MONDAY.isoformat())

    def test_term_counters_add_up_to_the_totals(self):
        self.fill_slots(9)

        data = self.summary().json()

        self.assertEqual(
            sum(row["slots"] for row in data["terms"]), data["slots_total"]
        )
        self.assertEqual(
            sum(row["lessons"] for row in data["terms"]), data["lessons_total"]
        )
        self.assertEqual(
            sum(row["balance"] for row in data["terms"]), data["balance"]
        )

    def test_lessons_without_slots_land_outside_terms(self):
        self.fill_slots(3)

        rows = self.summary().json()["terms"]

        first, outside = rows[0], rows[-1]
        self.assertEqual((first["slots"], first["lessons"]), (3, 3))
        self.assertEqual(outside["name"], "вне термов")
        # четырём урокам плана слотов не хватило — это и есть дефицит
        self.assertEqual((outside["slots"], outside["lessons"], outside["balance"]), (0, 4, -4))

    def test_empty_term_is_still_reported(self):
        self.fill_slots(3)

        rows = self.summary().json()["terms"]

        second = next(row for row in rows if row["name"] == "2 четверть")
        self.assertEqual((second["slots"], second["lessons"], second["balance"]), (0, 0, 0))

    def test_year_without_terms_puts_everything_outside(self):
        Term.objects.all().delete()
        self.fill_slots(3)

        rows = self.summary().json()["terms"]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "вне термов")
        self.assertEqual(rows[0]["slots"], 3)

    def test_vacation_inside_a_term_only_removes_slots(self):
        """Каникулы убирают слоты, но терм остаётся термом."""
        DayException.objects.create(
            year=self.course.year,
            start_date=MONDAY + timedelta(days=1),
            end_date=MONDAY + timedelta(days=2),
            kind=calendar_services.KIND_VACATION,
            title="Каникулы",
        )
        self.fill_slots(5)

        rows = self.summary().json()["terms"]

        # слоты в каникулы никто не удалял — раскладка их учитывает как есть
        self.assertEqual(rows[0]["slots"], 5)
        self.assertEqual(rows[0]["lessons"], 5)

    def test_terms_of_another_users_year_are_not_used(self):
        alien_year = self.alien_class.year
        Term.objects.create(
            year=alien_year,
            name="Чужая четверть",
            start_date=MONDAY,
            end_date=MONDAY + timedelta(days=30),
        )
        self.fill_slots(3)

        names = [row["name"] for row in self.summary().json()["terms"]]

        self.assertNotIn("Чужая четверть", names)


class LayoutSummaryApiTests(LayoutApiTestCase):
    def test_summary_agrees_with_layout(self):
        self.fill_slots(9)

        data = self.summary().json()
        entries = self.layout().json()["entries"]

        self.assertEqual(
            data["slots_total"], sum(1 for item in entries if item["slot"])
        )
        self.assertEqual(
            data["lessons_total"], sum(1 for item in entries if item["plan_row"])
        )
        self.assertEqual(data["balance"], data["slots_total"] - data["lessons_total"])
        self.assertEqual(
            data["past_slots"] + data["remaining_slots"], data["slots_total"]
        )
        self.assertEqual(
            data["past_lessons"] + data["remaining_lessons"], data["lessons_total"]
        )

    def test_summary_counts_past_by_today(self):
        today = timezone.localdate()
        self.add_slot(today - timedelta(days=1))
        self.add_slot(today)
        self.add_slot(today + timedelta(days=1))

        data = self.summary().json()

        self.assertEqual(data["past_slots"], 1)
        self.assertEqual(data["remaining_slots"], 2)
        self.assertEqual(data["past_lessons"], 1)
        self.assertEqual(data["remaining_lessons"], 6)

    def test_summary_reports_cancelled_and_extra(self):
        created = self.fill_slots(3)
        self.add_slot(MONDAY, number=2, is_extra=True, reason="Замена")
        created[0].is_cancelled = True
        created[0].reason = "Болезнь"
        created[0].save()

        data = self.summary().json()

        self.assertEqual(data["cancelled_count"], 1)
        self.assertEqual(data["extra_count"], 1)
        self.assertEqual(data["slots_total"], 3)

    def test_last_lesson_date_is_null_when_the_plan_does_not_fit(self):
        self.fill_slots(3)

        self.assertIsNone(self.summary().json()["last_lesson_date"])

    def test_last_lesson_date_when_everything_fits(self):
        self.fill_slots(9)

        self.assertEqual(self.summary().json()["last_lesson_date"], "2026-09-13")

    def test_summary_of_another_users_class_is_not_found(self):
        response = self.client.get(
            reverse("plannode-layout-summary"), {"course": self.alien_class.pk}
        )

        self.assertEqual(response.status_code, 404)


class SlotRibbonTests(LayoutApiTestCase):
    """
    Лента слотов — половина раскладки, которая от плана не зависит.

    Её берёт страница плана, чтобы сшивать даты с деревом у себя: правка
    плана меняет только вторую половину, а она тривиальна.
    """

    def setUp(self):
        super().setUp()
        self.first = Term.objects.create(
            year=self.course.year,
            name="1 четверть",
            start_date=MONDAY,
            end_date=MONDAY + timedelta(days=4),
        )
        self.second = Term.objects.create(
            year=self.course.year,
            name="2 четверть",
            start_date=MONDAY + timedelta(days=10),
            end_date=MONDAY + timedelta(days=20),
        )

    def ribbon(self, course=None):
        return self.client.get(
            reverse("plannode-layout-slots"),
            {"course": (course or self.course).pk},
        )

    def test_it_carries_dates_in_order(self):
        self.fill_slots(3)

        rows = self.ribbon().json()["slots"]

        self.assertEqual(
            [row["date"] for row in rows],
            [str(MONDAY + timedelta(days=index)) for index in range(3)],
        )

    def test_a_cancelled_lesson_is_not_in_the_ribbon(self):
        """Отменённый урок не занимает место в плане — и в ленте его нет."""
        self.fill_slots(2)
        self.add_slot(MONDAY + timedelta(days=2), is_cancelled=True)

        self.assertEqual(len(self.ribbon().json()["slots"]), 2)

    def test_every_slot_carries_its_term_with_dates(self):
        """
        Терм целиком, а не только его id: по смене терма страница плана
        рисует заголовок с датами, и второго запроса за ними быть не должно.
        """
        self.fill_slots(12)

        rows = self.ribbon().json()["slots"]

        self.assertEqual(rows[0]["term"]["name"], "1 четверть")
        self.assertEqual(rows[0]["term"]["start"], str(MONDAY))
        self.assertEqual(rows[0]["term"]["end"], str(MONDAY + timedelta(days=4)))
        # шестой слот приходится на промежуток между четвертями
        self.assertIsNone(rows[5]["term"])
        self.assertEqual(rows[10]["term"]["name"], "2 четверть")

    def test_a_break_between_two_lessons_is_named(self):
        DayException.objects.create(
            year=self.course.year,
            start_date=MONDAY + timedelta(days=5),
            end_date=MONDAY + timedelta(days=9),
            kind=DayException.Kind.VACATION,
            title="осенние каникулы",
        )
        # уроки по краям каникул, между ними — дыра
        self.add_slot(MONDAY)
        self.add_slot(MONDAY + timedelta(days=10))

        rows = self.ribbon().json()["slots"]

        self.assertIsNone(rows[0]["break_before"])
        self.assertEqual(rows[1]["break_before"]["title"], "осенние каникулы")
        self.assertEqual(
            rows[1]["break_before"]["start"], str(MONDAY + timedelta(days=5))
        )

    def test_a_break_that_no_lesson_straddles_is_not_mentioned(self):
        """Каникулы после последнего урока ничего не разрывают."""
        DayException.objects.create(
            year=self.course.year,
            start_date=MONDAY + timedelta(days=5),
            end_date=MONDAY + timedelta(days=9),
            kind=DayException.Kind.VACATION,
            title="осенние каникулы",
        )
        self.add_slot(MONDAY)

        self.assertIsNone(self.ribbon().json()["slots"][0]["break_before"])

    def test_a_holiday_is_not_a_break(self):
        """Праздник в один день ленту не рвёт: о нём и говорить нечего."""
        DayException.objects.create(
            year=self.course.year,
            start_date=MONDAY + timedelta(days=1),
            end_date=MONDAY + timedelta(days=1),
            kind=DayException.Kind.HOLIDAY,
            title="праздник",
        )
        self.add_slot(MONDAY)
        self.add_slot(MONDAY + timedelta(days=2))

        self.assertIsNone(self.ribbon().json()["slots"][1]["break_before"])

    def test_it_agrees_with_the_layout(self):
        """
        Два ответа об одном и том же не должны расходиться: лента — это
        раскладка без плана, и даты с термами в них одни и те же.
        """
        self.fill_slots(12)

        ribbon = self.ribbon().json()["slots"]
        entries = [
            entry
            for entry in self.layout().json()["entries"]
            if entry["slot"] is not None
        ]

        self.assertEqual(
            [(row["date"], row["term_id"]) for row in ribbon[: len(entries)]],
            [(entry["slot"]["date"], entry["term_id"]) for entry in entries],
        )

    def test_the_entries_and_the_summary_count_the_same_thing(self):
        """
        Сводка — это те же записи раскладки, посчитанные ещё раз.

        Раньше сверялись только даты и термы, а числа — резерв, «не
        помещается», последний урок — не сверялись вовсе: расхождение между
        лентой на странице плана и сводкой прошло бы молча. Конфигураций
        несколько, потому что расходятся такие вещи на краях: пустой план,
        пустое расписание, отмены.
        """
        cases = {
            "план короче": {"slots": 12, "cancelled": 0, "extra": 0},
            "план длиннее": {"slots": 3, "cancelled": 0, "extra": 0},
            "ровно по плану": {"slots": 7, "cancelled": 0, "extra": 0},
            "с отменёнными": {"slots": 9, "cancelled": 2, "extra": 0},
            "с дополнительными": {"slots": 9, "cancelled": 0, "extra": 2},
            "без расписания": {"slots": 0, "cancelled": 0, "extra": 0},
        }

        for name, spec in cases.items():
            with self.subTest(name):
                LessonSlot.objects.filter(course=self.course).delete()
                day = MONDAY
                for index in range(spec["slots"]):
                    self.add_slot(
                        day + timedelta(days=index),
                        is_cancelled=index < spec["cancelled"],
                        is_extra=index >= spec["slots"] - spec["extra"],
                    )

                entries = self.layout().json()["entries"]
                summary = self.summary().json()

                with_slot = [row for row in entries if row["slot"]]
                with_lesson = [row for row in entries if row["plan_row"]]
                matched = [row for row in entries if row["status"] == "matched"]
                fits = len(matched) == len(with_lesson)

                self.assertEqual(summary["slots_total"], len(with_slot), name)
                self.assertEqual(summary["lessons_total"], len(with_lesson), name)
                self.assertEqual(
                    summary["balance"], len(with_slot) - len(with_lesson), name
                )
                self.assertEqual(
                    summary["last_lesson_date"],
                    matched[-1]["slot"]["date"] if fits and matched else None,
                    name,
                )
                # «не помещается» — это записи без слота, и никак иначе
                self.assertEqual(
                    len([row for row in entries if row["status"] == "no_slot"]),
                    len(with_lesson) - len(matched),
                    name,
                )
                self.assertEqual(
                    summary["past_lessons"] + summary["remaining_lessons"],
                    summary["lessons_total"],
                    name,
                )

    def test_slots_carry_the_school_week_and_its_monday(self):
        """
        Нумерация сквозная от начала года, а не календарная: учителю важно,
        какая это неделя занятий.
        """
        year = self.course.year
        year.start_date = MONDAY
        year.save(update_fields=["start_date"])
        self.fill_slots(12)

        rows = self.ribbon().json()["slots"]

        self.assertEqual(rows[0]["week"], 1)
        self.assertEqual(rows[0]["week_start"], str(MONDAY))
        # шестой слот — воскресенье той же недели, седьмой уже следующая
        self.assertEqual(rows[6]["week"], 1)
        self.assertEqual(rows[7]["week"], 2)
        self.assertEqual(rows[7]["week_start"], str(MONDAY + timedelta(days=7)))

    def test_a_week_lost_to_a_break_does_not_take_a_number(self):
        """
        Счёт идёт по учебным неделям: неделя, целиком выпавшая на каникулы,
        номера не получает, и следующая за ней не «третья по календарю», а
        вторая по занятиям.
        """
        year = self.course.year
        year.start_date = MONDAY
        year.save(update_fields=["start_date"])
        DayException.objects.create(
            year=year,
            start_date=MONDAY + timedelta(days=7),
            end_date=MONDAY + timedelta(days=13),
            kind=DayException.Kind.VACATION,
            title="каникулы",
        )
        self.add_slot(MONDAY)
        self.add_slot(MONDAY + timedelta(days=14))

        rows = self.ribbon().json()["slots"]

        self.assertEqual([row["week"] for row in rows], [1, 2])

    def test_a_year_starting_midweek_still_has_a_first_week(self):
        """Год начался во вторник — эта неделя первая, следующая вторая."""
        year = self.course.year
        year.start_date = MONDAY - timedelta(days=6)  # прошлый вторник
        year.save(update_fields=["start_date"])

        self.add_slot(MONDAY - timedelta(days=5))
        self.add_slot(MONDAY)

        weeks = [row["week"] for row in self.ribbon().json()["slots"]]
        self.assertEqual(weeks, [1, 2])

    def test_another_teachers_course_is_not_found(self):
        self.assertEqual(self.ribbon(self.alien_class).status_code, 404)

    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.ribbon().status_code, 401)


class ProgressTests(LayoutApiTestCase):
    """
    Экран «Раскладка»: где курс идёт, успевает ли и что впереди.

    Считает всё то же `build_layout`, что и остальные ответы про раскладку,
    поэтому проверяется не арифметика сопоставления, а то, что поверх неё:
    темп, текущий терм и счётчики, которых больше нигде нет.
    """

    def progress(self):
        return self.client.get(reverse("plannode-progress"))

    def courses(self):
        return {row["name"]: row for row in self.progress().json()["courses"]}

    def test_it_answers_for_every_course_at_once(self):
        """План всегда про один курс, раскладка — про все."""
        second = make_course(self.school, year=self.course.year, name="9А")
        assign(self.user, second)
        self.add_slot(course=second)

        names = set(self.courses())

        self.assertIn(self.course.name, names)
        self.assertIn("9А", names)

    def test_where_i_am_is_the_next_lesson(self):
        self.fill_slots(9)

        row = self.courses()[self.course.name]

        self.assertEqual(row["lessons_total"], 7)
        # год ещё не начался, поэтому «сейчас» — самый первый урок плана
        self.assertEqual(row["current"]["number"], 1)
        self.assertEqual(row["current"]["title"], "Синус суммы")
        self.assertEqual(row["current"]["section_title"], "Тригонометрия")
        self.assertEqual(row["done"], 0)

    def test_the_next_lessons_come_with_dates(self):
        """Два, а не пять: экран отвечает «что готовить», а не «что дальше»."""
        self.fill_slots(9)

        upcoming = self.courses()[self.course.name]["next"]

        self.assertEqual(len(upcoming), 2)
        self.assertEqual(upcoming[0]["date"], str(MONDAY))
        self.assertEqual([row["number"] for row in upcoming], [1, 2])

    def test_reserve_is_slots_minus_lessons(self):
        """
        Резерв — главное число экрана: плюс значит запас дней, минус — что
        план не помещается. Порогов между ними нет.
        """
        self.fill_slots(9)

        row = self.courses()[self.course.name]

        self.assertEqual(row["slots_total"], 9)
        self.assertEqual(row["lessons_total"], 7)
        self.assertEqual(row["reserve"], 2)

    def test_a_plan_longer_than_the_year_has_a_negative_reserve(self):
        self.fill_slots(3)

        row = self.courses()[self.course.name]

        self.assertEqual(row["reserve"], -4)
        self.assertEqual(row["missing"], 4)

    def test_done_counts_lessons_already_taught(self):
        """Даты считаем от сегодняшнего дня, иначе «прошло» зависело бы от
        того, когда прогоняют тесты."""
        now = timezone.localdate()
        for index in range(3):
            self.add_slot(now - timedelta(days=index + 1))
        for index in range(3):
            self.add_slot(now + timedelta(days=index + 1))

        row = self.courses()[self.course.name]

        self.assertEqual(row["done"], 3)

    def test_a_plan_that_does_not_fit_has_no_end_date(self):
        self.fill_slots(3)

        row = self.courses()[self.course.name]

        self.assertIsNone(row["last_lesson_date"])
        self.assertEqual(row["missing"], 4)

    def test_counters_the_plan_page_does_not_have(self):
        self.fill_slots(9)
        self.add_slot(MONDAY + timedelta(days=20), is_extra=True)
        self.add_slot(MONDAY + timedelta(days=21), is_cancelled=True, reason="Болезнь")
        self.add_slot(MONDAY + timedelta(days=22), is_cancelled=True, reason="Болезнь")
        self.add_slot(MONDAY + timedelta(days=23), is_cancelled=True)

        row = self.courses()[self.course.name]

        self.assertEqual(row["extra"], 1)
        self.assertEqual(row["cancelled"], 3)
        # причин здесь нет: их место в расписании, где отмену и ставили
        self.assertNotIn("cancelled_by_reason", row)
        self.assertEqual(row["reserve"], 3)

    def test_a_plan_can_end_past_the_end_of_the_year(self):
        """
        Проверка достижимости, а не арифметики.

        Урок всегда стоит внутри границ года — так его валидирует сервер, —
        и казалось бы, последний урок плана не может оказаться позже конца
        года. Может: границы года правятся **после**, и сужение проверяет
        только разметку календаря, но не расписание. Предупреждение на
        экране состояния живёт ровно ради этого случая.
        """
        self.fill_slots(9)
        year = self.course.year
        year.end_date = MONDAY + timedelta(days=1)
        year.save(update_fields=["end_date"])

        row = self.courses()[self.course.name]

        self.assertGreater(row["last_lesson_date"], str(row["year_end"]))

    def test_the_number_of_queries_does_not_grow_with_the_courses(self):
        """
        Экран открывают из бара, и стоил он по шесть запросов на курс:
        уроки, отмены, план, термы, эталон и его строки. Проверяется не
        конкретное число — оно поедет от любой соседней правки, — а то, что
        от числа курсов оно не зависит вовсе.
        """
        self.fill_slots(9)

        with CaptureQueriesContext(connection) as one_course:
            self.progress()

        for index in range(3):
            extra = make_course(self.school, year=self.course.year, name=f"9{index}")
            assign(self.user, extra)
            self.add_slot(course=extra, number=index + 3)

        with CaptureQueriesContext(connection) as four_courses:
            response = self.progress()

        self.assertEqual(len(response.json()["courses"]), 4)
        self.assertEqual(
            len(four_courses),
            len(one_course),
            f"запросы растут с курсами: {len(one_course)} против "
            f"{len(four_courses)}",
        )

    def test_another_teachers_course_is_not_there(self):
        other = make_course(
            self.alien_school, year=self.alien_class.year, name="9В"
        )
        assign(self.stranger, other)

        self.assertNotIn("9В", self.courses())

    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.progress().status_code, 401)


