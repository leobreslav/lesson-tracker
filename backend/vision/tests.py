"""
Потолок расхода и журнал трат.

Проверяется не арифметика — она в две строки, — а три решения, каждое из
которых легко откатить назад по недосмотру: ноль значит «нельзя», потолок
считается за календарный месяц, и журнал показывает учителю **его** строки, а
администратору все.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin

from . import services
from .models import AiSpend
from .prices import HAIKU, SONNET, cost_micros


class PriceTests(SchoolTestMixin, APITestCase):
    def test_the_cost_is_counted_in_millionths(self):
        # 1000 входных по $1/M и 100 выходных по $5/M
        self.assertEqual(cost_micros(HAIKU, 1000, 100), 1500)

    def test_an_unknown_model_is_refused(self):
        """Неизвестная цена — это тихо снятый потолок, поэтому отказ."""
        with self.assertRaises(ValueError):
            cost_micros("claude-something-new", 10, 10)


class BudgetTests(SchoolTestMixin, APITestCase):
    def spend(self, micros, *, user=None, when=None):
        row = AiSpend.objects.create(
            school=self.school,
            user=user or self.user,
            purpose=AiSpend.SCAN_HEADER,
            model=HAIKU,
            cost_micros=micros,
        )
        if when:
            AiSpend.objects.filter(pk=row.pk).update(created_at=when)
        return row

    def test_zero_means_no(self):
        """Школа без выставленного лимита не тратит: ноль это «нельзя»."""
        self.school.ai_month_limit_cents = 0
        self.school.save()

        with self.assertRaises(Exception) as caught:
            services.check_budget(self.school)
        self.assertEqual(caught.exception.detail["code"], "ai_budget_exceeded")

    def test_last_month_does_not_count(self):
        """Граница — календарный месяц, и кончается он сам."""
        self.school.ai_month_limit_cents = 1
        self.school.save()
        self.spend(1_000_000, when=timezone.now() - timedelta(days=40))

        self.assertEqual(services.spent_this_month(self.school), 0)
        services.check_budget(self.school)  # не поднимает

    def test_spending_up_to_the_limit_closes_the_door(self):
        self.school.ai_month_limit_cents = 1  # один цент = 10 000 микродолларов
        self.school.save()
        self.spend(10_000)

        with self.assertRaises(Exception):
            services.check_budget(self.school)


class BudgetApiTests(SchoolTestMixin, APITestCase):
    def test_the_administrator_sets_the_limit(self):
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            reverse("ai-budget"), {"limit_cents": 2500}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.ai_month_limit_cents, 2500)

    def test_a_teacher_only_looks(self):
        self.client.force_authenticate(self.user)

        self.assertEqual(self.client.get(reverse("ai-budget")).status_code, 200)
        refused = self.client.patch(
            reverse("ai-budget"), {"limit_cents": 999999}, format="json"
        )
        self.assertEqual(refused.json()["code"], "school_admin_required")

    def test_a_negative_limit_is_refused(self):
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            reverse("ai-budget"), {"limit_cents": -5}, format="json"
        )

        self.assertEqual(response.json()["code"], "ai_limit_negative")


class SpendLogTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        for who in (self.user, self.colleague):
            AiSpend.objects.create(
                school=self.school,
                user=who,
                purpose=AiSpend.SCAN_HEADER,
                model=SONNET,
                cost_micros=1234,
            )

    def test_the_teacher_sees_only_their_own(self):
        """Кто сколько потратил — вопрос администратора, а не коллеги."""
        self.client.force_authenticate(self.user)

        rows = self.client.get(reverse("ai-spend")).json()["rows"]

        self.assertEqual(len(rows), 1)

    def test_the_administrator_sees_the_whole_school(self):
        self.client.force_authenticate(self.admin)

        rows = self.client.get(reverse("ai-spend")).json()["rows"]

        self.assertEqual(len(rows), 2)

    def test_the_administrator_can_narrow_it_to_their_own(self):
        self.client.force_authenticate(self.admin)

        rows = self.client.get(reverse("ai-spend"), {"mine": "true"}).json()["rows"]

        self.assertEqual(rows, [])
