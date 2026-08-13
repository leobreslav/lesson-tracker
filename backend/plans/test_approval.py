"""
Эталонный план и его утверждение методистом.

Смысл процедуры в двух свойствах, и почти каждый тест здесь про одно из
них. Первое: **снимок делается при отправке**, а не при утверждении —
методист видит то, что ему прислали. Второе: **состояние честное** — правка
плана отзывает поданный запрос, потому что утверждать то, чего уже нет,
нельзя.

Метрики расхождения считаются только от **утверждённого** эталона: пока
план не приняли, сравнивать не с чем.
"""

from django.urls import reverse
from schedule.models import CourseMethodist, Subject
from schools.testing import assign, make_course

from .models import PlanBaseline, PlanNode
from .tests import PlanTestCase


class ApprovalTestCase(PlanTestCase):
    """План из семи уроков, предмет у курса и методист по нему."""

    def setUp(self):
        super().setUp()
        self.trig, self.vectors, self.stereo = self.build_sample()
        self.algebra = Subject.objects.create(school=self.school, name="Алгебра")
        self.course.subject = self.algebra
        self.course.save(update_fields=["subject"])
        self.methodist = self.colleague
        assign(self.methodist, self.course)

    def make_methodist(self, person, course=None):
        return CourseMethodist.objects.create(
            course=course or self.course, user=person, assigned_by=self.admin
        )

    # --- запросы ---

    def submit(self, reviewer=None, course=None):
        body = {} if reviewer is None else {"reviewer": reviewer.pk}
        return self.client.post(
            f"{reverse('plannode-baseline-submit')}?course={(course or self.course).pk}",
            body,
            format="json",
        )

    def state(self, course=None):
        return self.client.get(
            reverse("plannode-baseline"), {"course": (course or self.course).pk}
        ).json()

    def queue(self):
        return self.client.get(reverse("planreview-list")).json()["reviews"]

    def approve(self, pk):
        return self.client.post(reverse("planreview-approve", args=[pk]))

    def send_back(self, pk, comment=""):
        return self.client.post(
            reverse("planreview-return", args=[pk]), {"comment": comment}, format="json"
        )

    def progress(self, course=None):
        rows = self.client.get(reverse("plannode-progress")).json()["courses"]
        return {row["name"]: row for row in rows}[(course or self.course).name]


class SubmitTests(ApprovalTestCase):
    def test_sending_again_does_not_pile_up_requests(self):
        """У одного плана один запрос: иначе очередь заполнится им же."""
        self.make_methodist(self.methodist)
        first = self.submit().json()["request"]

        self.add("Новый урок", parent=self.trig, position=9)
        again = self.submit().json()["request"]

        self.assertEqual(PlanBaseline.objects.count(), 1)
        self.assertEqual(again["id"], first["id"])
        self.assertGreater(again["submitted_at"], first["submitted_at"])

    def test_a_single_methodist_is_chosen_by_himself(self):
        self.make_methodist(self.methodist)

        response = self.submit()

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["request"]["status"], "pending")
        self.assertEqual(
            response.json()["request"]["reviewer"]["id"], self.methodist.pk
        )

    def test_with_several_methodists_the_teacher_picks_one(self):
        self.make_methodist(self.methodist)
        self.make_methodist(self.admin)

        refused = self.submit()

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "reviewer_required")
        self.assertEqual(len(self.state()["methodists"]), 2)

        response = self.submit(reviewer=self.admin)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["request"]["reviewer"]["id"], self.admin.pk)

    def test_without_a_methodist_the_refusal_explains_itself(self):
        """Молчаливое «не получилось» отправило бы искать ошибку у себя."""
        response = self.submit()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "no_methodist")
        # называем курс: методиста назначают на него, а не на предмет
        self.assertEqual(response.json()["params"]["subject"], self.course.name)

    def test_a_methodist_of_another_course_is_not_offered(self):
        other = make_course(self.school, year=self.course.year, name="9А")
        self.make_methodist(self.methodist, other)

        self.assertEqual(self.submit().json()["code"], "no_methodist")

    def test_a_methodist_of_another_school_is_not_offered(self):
        CourseMethodist.objects.create(
            course=self.alien_class, user=self.alien_admin
        )

        self.assertEqual(self.submit().json()["code"], "no_methodist")

    def test_a_pending_request_carries_no_snapshot_yet(self):
        """Копия снимается при утверждении: эталон — это то, что приняли."""
        self.make_methodist(self.methodist)

        self.submit()

        self.assertEqual(PlanBaseline.objects.get().rows.count(), 0)


class ReviewTests(ApprovalTestCase):
    def setUp(self):
        super().setUp()
        self.make_methodist(self.methodist)
        self.submit()
        self.baseline = PlanBaseline.objects.get()

    def test_the_methodist_sees_the_request(self):
        self.client.force_authenticate(self.methodist)

        queue = self.queue()

        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["teacher"]["id"], self.user.pk)
        self.assertEqual(queue[0]["course"]["name"], self.course.name)
        self.assertEqual(queue[0]["lessons"], 7)

    def test_the_request_opens_with_the_plan_and_the_numbers(self):
        """Методист смотрит живой план: правка отозвала бы запрос."""
        self.client.force_authenticate(self.methodist)

        body = self.client.get(
            reverse("planreview-detail", args=[self.baseline.pk])
        ).json()

        self.assertEqual(len(body["rows"]), 10)
        self.assertEqual(body["rows"][0]["title"], "Тригонометрия")
        self.assertTrue(body["rows"][0]["is_section"])
        self.assertEqual(body["slots_total"], 0)
        self.assertEqual(body["reserve"], -7)

    def test_approving_puts_the_baseline_in_force(self):
        self.client.force_authenticate(self.methodist)

        response = self.approve(self.baseline.pk)

        self.assertEqual(response.status_code, 200, response.content)
        self.client.force_authenticate(self.user)
        state = self.state()
        self.assertEqual(state["approved"]["status"], "approved")
        self.assertIsNotNone(state["approved"]["approved_at"])
        self.assertIsNone(state["request"])

    def test_returning_needs_a_comment(self):
        self.client.force_authenticate(self.methodist)

        refused = self.send_back(self.baseline.pk)

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "comment_required")
        self.baseline.refresh_from_db()
        self.assertEqual(self.baseline.status, "pending")

    def test_returning_with_a_comment_reaches_the_teacher(self):
        self.client.force_authenticate(self.methodist)
        self.send_back(self.baseline.pk, "Мало часов на повторение")

        self.client.force_authenticate(self.user)
        state = self.state()

        self.assertEqual(state["request"]["status"], "returned")
        self.assertEqual(state["request"]["comment"], "Мало часов на повторение")
        self.assertIsNone(state["approved"])

    def test_the_methodist_reads_the_current_plan(self):
        """
        Правки после отправки ничего не отзывают: запрос висит, а методист
        открывает то, что в плане сейчас, — и утверждает именно это.
        """
        self.add("Дописанный после отправки", parent=self.trig, position=9)

        self.client.force_authenticate(self.methodist)
        body = self.client.get(
            reverse("planreview-detail", args=[self.baseline.pk])
        ).json()

        self.assertEqual(len(self.queue()), 1)
        self.assertIn("Дописанный после отправки", [row["title"] for row in body["rows"]])

        self.approve(self.baseline.pk)

        titles = [row.title for row in self.baseline.rows.all()]
        self.assertIn("Дописанный после отправки", titles)

    def test_approval_takes_the_snapshot(self):
        self.client.force_authenticate(self.methodist)

        self.approve(self.baseline.pk)

        rows = self.baseline.rows.all()
        self.assertEqual(sum(1 for row in rows if not row.is_section), 7)
        self.assertEqual(rows.count(), 10)

    def test_a_methodist_of_another_course_sees_nothing(self):
        other = make_course(self.school, year=self.course.year, name="9А")
        CourseMethodist.objects.create(course=other, user=self.stranger)
        self.stranger.school = self.school
        self.stranger.save(update_fields=["school"])

        self.client.force_authenticate(self.stranger)

        self.assertEqual(self.queue(), [])
        self.assertEqual(
            self.client.get(
                reverse("planreview-detail", args=[self.baseline.pk])
            ).status_code,
            404,
        )

    def test_a_teacher_without_the_role_sees_no_queue(self):
        self.client.force_authenticate(self.user)

        self.assertEqual(self.queue(), [])

    def test_the_methodist_cannot_edit_the_plan_they_review(self):
        """Утвердить или вернуть — да; править чужую работу — нет."""
        self.client.force_authenticate(self.methodist)
        lesson = PlanNode.objects.get(course=self.course, title="Синус суммы")

        response = self.client.patch(
            reverse("plannode-detail", args=[lesson.pk]),
            {"title": "По-моему, так лучше"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        lesson.refresh_from_db()
        self.assertEqual(lesson.title, "Синус суммы")

    def test_a_methodist_of_another_school_sees_nothing(self):
        CourseMethodist.objects.create(course=self.alien_class, user=self.alien_admin)
        self.client.force_authenticate(self.alien_admin)

        self.assertEqual(self.queue(), [])

    def test_an_administrator_approves_nothing_by_default(self):
        """Администратор распоряжается школой, а не содержанием предмета."""
        self.client.force_authenticate(self.admin)

        self.assertEqual(self.queue(), [])
        self.assertEqual(self.approve(self.baseline.pk).status_code, 404)


class SelfApprovalTests(ApprovalTestCase):
    def test_a_methodist_approves_their_own_plan_and_it_is_marked(self):
        self.make_methodist(self.user)

        self.submit()
        baseline = PlanBaseline.objects.get()
        self.approve(baseline.pk)

        state = self.state()
        self.assertEqual(state["approved"]["status"], "approved")
        self.assertTrue(state["approved"]["self_approved"])


class MetricsTests(ApprovalTestCase):
    def setUp(self):
        super().setUp()
        self.make_methodist(self.user)

    def approved_plan(self):
        self.submit()
        self.approve(PlanBaseline.objects.get(status="pending").pk)

    def test_without_an_approved_baseline_there_are_no_metrics(self):
        self.submit()

        self.assertIsNone(self.progress()["baseline"])
        self.assertEqual(self.progress()["review"]["status"], "pending")

    def test_a_freshly_approved_plan_differs_from_itself_in_nothing(self):
        self.approved_plan()

        baseline = self.progress()["baseline"]

        self.assertEqual((baseline["added"], baseline["removed"]), (0, 0))
        self.assertEqual(baseline["themes"], [])

    def test_added_and_removed_are_two_numbers_not_one(self):
        """Плюс три минус три — это не ноль, а шесть правок."""
        self.approved_plan()
        for index in range(3):
            self.add(f"Новый {index}", parent=self.trig, position=10 + index)
        PlanNode.objects.filter(
            title__in=("Понятие вектора", "Сложение векторов")
        ).delete()

        baseline = self.progress()["baseline"]

        self.assertEqual(baseline["added"], 3)
        self.assertEqual(baseline["removed"], 2)

    def test_growth_is_counted_per_theme(self):
        self.approved_plan()
        self.add("Ещё один", parent=self.trig, position=10)
        self.add("И ещё", parent=self.trig, position=11)
        self.add("Сам по себе", position=12)

        themes = self.progress()["baseline"]["themes"]

        self.assertEqual(themes[0], {"title": "Тригонометрия", "added": 2})
        self.assertEqual(themes[1], {"title": None, "added": 1})

    def test_renaming_is_not_a_change_of_size(self):
        self.approved_plan()
        lesson = PlanNode.objects.get(course=self.course, title="Синус суммы")
        lesson.title = "Синус суммы двух углов"
        lesson.save(update_fields=["title"])

        baseline = self.progress()["baseline"]

        self.assertEqual((baseline["added"], baseline["removed"]), (0, 0))

    def test_the_approved_baseline_survives_a_new_submission(self):
        """
        Пока новый снимок ждёт методиста, считать не от чего другого.

        Иначе отправка стирала бы точку отсчёта ровно в тот момент, когда
        она нужнее всего.
        """
        self.approved_plan()
        self.add("Новый урок", parent=self.trig, position=10)
        self.submit()

        row = self.progress()

        self.assertEqual(row["baseline"]["added"], 1)
        self.assertEqual(row["review"]["status"], "pending")

    def test_the_snapshot_outlives_the_lessons_it_names(self):
        self.approved_plan()
        PlanNode.objects.filter(course=self.course, title="Аксиомы").delete()

        self.assertEqual(self.progress()["baseline"]["removed"], 1)
