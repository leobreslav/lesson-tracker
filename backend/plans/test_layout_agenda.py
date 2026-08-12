"""Темы уроков для сводного расписания: раскладка сразу по всем классам."""

from datetime import timedelta

from django.urls import reverse
from schedule.models import Course, LessonSlot

from .models import PlanNode
from .test_layout import MONDAY, LayoutApiTestCase


class LayoutAgendaTests(LayoutApiTestCase):
    def agenda(self, start=None, end=None, **extra):
        params = {
            "start": (start or MONDAY).isoformat(),
            "end": (end or MONDAY + timedelta(days=13)).isoformat(),
            **extra,
        }
        return self.client.get(reverse("plannode-layout-agenda"), params)

    def titles(self, response=None):
        data = (response or self.agenda()).json()["slots"]
        return {int(key): value["title"] for key, value in data.items()}

    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.agenda().status_code, 401)

    def test_period_is_required(self):
        response = self.client.get(reverse("plannode-layout-agenda"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "period_required")

    def test_reversed_period_is_rejected(self):
        response = self.agenda(start=MONDAY + timedelta(days=5), end=MONDAY)

        self.assertEqual(response.status_code, 400)

    def test_maps_slots_to_plan_lessons(self):
        created = self.fill_slots(3)

        payload = self.agenda().json()["slots"]

        self.assertEqual(
            [payload[str(slot.pk)]["title"] for slot in created],
            ["Синус суммы", "Косинус суммы", "Понятие вектора"],
        )
        self.assertEqual(
            payload[str(created[0].pk)]["section_title"], "Тригонометрия"
        )
        self.assertEqual(
            payload[str(created[0].pk)]["plan_row_id"], self.node("Синус суммы").pk
        )

    def test_lesson_outside_a_section_has_no_section_title(self):
        created = self.fill_slots(5)

        payload = self.agenda().json()["slots"]

        self.assertEqual(payload[str(created[4].pk)]["title"], "Повторение")
        self.assertIsNone(payload[str(created[4].pk)]["section_title"])

    def test_slot_without_a_plan_lesson_is_absent(self):
        """Слотов больше, чем уроков: лишние в ответ не попадают вовсе."""
        created = self.fill_slots(9)  # уроков плана всего семь

        payload = self.agenda().json()["slots"]

        self.assertEqual(len(payload), 7)
        self.assertNotIn(str(created[7].pk), payload)
        self.assertNotIn(str(created[8].pk), payload)

    def test_cancelling_a_slot_shifts_the_topics(self):
        created = self.fill_slots(4)
        before = self.titles()

        self.client.patch(
            reverse("lessonslot-detail", args=[created[1].pk]),
            {"is_cancelled": True, "reason": "Болезнь"},
            format="json",
        )

        after = self.titles()
        self.assertEqual(before[created[1].pk], "Косинус суммы")
        # отменённый слот выпал из раскладки, темы подтянулись
        self.assertNotIn(created[1].pk, after)
        self.assertEqual(after[created[2].pk], "Косинус суммы")
        self.assertEqual(after[created[3].pk], "Понятие вектора")

    def test_period_cuts_the_answer_but_not_the_matching(self):
        created = self.fill_slots(5)

        payload = self.agenda(
            start=MONDAY + timedelta(days=3), end=MONDAY + timedelta(days=4)
        ).json()["slots"]

        self.assertEqual(len(payload), 2)
        # нумерация не поехала: четвёртый слот по-прежнему четвёртый урок
        self.assertEqual(payload[str(created[3].pk)]["title"], "Сложение векторов")

    def test_covers_every_class_at_once(self):
        second = Course.objects.create(
            school=self.school, year=self.course.year, name="10А"
        )
        PlanNode.objects.create(
            teacher=self.user, course=second, parent=None, position=0, is_section=False,
            title="Своя тема",
        )
        mine = self.fill_slots(1)[0]
        other = LessonSlot.objects.create(
            teacher=self.user,
            year=second.year, course=second, date=MONDAY,
            lesson_number=2
        )

        payload = self.agenda().json()["slots"]

        self.assertEqual(payload[str(mine.pk)]["title"], "Синус суммы")
        self.assertEqual(payload[str(other.pk)]["title"], "Своя тема")

    def test_another_users_slots_are_invisible(self):
        PlanNode.objects.create(
            teacher=self.stranger, course=self.alien_class, parent=None, position=0,
            is_section=False, title="Чужой урок",
        )
        alien_slot = LessonSlot.objects.create(
            teacher=self.stranger,
            year=self.alien_class.year,
            course=self.alien_class,
            date=MONDAY,
            lesson_number=1,
        )
        self.fill_slots(1)

        payload = self.agenda().json()["slots"]

        self.assertNotIn(str(alien_slot.pk), payload)
        self.assertNotIn("Чужой урок", [item["title"] for item in payload.values()])

    def test_cancelled_slots_are_not_listed(self):
        created = self.fill_slots(2)
        created[0].is_cancelled = True
        created[0].save()

        payload = self.agenda().json()["slots"]

        self.assertNotIn(str(created[0].pk), payload)
        self.assertEqual(payload[str(created[1].pk)]["title"], "Синус суммы")
