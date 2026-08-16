"""
Связь «занятие проведено»: запись сильнее позиции.

Раскладка была чистым `zip` — i-й урок плана в i-й час, — то есть не
записью, а догадкой: допущением, что программа и календарь идут в ногу.
Догадка хорошая и бесплатная, но она молча переписывала прошлое: вставили
урок в сентябрьскую тему в марте, и сентябрь съезжал вместе со всей лентой.

Теперь у часа бывает связь (`Slot.lesson`), и правило двухступенчатое: час
со связью показывает свой урок, остальные разбирают оставшиеся по порядку.
Здесь проверяется и само правило, и то, что из него следует, — а следует
из него в том числе запрет двигать проведённую строку: позиция и запись
иначе начинают говорить разное.
"""

from datetime import timedelta

from django.urls import reverse
from schedule.models import Slot

from . import services
from .models import PlanNode
from .test_layout import MONDAY, LayoutApiTestCase


class RecordedLayoutTests(LayoutApiTestCase):
    def setUp(self):
        super().setUp()
        # семь уроков плана из фикстуры, семь дней подряд
        self.slots = self.fill_slots(7)
        # именно в порядке показа: раскладка идёт по нему, а не по pk
        self.rows = [
            lesson.node for lesson in services.flatten_lessons(self.course.pk)
        ]

    def layout(self):
        response = self.client.get(
            reverse("plannode-layout"), {"course": self.course.pk}
        )
        return response.json()["entries"]

    def dates_of(self):
        return {
            entry["plan_row"]["title"]: entry["slot"]["date"]
            for entry in self.layout()
            if entry["plan_row"] and entry["slot"]
        }

    def record(self, slot, node):
        slot.lesson = node
        slot.save(update_fields=["lesson"])

    def test_a_recorded_hour_shows_its_own_lesson(self):
        """Даже если по счёту в нём должен был стоять другой."""
        last = self.rows[-1]
        self.record(self.slots[0], last)

        first = self.layout()[0]

        self.assertEqual(first["plan_row"]["title"], last.title)

    def test_the_others_take_what_is_left_in_order(self):
        self.record(self.slots[0], self.rows[-1])

        titles = [
            entry["plan_row"]["title"] for entry in self.layout() if entry["plan_row"]
        ]

        self.assertEqual(titles[0], self.rows[-1].title)
        self.assertEqual(titles[1:], [row.title for row in self.rows[:-1]])

    def test_a_recorded_date_does_not_move_when_the_plan_does(self):
        """
        Ради этого связь и заведена: раскладка позиционная, и урок,
        вставленный в начало, сдвинул бы всю ленту вместе с историей.
        """
        anchored = self.rows[2]
        self.record(self.slots[2], anchored)
        before = self.dates_of()[anchored.title]

        self.add_first()

        self.assertEqual(self.dates_of()[anchored.title], before)

    def add_first(self):
        """Урок в самое начало плана: всё, что ниже, обязано сдвинуться."""
        created = self.client.post(
            reverse("plannode-list"),
            {"course": self.course.pk, "title": "Вводный", "parent": None},
            format="json",
        ).json()
        self.client.post(
            reverse("plannode-move-to", args=[created["id"]]),
            {"parent": None, "position": 0},
            format="json",
        )

    def test_an_unrecorded_lesson_does_move(self):
        """И это честно: о нём никто ничего не говорил."""
        drifting = self.rows[3]
        before = self.dates_of()[drifting.title]

        self.add_first()

        self.assertNotEqual(self.dates_of()[drifting.title], before)

    def test_free_hours_can_sit_in_the_middle(self):
        """
        Хвостом свободные часы были, пока сопоставление было чистым zip'ом.

        План кончился, а дальше стоит связанный час — и незанятые оказались
        между занятыми. Всё, что ходит по раскладке срезом, на этом ломается.
        """
        # только уроки: темы удалять нельзя, они унесут детей каскадом
        PlanNode.objects.filter(course=self.course, is_section=False).exclude(
            pk__in=[self.rows[0].pk, self.rows[-1].pk]
        ).delete()
        self.record(self.slots[6], self.rows[-1])

        statuses = [entry["status"] for entry in self.layout()]

        self.assertEqual(statuses[0], "matched")
        self.assertEqual(statuses[1:6], ["no_plan"] * 5)
        self.assertEqual(statuses[6], "matched")

    def test_the_tree_says_which_rows_were_taught(self):
        """Ручку перетаскивания надо прятать и тогда, когда даты выключены."""
        self.record(self.slots[0], self.rows[0])

        tree = self.client.get(
            reverse("plannode-list"), {"course": self.course.pk}
        ).json()["nodes"]
        taught = {
            row["title"]: row["taught"]
            for node in tree
            for row in ([node] + node.get("children", []))
        }

        self.assertTrue(taught[self.rows[0].title])
        self.assertFalse(taught[self.rows[1].title])


class TaughtRowsStayPutTests(LayoutApiTestCase):
    """
    Проведённую строку с места не двигают.

    Пока строка не связана, порядок — это всё, что о ней известно, и
    переставлять её можно свободно. Как только за ней записан час, позиция и
    запись говорят разное, и переставленная строка вытесняет соседей
    неизвестно куда. Двигается всё, что ниже последней связи, — а это и есть
    будущее, ради которого перетаскивание заведено.
    """

    def setUp(self):
        super().setUp()
        self.trig_lessons = list(self.trig.children.order_by("position"))
        self.slot = self.add_slot(MONDAY)
        self.slot.lesson = self.trig_lessons[0]
        self.slot.save(update_fields=["lesson"])

    def test_stepping_a_taught_lesson_is_refused(self):
        response = self.client.post(
            reverse("plannode-move", args=[self.trig_lessons[0].pk]),
            {"direction": "down"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "plan_lesson_taught")

    def test_dragging_a_taught_lesson_is_refused(self):
        response = self.client.post(
            reverse("plannode-move-to", args=[self.trig_lessons[0].pk]),
            {"parent": None, "position": 0},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "plan_lesson_taught")

    def test_the_answer_names_the_lesson_and_the_day(self):
        body = self.client.post(
            reverse("plannode-move", args=[self.trig_lessons[0].pk]),
            {"direction": "down"},
            format="json",
        ).json()

        self.assertEqual(body["params"]["title"], self.trig_lessons[0].title)
        self.assertEqual(body["params"]["date"], str(MONDAY))

    def test_a_section_holding_a_taught_lesson_stays_too(self):
        """Перенос темы двигает все её уроки, включая проведённый."""
        response = self.client.post(
            reverse("plansection-move", args=[self.trig.pk]),
            {"direction": "down"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "plan_lesson_taught")

    def test_everything_below_still_moves(self):
        untouched = self.trig_lessons[1]

        response = self.client.post(
            reverse("plannode-move", args=[untouched.pk]),
            {"direction": "down"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["moved"])

    def test_a_taught_row_is_still_renamed_freely(self):
        """Запрет про место, а не про содержание: переименование свободно."""
        response = self.client.patch(
            reverse("plannode-detail", args=[self.trig_lessons[0].pk]),
            {"title": "Синус суммы, вторая попытка"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)

    def test_the_link_dies_with_the_row_and_frees_it(self):
        """Строку удалили — час остался, связь ушла, соседи снова свободны."""
        self.trig_lessons[0].delete()
        self.slot.refresh_from_db()

        self.assertIsNone(self.slot.lesson_id)
        self.assertEqual(
            self.client.post(
                reverse("plannode-move", args=[self.trig_lessons[1].pk]),
                {"direction": "up"},
                format="json",
            ).status_code,
            200,
        )


class OneHourPerLessonTests(LayoutApiTestCase):
    """
    Одна строка плана — ровно одно занятие, и это ограничение базы.

    Не успели за урок — в план дописывается строка; успели две темы разом —
    план правится слиянием. Второй час на ту же строку выражал бы то, чего в
    этой модели не бывает, поэтому связь `OneToOne`.
    """

    def test_two_hours_cannot_claim_the_same_lesson(self):
        from django.db import IntegrityError, transaction

        lesson = self.trig.children.order_by("position").first()
        first = self.add_slot(MONDAY, number=1)
        second = self.add_slot(MONDAY + timedelta(days=1), number=1)

        first.lesson = lesson
        first.save(update_fields=["lesson"])
        second.lesson = lesson

        with self.assertRaises(IntegrityError), transaction.atomic():
            second.save(update_fields=["lesson"])


class ReserveSinceTests(LayoutApiTestCase):
    """
    Почему резерв стал таким: что сделало расписание, что сделала программа.

    Резерв — единственное число приложения, живущее сразу на обеих осях, и
    ровно поэтому его падение само по себе ничего не объясняет. Ответ
    становится точным, как только известна точка отсчёта, — её и снимает
    `PlanBaseline.slots_total` в момент утверждения.
    """

    def setUp(self):
        super().setUp()
        self.fill_slots(10)  # семь уроков плана, десять часов
        self.baseline = self.approve_plan()

    def approve_plan(self):
        from plans import approval

        from .models import PlanBaseline

        baseline = PlanBaseline.objects.create(
            course=self.course, submitted_by=self.user
        )
        return approval.approve(baseline, self.user)

    def reserve(self):
        from django.utils import timezone
        from plans import progress

        rows = progress.rows_for(progress.own_courses(self.user), timezone.localdate())
        row = next(item for item in rows if item["id"] == self.course.pk)
        return row["baseline"]["reserve"]

    def test_the_starting_point_is_taken_at_approval(self):
        self.assertEqual(self.baseline.slots_total, 10)
        self.assertEqual(self.reserve(), {
            "then": 3, "now": 3, "schedule": 0, "plan": 0,
        })

    def test_a_lost_day_is_charged_to_the_schedule(self):
        slot = Slot.objects.filter(course=self.course).order_by("date").first()
        slot.is_cancelled = True
        slot.save(update_fields=["is_cancelled"])

        self.assertEqual(
            self.reserve(), {"then": 3, "now": 2, "schedule": -1, "plan": 0}
        )

    def test_a_grown_plan_is_charged_to_the_programme(self):
        """«Не успели» — это дописанная строка, и резерв съедает она."""
        self.client.post(
            reverse("plannode-list"),
            {"course": self.course.pk, "title": "Продолжение"},
            format="json",
        )

        self.assertEqual(
            self.reserve(), {"then": 3, "now": 2, "schedule": 0, "plan": 1}
        )

    def test_the_two_halves_add_up_exactly(self):
        """Это тождество, а не оценка: `сейчас = тогда + часы − уроки`."""
        self.add_slot(MONDAY + timedelta(days=20), number=3, is_extra=True)
        self.client.post(
            reverse("plannode-list"),
            {"course": self.course.pk, "title": "Продолжение"},
            format="json",
        )

        numbers = self.reserve()

        self.assertEqual(
            numbers["now"],
            numbers["then"] + numbers["schedule"] - numbers["plan"],
        )

    def test_without_an_approved_baseline_there_is_nothing_to_decompose(self):
        from .models import PlanBaseline

        PlanBaseline.objects.all().delete()

        from django.utils import timezone
        from plans import progress

        rows = progress.rows_for(progress.own_courses(self.user), timezone.localdate())
        row = next(item for item in rows if item["id"] == self.course.pk)

        self.assertIsNone(row["baseline"])
