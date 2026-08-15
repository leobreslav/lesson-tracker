"""
Расписание школы — то же расписание курсов, только целиком.

Отдельной таблицы (`MasterSlot`) больше нет: после того как `Lesson`
переехал на курс, у неё не осталось ни одного своего поля, а ключ совпадал
буква в букву. Здесь проверяется то, что от неё осталось как поведение:
администратор правит любой курс школы, учитель — только свои, а видят
расписание все.

Про матрицу доступа отдельно (`schools/test_access.py`); тут — поведение,
которого у личного расписания раньше не было.
"""

from datetime import date, timedelta

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import (
    MONDAY,
    SchoolTestMixin,
    assign,
    make_course,
    make_slot,
    make_year,
)

from .models import Lesson

TUESDAY = MONDAY + timedelta(days=1)


class SchoolScheduleTestCase(SchoolTestMixin, APITestCase):
    """Два курса под одним учителем и один — под коллегой."""

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.algebra = make_course(self.school, self.year, "9Б Алгебра")
        self.geometry = make_course(self.school, self.year, "9Б Геометрия")
        self.theirs = make_course(self.school, self.year, "10А Алгебра")
        assign(self.user, self.algebra)
        assign(self.user, self.geometry)
        assign(self.colleague, self.theirs)

    def post(self, **fields):
        payload = {
            "course": self.algebra.pk,
            "date": MONDAY.isoformat(),
            "lesson_number": 1,
            **fields,
        }
        return self.client.post(reverse("lesson-list"), payload, format="json")

    def listing(self, **params):
        return self.client.get(reverse("lesson-list"), params)


class AdminWritesTests(SchoolScheduleTestCase):
    def test_an_admin_lays_out_a_lesson_in_somebody_elses_course(self):
        """Расписание школы составляет администратор — значит, любое."""
        self.sign_in(self.admin)

        response = self.post(course=self.theirs.pk)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Lesson.objects.get().course, self.theirs)

    def test_a_course_nobody_leads_can_still_be_scheduled(self):
        """«Нагрузку ещё не раздали» — обычное состояние, а не ошибка."""
        spare = make_course(self.school, self.year, "11В")
        self.sign_in(self.admin)

        response = self.post(course=spare.pk)

        self.assertEqual(response.status_code, 201, response.content)

    def test_a_teacher_cannot_touch_a_course_that_is_not_theirs(self):
        response = self.post(course=self.theirs.pk)

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["code"], "not_course_teacher")

    def test_a_teacher_edits_their_own_course_fully(self):
        slot = make_slot(self.user, self.algebra)

        response = self.client.patch(
            reverse("lesson-detail", args=[slot.pk]),
            {"is_cancelled": True, "reason": "Болезнь"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)

    def test_an_admin_may_fix_a_teachers_week(self):
        """Раньше сломанную неделю чинить было нечем: слоты видел только он."""
        slot = make_slot(self.colleague, self.theirs)
        self.sign_in(self.admin)

        response = self.client.delete(reverse("lesson-detail", args=[slot.pk]))

        self.assertEqual(response.status_code, 204, response.content)


class ClashTests(SchoolScheduleTestCase):
    def test_one_teacher_cannot_stand_in_two_places(self):
        """Учитель ищется через назначение: у слота его нет."""
        make_slot(self.user, self.algebra, MONDAY, 1)
        self.sign_in(self.admin)

        response = self.post(course=self.geometry.pk, lesson_number=1)

        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual(body["code"], "slot_number_taken")
        self.assertEqual(body["params"]["class_name"], "9Б Алгебра")

    def test_a_course_nobody_leads_clashes_with_nobody(self):
        spare = make_course(self.school, self.year, "11Г")
        make_slot(self.user, self.algebra, MONDAY, 1)
        self.sign_in(self.admin)

        response = self.post(course=spare.pk, lesson_number=1)

        self.assertEqual(response.status_code, 201, response.content)

    def test_a_course_cannot_be_booked_twice_that_hour(self):
        make_slot(self.user, self.algebra, MONDAY, 1)

        response = self.post(lesson_number=1)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("non_field_errors", response.json())

    def test_a_course_of_another_school_is_refused(self):
        alien = make_course(self.alien_school, name="Чужой")
        self.sign_in(self.admin)

        response = self.post(course=alien.pk)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("course", response.json())

    def test_a_date_outside_the_year_is_refused(self):
        response = self.post(date=date(2030, 9, 7).isoformat())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "slot_outside_year")


class ScopeTests(SchoolScheduleTestCase):
    """Список по умолчанию свой, `?scope=school` — школьный."""

    def setUp(self):
        super().setUp()
        self.mine = make_slot(self.user, self.algebra, MONDAY, 1)
        self.theirs_slot = make_slot(self.colleague, self.theirs, MONDAY, 2)

    def test_by_default_the_list_is_my_own_schedule(self):
        self.assertEqual(
            [row["id"] for row in self.listing().json()], [self.mine.pk]
        )

    def test_the_school_scope_shows_everything(self):
        ids = {row["id"] for row in self.listing(scope="school").json()}

        self.assertEqual(ids, {self.mine.pk, self.theirs_slot.pk})

    def test_a_teacher_may_read_the_whole_school_too(self):
        """Расписание общее: по нему живут все, и прячут его только от чужой школы."""
        self.sign_in(self.colleague)

        ids = {row["id"] for row in self.listing(scope="school").json()}

        self.assertEqual(ids, {self.mine.pk, self.theirs_slot.pk})

    def test_filter_by_teacher_goes_through_the_assignment(self):
        rows = self.listing(scope="school", teacher=self.colleague.pk).json()

        self.assertEqual([row["id"] for row in rows], [self.theirs_slot.pk])

    def test_filter_by_course(self):
        rows = self.listing(scope="school", course=self.theirs.pk).json()

        self.assertEqual([row["id"] for row in rows], [self.theirs_slot.pk])

    def test_garbage_filters_return_nothing_rather_than_crash(self):
        self.assertEqual(self.listing(scope="school", teacher="нет").json(), [])
        self.assertEqual(self.listing(scope="school", year="нет").json(), [])

    def test_another_school_sees_none_of_it(self):
        self.sign_in(self.alien_admin)

        self.assertEqual(self.listing(scope="school").json(), [])


class SummaryTests(SchoolScheduleTestCase):
    def test_it_counts_what_is_laid_out_and_what_has_nobody(self):
        spare = make_course(self.school, self.year, "11Д")
        make_slot(self.user, self.algebra, MONDAY, 1)
        make_slot(self.colleague, self.theirs, MONDAY, 2)
        Lesson.objects.create(
            year=self.year, course=spare, date=MONDAY, lesson_number=3
        )

        body = self.client.get(reverse("lesson-summary")).json()

        self.assertEqual(body["total"], 3)
        self.assertEqual(body["unassigned"], 1)
        self.assertEqual(body["teachers"], 2)


class BulkTests(SchoolScheduleTestCase):
    def setUp(self):
        super().setUp()
        make_slot(self.user, self.algebra, MONDAY, 1)
        make_slot(self.colleague, self.theirs, MONDAY, 2)

    def clear(self, course, **params):
        return self.client.delete(
            reverse("lesson-bulk")
            + f"?course={course.pk}&start={MONDAY}&end={MONDAY}"
            + "".join(f"&{key}={value}" for key, value in params.items())
        )

    def test_an_admin_clears_any_course(self):
        self.sign_in(self.admin)

        response = self.clear(self.theirs)

        self.assertEqual(response.json()["deleted"], 1)

    def test_a_teacher_cannot_clear_somebody_elses_course(self):
        response = self.clear(self.theirs)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Lesson.objects.count(), 2)


class AdminCopyTests(SchoolScheduleTestCase):
    """Раскатать неделю на год — то, ради чего школьное расписание и было."""

    def copy(self, course=None, **overrides):
        payload = {
            "source_start": MONDAY.isoformat(),
            "source_end": (MONDAY + timedelta(days=6)).isoformat(),
            "target_start": (MONDAY + timedelta(days=7)).isoformat(),
            "target_end": (MONDAY + timedelta(days=13)).isoformat(),
            **overrides,
        }
        if course is not None:
            payload["course_id"] = course.pk
        return self.client.post(reverse("lesson-copy"), payload, format="json")

    def test_an_admin_repeats_a_week_of_a_course_they_do_not_teach(self):
        make_slot(self.colleague, self.theirs, MONDAY, 2)
        self.sign_in(self.admin)

        response = self.copy(self.theirs)

        self.assertEqual(response.json()["created"], 1)
        self.assertEqual(
            Lesson.objects.filter(course=self.theirs).count(), 2
        )

    def test_a_teacher_cannot_copy_somebody_elses_course(self):
        make_slot(self.colleague, self.theirs, MONDAY, 2)

        response = self.copy(self.theirs)

        self.assertEqual(response.status_code, 403)

    def test_replace_leaves_a_cancellation_of_the_teacher_alone(self):
        """
        Массовая правка не трогает ручную пометку — и у администратора тоже.

        Он раскатывает сетку на весь год; без этого правила «перекопировать»
        стёрло бы чужие отмены вместе с причинами, и восстановить их было бы
        неоткуда.
        """
        make_slot(self.colleague, self.theirs, MONDAY, 2)
        kept = make_slot(
            self.colleague,
            self.theirs,
            MONDAY + timedelta(days=7),
            5,
            is_cancelled=True,
            reason="Болезнь",
        )
        self.sign_in(self.admin)

        self.copy(self.theirs, mode="replace")

        self.assertTrue(Lesson.objects.filter(pk=kept.pk).exists())
