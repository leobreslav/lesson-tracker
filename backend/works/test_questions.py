"""
Условия задач, прочитанные с листа.

Условие ложится в вопрос работы — там ему и место: критерий отвечает на другой
вопрос, «как работа оценена». Проверяется тут одно решение и его последствия: **расхождение не
подгоняется, а называется**. Задач на листе больше, чем в шкале, или максимум
на бумаге не тот, что выставлен, — это вопрос к человеку, а не повод молча
переписать то, по чему уже могут стоять оценки.
"""

from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin, make_course, make_work, make_year

from . import services


class QuestionTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        services.set_questions(
            self.work, [{"maximum": 3} for _ in (1, 2, 3)], by=self.user
        )

    def questions(self, *items):
        return [
            {"number": number, "text": text, "marks": marks}
            for number, text, marks in items
        ]

    def test_the_statements_land_on_the_questions_by_number(self):
        got = services.apply_questions(
            self.work,
            by=self.user,
            found=self.questions(
                (1, "$2+2$", 3), (2, "$3\\times3$", 3), (3, "Сколько?", 3)
            ),
        )

        self.assertEqual(got["written"], 3)
        texts = list(self.work.tasks.values_list("problem__text", flat=True))
        self.assertEqual(texts, ["$2+2$", "$3\\times3$", "Сколько?"])

    def test_questions_beyond_the_scale_are_named_not_added(self):
        """
        Лист длиннее шкалы — это вопрос к человеку.

        Дописать критерии молча значит задним числом переписать то, по чему уже
        могут стоять оценки.
        """
        got = services.apply_questions(
            self.work, by=self.user, found=self.questions((1, "раз", 3), (4, "четыре", 3))
        )

        self.assertEqual(got["extra"], [4])
        self.assertEqual(self.work.tasks.count(), 3)

    def test_a_different_top_mark_is_reported_not_applied(self):
        got = services.apply_questions(self.work, by=self.user, found=self.questions((2, "два", 5)))

        self.assertEqual(got["marks_differ"], [{"number": 2, "marks": 5}])
        self.assertEqual(self.work.tasks.all()[1].maximum, 3)

    def test_reading_again_overwrites_the_old_text(self):
        """Кнопку жмут второй раз именно затем, чтобы переписать прочитанное."""
        services.apply_questions(self.work, by=self.user, found=self.questions((1, "старое", None)))
        services.apply_questions(self.work, by=self.user, found=self.questions((1, "новое", None)))

        self.assertEqual(self.work.tasks.first().problem.text, "новое")

    def test_a_sheet_without_questions_changes_nothing(self):
        services.apply_questions(self.work, by=self.user, found=self.questions((1, "раз", None)))

        got = services.apply_questions(self.work, by=self.user, found=[])

        self.assertEqual(got["written"], 0)
        self.assertEqual(self.work.tasks.first().problem.text, "раз")


class QuestionNameTests(SchoolTestMixin, APITestCase):
    """
    Вопрос зовётся своим именем, а если его нет — номером по порядку.

    Роли две, и раньше их исполняла одна позиция: «какой он по счёту» и «как
    его называют вслух». На работе с пунктами «1а, 1б, 1в» это ломалось —
    три пункта одного задания становились задачами 1, 2 и 3, и сказать «в
    третьей задаче» учитель уже не мог: третьей у него нет.

    Отсюда же второе решение, которое тут и стережётся: имя **не** заполняется
    номером при создании. Заполненное число пришлось бы перебивать при каждом
    переносе вопроса, и первый же перенос сделал бы имена враньём.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)

    def test_a_question_without_a_name_is_called_by_its_place(self):
        services.set_questions(
            self.work, [{"maximum": 1} for _ in (1, 2, 3)], by=self.user
        )

        self.assertEqual([task.name for task in self.work.tasks.all()], ["1", "2", "3"])

    def test_a_named_question_is_called_by_its_name(self):
        services.set_questions(
            self.work,
            [{"label": "1а"}, {"label": "1б"}, {"label": "324 из Галицкого"}],
            by=self.user,
        )

        self.assertEqual(
            [task.name for task in self.work.tasks.all()],
            ["1а", "1б", "324 из Галицкого"],
        )

    def test_a_name_survives_the_question_moving(self):
        """
        Имя принадлежит вопросу, а номер — месту, и переезд их разводит.

        Будь имя заполнено числом при создании, переезд оставил бы «2» на
        первом месте — то есть имя, которое врёт про порядок и при этом
        выглядит номером.
        """
        services.set_questions(
            self.work, [{"label": "1а"}, {"label": "1б"}], by=self.user
        )
        first, second = list(self.work.tasks.all())

        services.move(second, "up")

        self.assertEqual([task.name for task in self.work.tasks.all()], ["1б", "1а"])

    def test_an_unnamed_question_renumbers_itself_on_moving(self):
        """Безымянный зовётся местом, а место переездом и меняется."""
        services.set_questions(self.work, [{}, {}, {}], by=self.user)
        third = list(self.work.tasks.all())[2]

        services.move(third, "up")

        self.assertEqual([task.name for task in self.work.tasks.all()], ["1", "2", "3"])

    def test_the_table_calls_the_columns_by_their_names(self):
        """
        Имя доезжает до таблицы проверки — того экрана, ради которого оно и
        заведено: столбцов там пятнадцать, и искать среди них глазами можно
        только по подписи.
        """
        services.set_questions(
            self.work, [{"label": "1а"}, {"label": "1б"}], by=self.user
        )

        table = services.build_table(self.work)

        self.assertEqual([column["name"] for column in table["tasks"]], ["1а", "1б"])

    def test_saving_questions_without_names_does_not_wipe_them(self):
        """
        Отсутствие ключа значит «не трогай», а не «сними имя».

        Правят вопросы не только ради имён — максимум, открытость для ответов,
        условие с листа, — и умолчание в сериализаторе стирало бы имена молча
        при каждой такой правке.
        """
        services.set_questions(
            self.work, [{"label": "1а"}, {"label": "1б"}], by=self.user
        )

        services.set_questions(self.work, [{"maximum": 5}, {"maximum": 5}], by=self.user)

        self.assertEqual([task.name for task in self.work.tasks.all()], ["1а", "1б"])

    def test_an_empty_name_takes_the_name_off(self):
        """Пустая строка — это решение, и оно возвращает вопросу его номер."""
        services.set_questions(self.work, [{"label": "1а"}], by=self.user)

        services.set_questions(self.work, [{"label": ""}], by=self.user)

        self.assertEqual(self.work.tasks.first().name, "1")
