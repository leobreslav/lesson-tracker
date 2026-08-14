"""
Who teaches which course, and the school's list of year groups.

Both are new tables answering questions that used to have no home. «What do
I teach» lived inside the school timetable, so a teacher without one saw
nothing anywhere; «which year group is this» was a number on the course, so
two schools could not spell it differently.

The assignment is written from two ends — the teacher's card and the
course's card — and the tests below check that both ends land in the same
row, because that is the whole reason for having one table instead of two
lists.
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from plans.models import PlanNode
from schedule.serializers import full_name
from rest_framework.test import APITestCase
from schools.testing import (
    MONDAY,
    SchoolTestMixin,
    assign,
    make_course,
    make_grade,
    make_node,
    make_slot,
    make_user,
    make_year,
)

from .models import Course, CourseAssignment, GradeLevel, LessonSlot


class AssignmentTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.algebra = make_course(self.school, self.year, "9Б Алгебра")
        self.geometry = make_course(self.school, self.year, "9Б Геометрия")

    def as_admin(self):
        return self.sign_in(self.admin)

    def post_assignment(self, course, teacher):
        return self.client.post(
            reverse("courseassignment-list"),
            {"course": course.pk, "teacher": teacher.pk},
            format="json",
        )

    def my_courses(self, **params):
        return self.client.get(reverse("course-list"), params).json()


# --- what a teacher sees --------------------------------------------------------


class VisibleCoursesTests(AssignmentTestCase):
    def test_a_teacher_sees_the_courses_they_are_assigned_to(self):
        assign(self.user, self.algebra)

        names = [item["name"] for item in self.my_courses()]

        self.assertEqual(names, ["9Б Алгебра"])

    def test_an_unassigned_course_is_not_on_the_list(self):
        assign(self.user, self.algebra)

        ids = [item["id"] for item in self.my_courses()]

        self.assertNotIn(self.geometry.pk, ids)

    def test_the_whole_school_is_one_parameter_away(self):
        """The «School» section manages courses nobody has been given yet."""
        names = [item["name"] for item in self.my_courses(scope="school")]

        self.assertEqual(names, ["9Б Алгебра", "9Б Геометрия"])

    def test_a_lesson_cannot_be_created_in_a_course_nobody_gave_you(self):
        """
        Курс школы виден всем — расписание общее, — поэтому отказ именной:
        «это не ваш курс», а не «нет такого курса».
        """
        response = self.client.post(
            reverse("lessonslot-list"),
            {"course": self.algebra.pk, "date": MONDAY, "lesson_number": 1},
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["code"], "not_course_teacher")

    def test_an_unassigned_course_leaves_the_list_with_its_work_intact(self):
        """
        Курс мой ровно потому, что мне его поручили.

        Условие было длиннее — «плюс те, где у меня уже есть уроки», — и
        защищало от того, что снятие назначения спрячет от человека его
        собственную работу. Теперь прятать нечего: расписание, план и работы
        принадлежат курсу, личного внутри него не осталось, и работа целиком
        достаётся следующему ведущему.
        """
        slot = make_slot(self.user, self.algebra)
        CourseAssignment.objects.filter(
            course=self.algebra, teacher=self.user
        ).delete()

        ids = [item["id"] for item in self.my_courses()]

        self.assertNotIn(self.algebra.pk, ids)
        self.assertTrue(LessonSlot.objects.filter(pk=slot.pk).exists())


# --- writing the link from either side -------------------------------------------


class TwoSidesTests(AssignmentTestCase):
    def test_assigning_from_the_course_card_and_from_the_teacher_card_agree(self):
        self.as_admin()

        from_course = self.post_assignment(self.algebra, self.user)
        from_teacher = self.post_assignment(self.geometry, self.user)

        self.assertEqual(from_course.status_code, 201, from_course.content)
        self.assertEqual(from_teacher.status_code, 201, from_teacher.content)

        # the course card reads it off the course...
        courses = {
            item["name"]: [teacher["id"] for teacher in item["teachers"]]
            for item in self.client.get(
                reverse("course-list"), {"scope": "school"}
            ).json()
        }
        self.assertEqual(courses["9Б Алгебра"], [self.user.pk])
        self.assertEqual(courses["9Б Геометрия"], [self.user.pk])

        # ...and the teacher card reads the same rows off the person
        member = self.client.get(reverse("member-detail", args=[self.user.pk])).json()
        self.assertEqual(
            sorted(course["name"] for course in member["courses"]),
            ["9Б Алгебра", "9Б Геометрия"],
        )

    def test_a_course_has_one_lead_teacher(self):
        """Ассистенты бывают, а ведущий один — и план у курса поэтому один."""
        self.as_admin()
        self.post_assignment(self.algebra, self.user)

        refused = self.post_assignment(self.algebra, self.colleague)

        self.assertEqual(refused.status_code, 400)
        body = refused.json()
        self.assertEqual(body["code"], "course_teacher_taken")
        # называем того, кто там стоит: «занято» без имени бесполезно
        self.assertEqual(body["params"]["teacher"], full_name(self.user))
        self.assertEqual(self.algebra.assignments.count(), 1)

    def test_the_same_pair_cannot_be_written_twice(self):
        self.as_admin()
        self.post_assignment(self.algebra, self.user)

        again = self.post_assignment(self.algebra, self.user)

        self.assertEqual(again.status_code, 400)

    def test_a_teacher_cannot_assign_anybody(self):
        response = self.post_assignment(self.algebra, self.user)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "school_admin_required")

    def test_another_schools_course_cannot_be_named(self):
        self.as_admin()
        alien = make_course(self.alien_school, name="9А")

        response = self.post_assignment(alien, self.user)

        self.assertEqual(response.status_code, 400)

    def test_another_schools_teacher_cannot_be_named(self):
        self.as_admin()

        response = self.post_assignment(self.algebra, self.stranger)

        self.assertEqual(response.status_code, 400)

    def test_the_list_is_scoped_to_the_school(self):
        self.as_admin()
        alien_course = make_course(self.alien_school, name="9А")
        CourseAssignment.objects.create(course=alien_course, teacher=self.stranger)
        assign(self.user, self.algebra)

        rows = self.client.get(reverse("courseassignment-list")).json()

        self.assertEqual([row["course_name"] for row in rows], ["9Б Алгебра"])


# --- taking a course away ---------------------------------------------------------


class UnassignTests(AssignmentTestCase):
    def setUp(self):
        super().setUp()
        self.as_admin()
        self.link = assign(self.user, self.algebra)

    def unassign(self, **params):
        return self.client.delete(
            reverse("courseassignment-detail", args=[self.link.pk]),
            params,
        )

    def test_an_empty_assignment_goes_without_ceremony(self):
        response = self.unassign()

        self.assertEqual(response.status_code, 204)
        self.assertFalse(CourseAssignment.objects.filter(pk=self.link.pk).exists())

    def test_with_lessons_behind_it_the_first_attempt_is_refused(self):
        make_slot(self.user, self.algebra)

        response = self.client.delete(
            reverse("courseassignment-detail", args=[self.link.pk])
        )

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], "assignment_in_use")
        self.assertEqual(body["params"]["slots"], 1)
        self.assertTrue(CourseAssignment.objects.filter(pk=self.link.pk).exists())

    def test_the_confirmation_is_about_losing_sight_of_the_course(self):
        """
        Работа принадлежит курсу и не пропадает — а курс из списков уходит.

        Раньше подтверждение спрашивали про чужую работу; теперь спрашивать
        про неё нечего, и осталось единственное настоящее последствие:
        снятый перестаёт видеть курс вообще.
        """
        make_node(self.user, self.algebra, "Урок")
        # the fixture assigns as it writes, so read the row back
        self.link = CourseAssignment.objects.get(
            course=self.algebra, teacher=self.user
        )
        url = reverse("courseassignment-detail", args=[self.link.pk])

        refused = self.client.delete(url)
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["params"]["plan_rows"], 1)

        confirmed = self.client.delete(f"{url}?force=true")

        self.assertEqual(confirmed.status_code, 204, confirmed.content)
        self.assertFalse(CourseAssignment.objects.filter(pk=self.link.pk).exists())
        self.assertTrue(PlanNode.objects.filter(course=self.algebra).exists())

    def test_lessons_name_the_plan_that_stays(self):
        make_slot(self.user, self.algebra)
        make_node(self.user, self.algebra, "Урок")
        self.link = CourseAssignment.objects.get(
            course=self.algebra, teacher=self.user
        )

        response = self.client.delete(
            reverse("courseassignment-detail", args=[self.link.pk])
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["params"]["plan_rows"], 1)

    def test_forcing_it_removes_the_link_and_keeps_the_work(self):
        slot = make_slot(self.user, self.algebra)
        node = make_node(self.user, self.algebra, "Урок")
        self.link = CourseAssignment.objects.get(
            course=self.algebra, teacher=self.user
        )

        response = self.client.delete(
            f"{reverse('courseassignment-detail', args=[self.link.pk])}?force=true"
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(CourseAssignment.objects.filter(pk=self.link.pk).exists())
        self.assertTrue(type(slot).objects.filter(pk=slot.pk).exists())
        self.assertTrue(PlanNode.objects.filter(pk=node.pk).exists())


class GradeLevelTests(AssignmentTestCase):
    def test_the_number_of_queries_does_not_grow_with_the_rows(self):
        """
        Счётчик курсов — аннотация, а не `source="courses.count"`.

        Второе стоит запроса на строку, и это шаблон, который копируется в
        каждый следующий справочник: одиннадцать параллелей — одиннадцать
        лишних запросов ради одиннадцати чисел.
        """
        make_grade(self.school, level=1)

        with CaptureQueriesContext(connection) as one_row:
            self.client.get(reverse("gradelevel-list"))

        for level in range(2, 12):
            make_grade(self.school, level=level)

        with CaptureQueriesContext(connection) as eleven_rows:
            response = self.client.get(reverse("gradelevel-list"))

        self.assertEqual(len(response.json()), 11)
        self.assertEqual(
            len(eleven_rows),
            len(one_row),
            f"запросы растут со строками: {len(one_row)} против {len(eleven_rows)}",
        )

    def test_a_new_school_starts_with_none_of_them(self):
        """
        Eleven guessed rows were worse than an empty list.

        A school numbering its years 1..13, or naming them MYP, had to delete
        or rename most of what it never asked for. The empty state offers the
        two usual sets as one button each instead.
        """
        self.assertEqual(GradeLevel.objects.filter(school=self.school).count(), 0)

    def test_the_preset_button_fills_the_list(self):
        self.as_admin()

        response = self.client.post(
            reverse("gradelevel-preset"), {"through": 13}, format="json"
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["created"], 13)
        levels = GradeLevel.objects.filter(school=self.school)
        self.assertEqual([item.level for item in levels], list(range(1, 14)))
        self.assertEqual(levels.last().name, "Grade 13")

    def test_the_names_are_written_in_the_language_of_the_school(self):
        """
        Имя параллели — контент в базе, а не интерфейс.

        Записывается один раз и при смене языка не переписывается — то же
        правило, что у типовых каникул и четвертей. Русская школа получала
        «Grade 1» от кнопки, которая рядом заводит «1 четверть».
        """
        self.as_admin()
        self.admin.language = "ru"
        self.admin.save(update_fields=["language"])

        self.client.post(reverse("gradelevel-preset"), {"through": 2}, format="json")

        self.assertEqual(
            [item.name for item in GradeLevel.objects.filter(school=self.school)],
            ["1 класс", "2 класс"],
        )

    def test_the_preset_adds_only_what_is_missing(self):
        self.as_admin()
        ninth = make_grade(self.school, 9, "MYP 4")

        self.client.post(reverse("gradelevel-preset"), {"through": 11}, format="json")

        ninth.refresh_from_db()
        # the one that was already there kept its name
        self.assertEqual(ninth.name, "MYP 4")
        self.assertEqual(GradeLevel.objects.filter(school=self.school).count(), 11)

    def test_a_silly_preset_is_refused(self):
        self.as_admin()

        response = self.client.post(
            reverse("gradelevel-preset"), {"through": 99}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "grade_preset_invalid")

    def test_a_teacher_cannot_press_the_preset_button(self):
        response = self.client.post(
            reverse("gradelevel-preset"), {"through": 11}, format="json"
        )

        self.assertEqual(response.status_code, 403)

    def test_unused_levels_go_in_one_go(self):
        self.as_admin()
        self.client.post(reverse("gradelevel-preset"), {"through": 11}, format="json")
        self.algebra.grade = make_grade(self.school, 9)
        self.algebra.save(update_fields=["grade"])

        response = self.client.delete(reverse("gradelevel-delete-unused"))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["deleted"], 10)
        self.assertEqual(
            [item.level for item in GradeLevel.objects.filter(school=self.school)], [9]
        )

    def test_clearing_the_unused_ones_does_not_reach_another_school(self):
        self.as_admin()
        theirs = make_grade(self.alien_school, 5)

        self.client.delete(reverse("gradelevel-delete-unused"))

        self.assertTrue(GradeLevel.objects.filter(pk=theirs.pk).exists())

    def test_a_thirteenth_year_is_a_normal_number(self):
        """British and IB schools have thirteen; the old ceiling was wrong."""
        self.as_admin()

        response = self.client.post(
            reverse("gradelevel-list"), {"level": 13, "name": "Year 13"}, format="json"
        )

        self.assertEqual(response.status_code, 201, response.content)

    def test_zero_is_still_not_a_year_of_study(self):
        self.as_admin()

        response = self.client.post(
            reverse("gradelevel-list"), {"level": 0, "name": "Нулевой"}, format="json"
        )

        self.assertEqual(response.status_code, 400)

    def test_the_year_of_study_is_fixed_once_courses_use_it(self):
        self.as_admin()
        ninth = make_grade(self.school, 9, "MYP 4")
        self.algebra.grade = ninth
        self.algebra.save(update_fields=["grade"])

        response = self.client.patch(
            reverse("gradelevel-detail", args=[ninth.pk]), {"level": 4}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "grade_level_locked")
        ninth.refresh_from_db()
        self.assertEqual(ninth.level, 9)

    def test_an_empty_one_can_still_be_moved(self):
        """A typo in a year group nobody uses is just a typo."""
        self.as_admin()
        level = make_grade(self.school, 4, "Year 4")

        response = self.client.patch(
            reverse("gradelevel-detail", args=[level.pk]), {"level": 5}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.content)
        level.refresh_from_db()
        self.assertEqual(level.level, 5)

    def test_renaming_stays_free_whatever_uses_it(self):
        self.as_admin()
        ninth = make_grade(self.school, 9, "Grade 9")
        self.algebra.grade = ninth
        self.algebra.save(update_fields=["grade"])

        response = self.client.patch(
            reverse("gradelevel-detail", args=[ninth.pk]), {"name": "MYP 4"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)

    def test_an_administrator_renames_one(self):
        self.as_admin()
        ninth = make_grade(self.school, 9)

        response = self.client.patch(
            reverse("gradelevel-detail", args=[ninth.pk]),
            {"name": "MYP 4"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        ninth.refresh_from_db()
        self.assertEqual(ninth.name, "MYP 4")
        # the year of study did not move: that is what sorting runs on
        self.assertEqual(ninth.level, 9)

    def test_a_teacher_only_reads_the_list(self):
        response = self.client.post(
            reverse("gradelevel-list"), {"level": 12, "name": "Двенадцатый"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_another_schools_levels_are_invisible(self):
        alien = make_grade(self.alien_school, 9)

        listed = self.client.get(reverse("gradelevel-list")).json()

        self.assertNotIn(alien.pk, [item["id"] for item in listed])
        self.assertEqual(
            self.client.get(reverse("gradelevel-detail", args=[alien.pk])).status_code,
            404,
        )

    def test_two_levels_with_the_same_number_are_refused(self):
        self.as_admin()
        make_grade(self.school, 9)

        response = self.client.post(
            reverse("gradelevel-list"), {"level": 9, "name": "Ещё девятый"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_a_level_a_course_uses_cannot_be_deleted(self):
        self.as_admin()
        ninth = make_grade(self.school, 9)
        self.algebra.grade = ninth
        self.algebra.save(update_fields=["grade"])

        response = self.client.delete(reverse("gradelevel-detail", args=[ninth.pk]))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "grade_in_use")
        self.assertTrue(GradeLevel.objects.filter(pk=ninth.pk).exists())

    def test_an_unused_level_goes(self):
        self.as_admin()
        first = make_grade(self.school, 1)

        response = self.client.delete(reverse("gradelevel-detail", args=[first.pk]))

        self.assertEqual(response.status_code, 204)

    def test_courses_are_sorted_by_year_of_study_not_by_the_name(self):
        """
        «MYP 4» is the ninth year, «Grade 6» is the sixth. The sixth comes
        first — sorting on the label would put MYP 4 in front of it.
        """
        self.as_admin()
        sixth = make_grade(self.school, 6, "Grade 6")
        ninth = make_grade(self.school, 9, "MYP 4")
        self.algebra.grade = ninth
        self.algebra.save(update_fields=["grade"])
        self.geometry.grade = sixth
        self.geometry.save(update_fields=["grade"])

        names = [
            item["grade_name"]
            for item in self.client.get(
                reverse("course-list"), {"scope": "school"}
            ).json()
        ]

        self.assertEqual(names, ["Grade 6", "MYP 4"])


# --- subjects, the same shape ---------------------------------------------------------


class SubjectIsolationTests(AssignmentTestCase):
    def test_another_schools_subjects_are_invisible(self):
        from .models import Subject

        alien = Subject.objects.create(school=self.alien_school, name="Латынь")
        mine = Subject.objects.create(school=self.school, name="Алгебра")

        listed = self.client.get(reverse("subject-list")).json()

        self.assertEqual([item["id"] for item in listed], [mine.pk])
        self.assertEqual(
            self.client.get(reverse("subject-detail", args=[alien.pk])).status_code,
            404,
        )

    def test_a_subject_a_course_uses_cannot_be_deleted(self):
        from .models import Subject

        self.as_admin()
        subject = Subject.objects.create(school=self.school, name="Алгебра")
        self.algebra.subject = subject
        self.algebra.save(update_fields=["subject"])

        response = self.client.delete(reverse("subject-detail", args=[subject.pk]))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "subject_in_use")


class EnrolmentTests(SchoolTestMixin, APITestCase):
    """
    Состав курса: администратор записывает и снимает, ученик видит своё.

    Снятие не удаляет строку — она и есть право ученика видеть сделанное в
    курсе. Поэтому «снять» и «удалить» здесь разные слова, и второго нет.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        self.other = make_course(self.school, self.year, "9Б Геометрия")
        self.sign_in(self.admin)

    def enrol(self, student=None, course=None):
        return self.client.post(
            reverse("coursestudent-list"),
            {"course": (course or self.course).pk, "student": (student or self.student).pk},
            format="json",
        )

    def roster(self, course=None):
        return self.client.get(
            reverse("coursestudent-list"), {"course": (course or self.course).pk}
        ).json()

    def test_an_admin_enrols_a_student(self):
        response = self.enrol()

        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()["active"])
        self.assertEqual([row["student"] for row in self.roster()], [self.student.pk])

    def test_a_teacher_cannot_enrol(self):
        """Состав курса ведёт администратор — как и всё школьное."""
        self.sign_in(self.user)

        self.assertEqual(self.enrol().status_code, 403)

    def test_removing_keeps_the_row_and_the_history(self):
        row_id = self.enrol().json()["id"]

        response = self.client.delete(reverse("coursestudent-detail", args=[row_id]))

        self.assertEqual(response.status_code, 204)
        row = self.roster()[0]
        self.assertFalse(row["active"])
        self.assertIsNotNone(row["removed_at"])

    def test_enrolling_again_brings_the_removed_one_back(self):
        row_id = self.enrol().json()["id"]
        self.client.delete(reverse("coursestudent-detail", args=[row_id]))

        response = self.enrol()

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["id"], row_id)
        self.assertTrue(response.json()["active"])
        self.assertEqual(len(self.roster()), 1)

    def test_a_teacher_cannot_be_enrolled_as_a_student(self):
        response = self.enrol(student=self.colleague)

        self.assertEqual(response.status_code, 400, response.content)

    def test_a_student_of_another_school_is_not_offered(self):
        alien = make_user(self.alien_school, "alien-student@example.com", student=True)

        self.assertEqual(self.enrol(student=alien).status_code, 400)

    def test_the_student_sees_their_courses_split_in_two(self):
        """
        Снятый курс не исчезает, а уезжает вниз с пометкой: курс, пропавший
        без объяснения, читается как поломка.
        """
        self.enrol(course=self.course)
        removed = self.enrol(course=self.other).json()["id"]
        self.client.delete(reverse("coursestudent-detail", args=[removed]))

        self.sign_in(self.student)
        body = self.client.get(reverse("student-courses")).json()

        self.assertEqual(
            [(row["name"], row["active"]) for row in body["courses"]],
            [("9Б Алгебра", True), ("9Б Геометрия", False)],
        )

    def test_a_teacher_has_no_student_section(self):
        self.sign_in(self.user)

        response = self.client.get(reverse("student-courses"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "students_only")
