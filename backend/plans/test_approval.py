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

from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from schedule.models import CourseMethodist, Subject
from schools.testing import MONDAY, assign, make_course, make_node, make_slot

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
        # методист курс не ведёт: ведущий у курса один, а утверждает
        # обычно как раз не он
        self.methodist = self.colleague

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

    def supervised(self):
        """Что видит методист: все планы под его надзором, не только запросы."""
        return self.client.get(reverse("planreview-list")).json()["plans"]

    def supervised_row(self, course=None):
        """Строка курса: план принадлежит курсу, и строка у него одна."""
        course = course or self.course
        return next(row for row in self.supervised() if row["id"] == course.pk)

    def review(self, course=None):
        """План под надзором: адресуется курсом, а не присланным запросом."""
        return self.client.get(
            reverse("planreview-detail", args=[(course or self.course).pk])
        )

    def approve(self, course=None):
        return self.client.post(
            reverse("planreview-approve", args=[(course or self.course).pk])
        )

    def send_back(self, comment="", course=None):
        return self.client.post(
            reverse("planreview-return", args=[(course or self.course).pk]),
            {"comment": comment},
            format="json",
        )

    def progress(self, course=None):
        from django.utils import timezone
        from plans import progress as progress_module

        rows = progress_module.rows_for(
            progress_module.own_courses(self.user), timezone.localdate()
        )
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

    def test_the_methodist_sees_the_request_as_a_mark_on_the_row(self):
        self.client.force_authenticate(self.methodist)

        row = self.supervised_row()

        self.assertEqual(row["name"], self.course.name)
        self.assertEqual(row["lessons_total"], 7)
        # запрос — пометка в строке, а не причина её существования
        self.assertEqual(row["review"]["status"], "pending")

    def test_the_request_opens_with_the_plan_and_the_numbers(self):
        """Методист смотрит живой план: правка отозвала бы запрос."""
        self.client.force_authenticate(self.methodist)

        body = self.review().json()

        self.assertEqual(len(body["rows"]), 10)
        self.assertEqual(body["rows"][0]["title"], "Тригонометрия")
        self.assertTrue(body["rows"][0]["is_section"])
        self.assertEqual(body["slots_total"], 0)
        self.assertEqual(body["reserve"], -7)

    def test_approving_puts_the_baseline_in_force(self):
        self.client.force_authenticate(self.methodist)

        response = self.approve()

        self.assertEqual(response.status_code, 200, response.content)
        self.client.force_authenticate(self.user)
        state = self.state()
        self.assertEqual(state["approved"]["status"], "approved")
        self.assertIsNotNone(state["approved"]["approved_at"])
        self.assertIsNone(state["request"])

    def test_returning_needs_a_comment(self):
        self.client.force_authenticate(self.methodist)

        refused = self.send_back()

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "comment_required")
        self.baseline.refresh_from_db()
        self.assertEqual(self.baseline.status, "pending")

    def test_returning_with_a_comment_reaches_the_teacher(self):
        self.client.force_authenticate(self.methodist)
        self.send_back("Мало часов на повторение")

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
        body = self.review().json()

        self.assertEqual(self.supervised_row()["review"]["status"], "pending")
        self.assertIn("Дописанный после отправки", [row["title"] for row in body["rows"]])

        self.approve()

        titles = [row.title for row in self.baseline.rows.all()]
        self.assertIn("Дописанный после отправки", titles)

    def test_approval_takes_the_snapshot(self):
        self.client.force_authenticate(self.methodist)

        self.approve()

        rows = self.baseline.rows.all()
        self.assertEqual(sum(1 for row in rows if not row.is_section), 7)
        self.assertEqual(rows.count(), 10)

    def test_a_methodist_of_another_course_sees_nothing(self):
        other = make_course(self.school, year=self.course.year, name="9А")
        CourseMethodist.objects.create(course=other, user=self.stranger)
        self.stranger.school = self.school
        self.stranger.save(update_fields=["school"])

        self.client.force_authenticate(self.stranger)

        # свой курс он видит, наш — нет
        self.assertNotIn(self.course.pk, [row["id"] for row in self.supervised()])
        self.assertEqual(
            self.review().status_code,
            404,
        )

    def test_a_teacher_without_the_role_sees_no_queue(self):
        self.client.force_authenticate(self.user)

        self.assertEqual(self.supervised(), [])

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

        self.assertNotIn(self.course.pk, [row["id"] for row in self.supervised()])

    def test_an_administrator_approves_nothing_by_default(self):
        """Администратор распоряжается школой, а не содержанием предмета."""
        self.client.force_authenticate(self.admin)

        self.assertEqual(self.supervised(), [])
        self.assertEqual(self.approve().status_code, 404)


class SupervisionTests(ApprovalTestCase):
    """
    Экран методиста показывает **все** планы под его надзором.

    Очередь на утверждение отвечала на вопрос «что мне подписать», а
    спрашивают с методиста другое: кто отстаёт, у кого план не помещается в
    год, кто переписал половину после утверждения. Про тех, кто ничего не
    присылал, очередь молчала — а это как раз те, к кому есть вопросы.
    """

    def setUp(self):
        super().setUp()
        self.make_methodist(self.methodist)
        self.client.force_authenticate(self.methodist)

    def test_a_plan_shows_up_without_any_request(self):
        row = self.supervised_row()

        self.assertIsNone(row["review"])
        self.assertEqual(row["lessons_total"], 7)

    def test_the_plan_opens_without_any_request(self):
        """
        Право читать даёт назначение методистом, а не присланный запрос.

        Очередь на подпись была единственным входом и потому решала заодно,
        что методисту видно: список стал полным, а план по-прежнему
        открывался только присланный. Спрашивают же с него ровно про
        остальных — про тех, кто ничего не отправлял.
        """
        body = self.review().json()

        self.assertEqual(len(body["rows"]), 10)
        self.assertEqual(body["rows"][0]["title"], "Тригонометрия")
        self.assertEqual(body["lessons"], 7)
        # запрос — состояние плана, а не пропуск к нему
        self.assertIsNone(body["review"])
        self.assertEqual(body["course"]["id"], self.course.pk)

    def test_the_comparison_opens_without_any_request_too(self):
        """Сравнение — другой взгляд на то же самое, а не второе право."""
        body = self.client.get(
            reverse("planreview-diff", args=[self.course.pk])
        ).json()

        self.assertEqual(body["baseline"], None)

    def test_there_is_nothing_to_decide_until_the_plan_is_sent(self):
        """
        План виден всегда, а решают только присланное.

        Кнопки живут рядом с планом, поэтому «открыт, но утверждать нечего»
        — обычное состояние, и отказ на него внятный, а не 404.
        """
        for answer in (self.approve(), self.send_back("нет")):
            self.assertEqual(answer.status_code, 400, answer.content)
            self.assertEqual(answer.json()["code"], "review_not_pending")

        self.assertFalse(PlanBaseline.objects.exists())

    def test_a_returned_request_is_not_waiting_for_a_decision(self):
        """Вернули — ход за учителем: решать снова нечего, пока не прислал."""
        self.client.force_authenticate(self.user)
        self.submit(self.methodist)
        self.client.force_authenticate(self.methodist)
        self.send_back("Мало часов")

        self.assertEqual(self.approve().json()["code"], "review_not_pending")

    def test_the_numbers_are_the_ones_the_teacher_sees(self):
        """
        Один расчёт на два экрана — иначе разговор про «отстаёшь» начинался
        бы со спора о цифрах.
        """
        make_slot(self.user, self.course, day=MONDAY, number=1)
        make_slot(self.user, self.course, day=MONDAY + timedelta(days=1), number=1)

        seen_by_methodist = self.supervised_row()
        self.client.force_authenticate(self.user)
        seen_by_teacher = self.progress()

        for field in ("lessons_total", "slots_total", "reserve", "done", "missing"):
            self.assertEqual(
                seen_by_methodist[field], seen_by_teacher[field], field
            )

    def test_a_course_has_exactly_one_row(self):
        """План принадлежит курсу, и ведущий у курса один — строка одна."""
        rows = [row for row in self.supervised() if row["id"] == self.course.pk]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["teacher"]["id"], self.user.pk)

    def test_a_teacher_who_has_not_started_is_visible_too(self):
        """«Ещё не начал» — то, что методисту как раз нужно видеть."""
        fresh = make_course(self.school, year=self.course.year, name="9Г")
        assign(self.colleague, fresh)
        self.make_methodist(self.methodist, course=fresh)

        row = self.supervised_row(fresh)

        self.assertEqual(row["lessons_total"], 0)
        self.assertEqual(row["teacher"]["id"], self.colleague.pk)
        self.assertIsNone(row["review"])

    def test_courses_without_the_role_are_not_there(self):
        other = make_course(self.school, year=self.course.year, name="9В")
        assign(self.user, other)

        self.assertNotIn(other.pk, [row["id"] for row in self.supervised()])

    def test_the_queries_do_not_grow_with_the_plans(self):
        for index in range(3):
            extra = make_course(self.school, year=self.course.year, name=f"9-{index}")
            assign(self.user, extra)
            self.make_methodist(self.methodist, course=extra)
            make_node(self.user, extra, f"Урок {index}")

        with CaptureQueriesContext(connection) as many:
            rows = self.supervised()

        self.assertGreaterEqual(len(rows), 4)
        self.assertLess(
            len(many),
            15,
            f"на {len(rows)} планов ушло {len(many)} запросов",
        )


class SelfApprovalTests(ApprovalTestCase):
    def test_a_methodist_approves_their_own_plan_and_it_is_marked(self):
        self.make_methodist(self.user)

        self.submit()
        baseline = PlanBaseline.objects.get()
        self.approve()

        state = self.state()
        self.assertEqual(state["approved"]["status"], "approved")
        self.assertTrue(state["approved"]["self_approved"])


class MetricsTests(ApprovalTestCase):
    def setUp(self):
        super().setUp()
        self.make_methodist(self.user)

    def approved_plan(self):
        self.submit()
        self.approve()

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


class DiffVersionTests(ApprovalTestCase):
    """
    Сравнивать можно с любым утверждением, а не только с последним.

    История снимков копилась с самого начала: `approve` переписывает только
    свои строки, и прежние утверждения остаются в базе целиком. Вопрос «что
    изменилось с начала года» такой же законный, как «что с последней
    подписи», — и до появления выбора ответить на него было нечем.
    """

    def setUp(self):
        super().setUp()
        self.make_methodist(self.methodist)

    def sign(self):
        """Отправить и утвердить — одно утверждение целиком."""
        request = self.submit(self.methodist).json()["request"]
        self.client.force_authenticate(self.methodist)
        self.approve()
        self.client.force_authenticate(self.user)
        return request["id"]

    def diff(self, baseline=None):
        query = {"course": self.course.pk}
        if baseline is not None:
            query["baseline"] = baseline
        return self.client.get(reverse("plannode-diff"), query)

    def test_every_approval_stays_a_version(self):
        first = self.sign()
        self.add("Новый урок", position=9)
        second = self.sign()

        versions = self.diff().json()["versions"]

        # свежее сверху: сравнивают обычно с последним, и он же по умолчанию
        self.assertEqual([item["id"] for item in versions], [second, first])

    def test_the_latest_approval_is_the_default(self):
        self.sign()
        self.add("Новый урок", position=9)
        second = self.sign()
        self.add("Ещё один", position=10)

        body = self.diff().json()
        added = [row for row in body["rows"] if row["state"] == "added"]

        self.assertEqual(body["baseline"]["id"], second)
        self.assertEqual([row["title"] for row in added], ["Ещё один"])

    def test_an_older_version_counts_everything_since_it(self):
        first = self.sign()
        self.add("Новый урок", position=9)
        self.sign()
        self.add("Ещё один", position=10)

        body = self.diff(first).json()
        added = [row["title"] for row in body["rows"] if row["state"] == "added"]

        self.assertEqual(body["baseline"]["id"], first)
        self.assertEqual(added, ["Новый урок", "Ещё один"])

    def test_a_stranger_baseline_is_refused(self):
        """Чужой снимок и несуществующий — один отказ: подтверждать нечего."""
        self.sign()

        response = self.diff(baseline=999999)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "baseline_unknown")

    def test_the_methodist_sees_the_same_versions(self):
        first = self.sign()
        self.add("Новый урок", position=9)
        request = self.submit(self.methodist).json()["request"]

        self.client.force_authenticate(self.methodist)
        body = self.client.get(
            reverse("planreview-diff", args=[self.course.pk]), {"baseline": first}
        ).json()

        self.assertEqual(body["baseline"]["id"], first)
        self.assertEqual(
            [row["title"] for row in body["rows"] if row["state"] == "added"],
            ["Новый урок"],
        )
