"""
Предложения: дверь в закрытый каталог.

Проверяется три правила, на которых всё стоит: **кому идёт** выводится из
владения, **принятие делает дело**, а **отказ требует слов**.
"""

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin

from . import proposals
from .models import METHOD, OBJECT, Problem, ProblemTag, Proposal, Solution, Tag


class ProposalTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_root()
        self.common = Problem.objects.create(
            text="Найдите площадь треугольнка", created_by=self.root
        )
        self.ours = Problem.objects.create(
            text="Школьная задача", school=self.school, created_by=self.admin
        )

    def propose(self, who, **body):
        self.client.force_authenticate(who)
        return self.client.post(reverse("bank-proposals"), body, format="json")

    def resolve(self, who, proposal, **body):
        self.client.force_authenticate(who)
        return self.client.patch(
            reverse("bank-proposal", args=[proposal]), body, format="json"
        )

    # --- кому идёт ---------------------------------------------------------

    def test_the_addressee_follows_the_ownership(self):
        system = self.propose(
            self.user, kind="typo", problem=self.common.pk, suggested="Найдите площадь"
        )
        school = self.propose(
            self.user, kind="typo", problem=self.ours.pk, suggested="Поправлено"
        )

        self.assertEqual(system.data["level"], "system")
        self.assertEqual(school.data["level"], "school")

        # и присланный уровень его не перебивает: иначе предложение про
        # системную задачу можно было бы адресовать школе, где его никто не
        # вправе применить
        forced = self.propose(
            self.user,
            kind="typo",
            problem=self.common.pk,
            suggested="…",
            level="school",
        )
        self.assertEqual(forced.data["level"], "system")

    def test_a_school_admin_resolves_the_school_queue_and_not_the_common_one(self):
        system = self.propose(
            self.user, kind="typo", problem=self.common.pk, suggested="…"
        ).data
        school = self.propose(
            self.user, kind="typo", problem=self.ours.pk, suggested="…"
        ).data

        self.client.force_authenticate(self.admin)
        waiting = self.client.get(reverse("bank-proposals")).data["waiting"]
        self.assertEqual([one["id"] for one in waiting], [school["id"]])

        # а системное для него неотличимо от несуществующего: не его очередь и
        # не его предложение — то же правило, что у чужого объекта везде
        self.assertEqual(
            self.resolve(self.admin, system["id"], state="accepted").status_code, 404
        )

    def test_a_teacher_has_no_queue_at_all(self):
        self.propose(self.user, kind="typo", problem=self.ours.pk, suggested="…")

        self.client.force_authenticate(self.colleague)
        answer = self.client.get(reverse("bank-proposals")).data
        self.assertEqual(answer["waiting"], [])
        self.assertEqual(answer["mine"], [])

    # --- принятие делает дело ---------------------------------------------

    def test_accepting_a_typo_writes_the_suggested_text(self):
        made = self.propose(
            self.user,
            kind="typo",
            problem=self.ours.pk,
            text="буква пропущена",
            suggested="Школьная задача, поправленная",
        ).data

        self.resolve(self.admin, made["id"], state="accepted")
        self.ours.refresh_from_db()

        self.assertEqual(self.ours.text, "Школьная задача, поправленная")

    def test_accepting_a_tag_hangs_it(self):
        tag = Tag.objects.create(name="многочлен", kind=OBJECT)
        made = self.propose(
            self.user, kind="tag", problem=self.ours.pk, tag=tag.pk, text="просится"
        ).data

        self.resolve(self.admin, made["id"], state="accepted")

        self.assertTrue(
            ProblemTag.objects.filter(problem=self.ours, tag=tag).exists()
        )

    def test_a_new_tag_needs_its_kind_from_the_one_who_keeps_the_dictionary(self):
        made = self.propose(
            self.user,
            kind="tag",
            problem=self.common.pk,
            suggested="многочлен",
            text="такого тега нет",
        ).data

        # вид называет разбирающий: словарь разложен по видам, и это его дело
        refused = self.resolve(self.root, made["id"], state="accepted")
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.data["code"], "tag_kind_required")

        self.resolve(self.root, made["id"], state="accepted", tag_kind=OBJECT)
        self.assertTrue(Tag.objects.filter(name="многочлен", kind=OBJECT).exists())
        self.assertTrue(
            ProblemTag.objects.filter(problem=self.common, tag__name="многочлен").exists()
        )

    def test_a_method_tag_does_not_land_on_a_statement_and_nothing_is_left_behind(self):
        # метод вешается на разбор, а не на условие. Принятие отказывает — и
        # тег при этом не заводится: транзакция откатывает всё, иначе в словаре
        # оставался бы мусор от неудавшегося разбора
        made = self.propose(
            self.user, kind="tag", problem=self.common.pk, suggested="производная"
        ).data

        refused = self.resolve(self.root, made["id"], state="accepted", tag_kind=METHOD)

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.data["code"], "tag_kind_mismatch")
        self.assertFalse(Tag.objects.filter(name="производная").exists())

    def test_accepting_a_problem_keeps_the_author_in_the_history(self):
        made = self.propose(
            self.user,
            kind="problem",
            suggested="Докажите, что $x^2 \\geqslant 0$",
            text="пригодится",
        ).data

        self.resolve(self.admin, made["id"], state="accepted")
        added = Problem.objects.get(text__startswith="Докажите")

        # владение школьное, а авторство — того, кто предложил: приписывать
        # чужую работу разбирающему нечестно
        self.assertEqual(added.level, "school")
        self.assertEqual(added.created_by_id, self.user.pk)

    def test_accepting_a_solution_adds_it_to_the_named_problem(self):
        made = self.propose(
            self.user,
            kind="solution",
            problem=self.ours.pk,
            suggested="Через теорему косинусов",
        ).data

        self.resolve(self.admin, made["id"], state="accepted")
        self.assertEqual(
            [one.text for one in Solution.objects.filter(problem=self.ours)],
            ["Через теорему косинусов"],
        )

    # --- отказ и разговор --------------------------------------------------

    def test_declining_without_words_is_refused(self):
        made = self.propose(
            self.user, kind="other", text="что-то не так", problem=self.ours.pk
        ).data

        silent = self.resolve(self.admin, made["id"], state="declined")
        self.assertEqual(silent.status_code, 400)
        self.assertEqual(silent.data["code"], "proposal_answer_required")

        spoken = self.resolve(
            self.admin, made["id"], state="declined", answer="это не опечатка"
        )
        self.assertEqual(spoken.data["state"], "declined")
        self.assertEqual(spoken.data["answer"], "это не опечатка")

    def test_both_sides_talk_in_one_thread(self):
        made = self.propose(
            self.user, kind="other", text="а тут точно так?", problem=self.ours.pk
        ).data

        self.client.force_authenticate(self.admin)
        self.client.post(
            reverse("bank-proposal", args=[made["id"]]),
            {"text": "а что именно смущает?"},
            format="json",
        )
        self.client.force_authenticate(self.user)
        answer = self.client.post(
            reverse("bank-proposal", args=[made["id"]]),
            {"text": "вторая строка"},
            format="json",
        )

        self.assertEqual(
            [one["text"] for one in answer.data["notes"]],
            ["а что именно смущает?", "вторая строка"],
        )

    def test_someone_elses_proposal_is_indistinguishable_from_none(self):
        made = self.propose(
            self.user, kind="other", text="…", problem=self.ours.pk
        ).data

        self.client.force_authenticate(self.colleague)
        self.assertEqual(
            self.client.get(reverse("bank-proposal", args=[made["id"]])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("bank-proposal", args=[10**9])).status_code, 404
        )

    def test_an_empty_proposal_is_refused(self):
        answer = self.propose(self.user, kind="other", problem=self.ours.pk)
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "proposal_empty")
