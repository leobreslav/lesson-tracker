"""
Числа раскладки: три реализации, один набор ожиданий.

Одни и те же «слотов / уроков / резерв / не помещается / последний урок»
считаются в трёх местах — `layout_summary`, `course_progress` и
`planLayout.layoutTotals` на клиенте. Сегодня они согласны, и заметить, что
разошлись, было бы нечем: страница плана показывает своё число, «Состояние
курсов» — своё, и оба выглядят правдоподобно.

Поэтому случаи лежат в `mirrors/layout.json` и читаются с двух сторон.
Здесь сверяются обе серверные реализации плюс лента слотов, которую клиент
получает на вход; клиентскую половину гоняет
`frontend/tests/planLayout.test.js` на этом же файле.

Сведение трёх расчётов в один — отдельная работа. Сначала пусть тесты
стерегут: без них любое сведение — это правка вслепую.
"""

import json
from datetime import date
from pathlib import Path
from unittest import mock

from django.urls import reverse
from schedule.models import Lesson

from .models import PlanNode
from .test_layout import PlanTestCase

CASES = json.loads(
    (
        Path(__file__).resolve().parent.parent.parent / "mirrors" / "layout.json"
    ).read_text(encoding="utf-8")
)

TODAY = date.fromisoformat(CASES["today"])


class LayoutNumbersMirrorTests(PlanTestCase):
    """Каждый случай общего файла — против трёх ответов сервера сразу."""

    def build(self, case):
        """План и слоты случая. У курса уже есть год из фикстуры."""
        PlanNode.objects.filter(course=self.course).delete()
        Lesson.objects.filter(course=self.course).delete()

        position = 0
        for block in case["plan"]:
            parent = None
            if block.get("section"):
                parent = PlanNode.objects.create(
                    course=self.course,
                    title=block["section"],
                    is_section=True,
                    position=position,
                )
                position += 1

            for index, title in enumerate(block["lessons"]):
                PlanNode.objects.create(
                    course=self.course,
                    parent=parent,
                    title=title,
                    position=index if parent else position,
                )
                if parent is None:
                    position += 1

        for number, slot in enumerate(case["slots"], start=1):
            # «previous» — уроки прежнего ведущего: слот личный, а раскладка
            # считает по курсу, и это ровно то, что случай проверяет
            owner = self.colleague if slot.get("teacher") == "previous" else self.user
            Lesson.objects.create(
                year=self.course.year,
                course=self.course,
                date=date.fromisoformat(slot["date"]),
                # номер свой у каждого слота: пара (дата, номер) уникальна, а
                # даты в случаях повторяются
                lesson_number=(number - 1) % 10 + 1,
                is_cancelled=slot.get("cancelled", False),
                is_extra=slot.get("extra", False),
            )

    def test_every_case_agrees_across_all_three(self):
        self.assertGreater(len(CASES["cases"]), 5, "случаев подозрительно мало")

        for case in CASES["cases"]:
            with self.subTest(case["name"]):
                self.build(case)
                why = f"{case['name']}: {case['why']}"
                expected = case["expected"]

                # `today` заморожен: «проведено» и «осталось» считаются по датам,
                # и без заморозки случай протух бы вместе с сентябрём
                with mock.patch(
                    "plans.views.timezone.localdate", return_value=TODAY
                ):
                    summary = self.client.get(
                        reverse("plannode-layout-summary"), {"course": self.course.pk}
                    ).json()
                    progress = next(
                        row
                        for row in self.client.get(reverse("plannode-progress")).json()[
                            "courses"
                        ]
                        if row["id"] == self.course.pk
                    )
                    ribbon = self.client.get(
                        reverse("plannode-layout-slots"), {"course": self.course.pk}
                    ).json()["slots"]

                self.check_summary(summary, expected, why)
                self.check_progress(progress, expected, why)
                self.check_ribbon(ribbon, case, why)

    def check_summary(self, summary, expected, why):
        self.assertEqual(
            {
                key: summary[key]
                for key in (
                    "slots_total",
                    "lessons_total",
                    "balance",
                    "last_lesson_date",
                    "past_lessons",
                    "remaining_lessons",
                )
            },
            {
                key: expected[key]
                for key in (
                    "slots_total",
                    "lessons_total",
                    "balance",
                    "last_lesson_date",
                    "past_lessons",
                    "remaining_lessons",
                )
            },
            f"/layout/summary/ — {why}",
        )

    def check_progress(self, progress, expected, why):
        """
        У «Состояния курсов» те же числа под другими именами.

        `reserve` — это `balance`, `done` — «проведено». Имена разные
        исторически, значения расходиться не должны.
        """
        self.assertEqual(
            {
                "slots_total": progress["slots_total"],
                "lessons_total": progress["lessons_total"],
                "balance": progress["reserve"],
                "missing": progress["missing"],
                "last_lesson_date": progress["last_lesson_date"],
                "past_lessons": progress["done"],
                "remaining_lessons": progress["lessons_total"] - progress["done"],
            },
            {
                key: expected[key]
                for key in (
                    "slots_total",
                    "lessons_total",
                    "balance",
                    "missing",
                    "last_lesson_date",
                    "past_lessons",
                    "remaining_lessons",
                )
            },
            f"/progress/ — {why}",
        )

    def check_ribbon(self, ribbon, case, why):
        """
        Лента — вход клиентской половины: на ней он считает свои числа.

        Отменённые слоты в неё не попадают, порядок по дате — если разойдётся
        это, разойдётся и всё, что клиент из неё выведет.
        """
        self.assertEqual(
            [row["date"] for row in ribbon],
            [slot["date"] for slot in case["slots"] if not slot.get("cancelled")],
            f"лента — {why}",
        )
        self.assertEqual(len(ribbon), case["expected"]["slots_total"], why)
