"""
Копирование периода: серверная половина общих случаев.

Случаи лежат в `mirrors/copy.json` и читаются с двух сторон — отсюда и из
`frontend/tests/scheduleLogic.test.js`. Смысл ровно в этом: предпросмотр на
клиенте считает своим кодом, и «похожие» тесты с двух сторон расхождение не
ловят — они пишутся порознь и проверяют то, что автор помнил в тот день.

Здесь проверяется **сервер целиком**, через эндпоинт: раскладка (`plan_copy`),
занятость (`place_copies`) и запросы вокруг них — вместе, потому что порознь
они правильные и в паре как раз и расходились.
"""

import json
from datetime import date
from pathlib import Path

from calendars.models import DayException, SchoolYear
from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin, assign, make_course

from .models import Course, Slot

# путь такой же, как из frontend/tests: ../../mirrors от каталога приложения
CASES = json.loads(
    (Path(__file__).resolve().parent.parent.parent / "mirrors" / "copy.json").read_text(
        encoding="utf-8"
    )
)


def day(iso: str) -> date:
    return date.fromisoformat(iso)


class CopyMirrorTests(SchoolTestMixin, APITestCase):
    """Каждый случай общего файла — отдельный подтест с его собственным «зачем»."""

    def setUp(self):
        super().setUp()
        self.sign_in(self.user)

    def build(self, case) -> dict[str, Course]:
        """Год, разметка и уроки случая. Курсы заводятся по мере упоминания."""
        spec = CASES["year"]
        year = SchoolYear.objects.create(
            school=self.school,
            name=spec["name"],
            start_date=day(spec["start_date"]),
            end_date=day(spec["end_date"]),
            weekend_days=spec["weekend_days"],
        )

        for vacation in case.get("vacations", ()):
            DayException.objects.create(
                year=year,
                start_date=day(vacation["start"]),
                end_date=day(vacation["end"]),
                kind=DayException.Kind.VACATION,
                title=vacation["title"],
            )

        courses: dict[str, Course] = {}
        for slot in case["slots"]:
            name = slot["course"]
            if name not in courses:
                courses[name] = make_course(self.school, year=year, name=name)
                assign(self.user, courses[name])

            Slot.objects.create(
                year=year,
                course=courses[name],
                date=day(slot["date"]),
                lesson_number=slot["number"],
                is_cancelled=slot.get("cancelled", False),
                is_extra=slot.get("extra", False),
            )

        # копируемый курс мог не встретиться среди уроков — случай про пустой
        # источник как раз такой
        target = case["copy"]
        if target not in courses:
            courses[target] = make_course(self.school, year=year, name=target)
            assign(self.user, courses[target])

        return courses

    def test_every_case_of_the_shared_file(self):
        self.assertGreater(len(CASES["cases"]), 10, "случаев подозрительно мало")

        for case in CASES["cases"]:
            with self.subTest(case["name"]):
                self.run_case(case)
                # каждый случай начинается с чистого листа: год, курсы и
                # уроки свои, иначе занятость перетекала бы между случаями
                Slot.objects.all().delete()
                Course.objects.all().delete()
                SchoolYear.objects.all().delete()

    def run_case(self, case):
        courses = self.build(case)
        expected = case["expected"]

        response = self.client.post(
            reverse("slot-copy"),
            {
                "course_id": courses[case["copy"]].pk,
                "source_start": case["source"]["start"],
                "source_end": case["source"]["end"],
                "target_start": case["target"]["start"],
                "target_end": case["target"]["end"],
                "mode": case["mode"],
                # шаг есть не у всех случаев: «каждую неделю» — умолчание
                "step": case.get("step", 1),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        why = f"{case['name']}: {case['why']}"

        self.assertEqual(body["created"], expected["created"], why)
        self.assertEqual(body["skipped"], expected["skipped"], why)

        if "deleted" in expected:
            self.assertEqual(body["deleted"], expected["deleted"], why)
        if "conflicts" in expected:
            self.assertEqual(len(body["conflicts"]), expected["conflicts"], why)

        # где именно встали уроки: числа сходятся и у неверной раскладки
        if "dates" in expected:
            created = (
                Slot.objects.filter(
                    course=courses[case["copy"]],
                    date__gte=day(case["target"]["start"]),
                    date__lte=day(case["target"]["end"]),
                )
                .order_by("date", "lesson_number")
                .values_list("date", "lesson_number")
            )
            self.assertEqual(
                [(str(item[0]), item[1]) for item in created],
                [tuple(pair) for pair in expected["dates"]],
                why,
            )
