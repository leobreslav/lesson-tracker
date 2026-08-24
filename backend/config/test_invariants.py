"""
Реестр инвариантов: правила, которые держали в голове, — теперь под сторожем.

Проект вырос, и главная опасность в нём давно не «код не работает», а «решение
противоречит правилу, записанному в другом углу». Поэтому у каждого сквозного
правила должен быть **сторож**: тест, который падает, когда правило нарушено, и
называет само правило словами — чтобы читающий падение понял, что он сломал, не
поднимая историю.

Здесь собраны правила, которые **пересекают приложения** и потому не живут ни в
одном наборе тестов целиком. Правила внутри одного приложения стерегутся там же
(см. `schools/test_wiring.py`, `schedule/test_order_wiring.py`,
`plans/test_history_wiring.py`, `config/test_source.py`).

Как добавлять новое правило: заводите тест, чьё имя читается как утверждение,
и пишите в докстринге **почему** оно верно и что сломается без него. Тест,
объясняющий только «как», через полгода нельзя ни починить, ни выбросить.
"""

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin


class NoTestSpendsMoneyTests(SimpleTestCase):
    """
    Ни один тест не платит за чтение сканов.

    Чтение сканов — единственное место в проекте, где код тратит деньги, и
    ключ у прогона тот же, что у разработки: настоящий. Тест, случайно
    позвавший `vision.client`, списывал бы деньги на каждом прогоне — а
    гоняются они на каждом шаге работы, четырьмя шардами в CI и ночью.

    Хуже всего, что снаружи это ничем не выдаёт себя: платящий тест выглядит
    обычным зелёным тестом, и узнают о нём по счёту в конце месяца.

    Поэтому `config/testing.py` обнуляет ключ на весь прогон, а этот сторож
    следит, что обнуление не отменили: без него любой вызов упирается в
    `ai_key_missing`, то есть в громкий отказ вместо тихой траты.

    Проверять настоящее чтение так нельзя, и это не потеря: без настоящего
    запроса его не проверить никак. Такой запрос делается руками и с
    разрешения человека — CLAUDE.md, «Живые запросы к Anthropic».
    """

    def test_the_anthropic_key_is_empty_for_the_whole_run(self):
        self.assertEqual(
            getattr(settings, "ANTHROPIC_API_KEY", ""),
            "",
            "Ключ Anthropic виден тестам: прогон способен тратить деньги. "
            "Верните обнуление в config/testing.py.",
        )

    def test_no_second_reader_for_the_whole_run(self):
        """
        Платный путь тут не один, и второй завели позже первого.

        Шапку читают двое: модель и Mathpix, распознаватель рукописного.
        Второй продаётся не по токенам, а по запросам, и стоит дороже одного
        чтения моделью, — то есть забытый ключ обошёлся бы дороже той траты, с
        которой всё это правило началось.

        Проверяются оба ключа: Mathpix зовётся, только когда есть **и** имя
        приложения, **и** ключ, поэтому пустой любой из них уже закрывает
        дверь. Требуем пустых обоих — «дверь закрыта наполовину» это не
        состояние, а случайность, которую однажды поправят не в ту сторону.
        """
        for name in ("MATHPIX_APP_ID", "MATHPIX_APP_KEY"):
            self.assertEqual(
                getattr(settings, name, ""),
                "",
                f"{name} виден тестам: прогон способен платить за чтение "
                "шапок. Верните обнуление в config/testing.py.",
            )


class StatementLivesInOnePlaceTests(SimpleTestCase):
    """
    Текст условия живёт **только** в `bank.Problem`.

    Он уже успел пожить в трёх местах — у ячейки работы, у критерия шкалы и в
    банке, — и это стоило дня работы: правка в одном месте не доезжала до
    остальных, а расхождение было не видно ниоткуда. Второе поле с условием,
    заведённое где угодно, вернёт ту же беду.
    """

    # Поля, которые **законно** содержат текст, похожий на условие: у них
    # другая природа, и каждое названо с причиной.
    ALLOWED = {
        ("bank", "Problem", "text"): "само условие и есть",
        ("bank", "Solution", "text"): "разбор, а не условие",
        ("works", "Work", "description"): "что делать в работе целиком",
        ("works", "Submission", "answer"): "слова ученика, а не наша запись",
        ("works", "Message", "text"): "реплика разговора",
        ("plans", "PlanNode", "body"): "ход урока: программа, а не задача",
        ("plans", "PlanNode", "objectives"): "цели урока",
        ("plans", "PlanNode", "formative"): "формативное оценивание",
        ("plans", "PlanNode", "homework"): "домашнее задание строкой плана",
        ("library", "PlanTemplateRow", "body"): "то же, но в шаблоне",
        ("library", "PlanTemplateRow", "objectives"): "то же, но в шаблоне",
        ("library", "PlanTemplateRow", "formative"): "то же, но в шаблоне",
        ("library", "PlanTemplateRow", "homework"): "то же, но в шаблоне",
    }

    SUSPICIOUS = {"question", "statement", "problem_text", "condition"}

    def test_no_second_field_holds_a_statement(self):
        found = []
        for model in apps.get_models():
            label = model._meta.app_label
            if label not in {"bank", "works", "plans", "library"}:
                continue
            for field in model._meta.get_fields():
                if not hasattr(field, "get_internal_type"):
                    continue
                if field.get_internal_type() != "TextField":
                    continue
                key = (label, model.__name__, field.name)
                if key in self.ALLOWED:
                    continue
                if field.name in self.SUSPICIOUS:
                    found.append(f"{label}.{model.__name__}.{field.name}")

        self.assertEqual(
            found,
            [],
            "условие живёт только в bank.Problem: эти поля выглядят вторым его "
            "хранилищем — либо переносите текст в банк, либо назовите поле в "
            "ALLOWED с причиной",
        )


class TheCellHasNoTextOfItsOwnTests(SimpleTestCase):
    """
    У ячейки работы нет своего текста, и новое поле должно об этом сказать.

    Приём тот же, что у `LessonFieldsTests` в расписании: каждое поле названо
    либо местом (позиция, цена), либо связью, либо показом, либо правом
    ученика. Забытое поле — это ровно та тихая правка, из-за которой условие
    когда-то расползлось.
    """

    PLACE = {"id", "work", "position", "maximum", "created_at"}
    # `attachments` — снимки, присланные **по этому вопросу**. Связь, а не
    # текст: изображение тетради не отвечает на «что спрашивали», оно
    # отвечает на «что он написал», и лежит оно на работе ученика — ячейка
    # тут только адрес внутри неё.
    LINKS = {
        "problem",
        "submissions",
        "marks",
        "mark_changes",
        "threads",
        "attachments",
    }
    SHOWING = {"show_stem"}
    # Как ячейка **зовётся**, а не где стоит. Разряд отдельный от PLACE
    # намеренно: пока имени не было, эту роль исполняла позиция — вопросы
    # звались номерами по порядку, — и работа с пунктами «1а, 1б, 1в» была
    # невыразима. Имя не двигает ячейку и не решает, что видно; оно решает,
    # каким словом про неё говорят на уроке.
    NAMING = {"label"}
    # Что ученик вправе делать с этой ячейкой. Разряд заведён под
    # `open_for_answers` и назван отдельно от показа намеренно: показ решает,
    # что видно, а это — что можно, и разница видна на бумажной работе, где
    # условие показано, а ответить нельзя. Флагом работы (`on_paper`) на тот
    # же вопрос отвечали одним ответом на все ячейки разом.
    ANSWERING = {"open_for_answers"}

    def test_every_field_of_a_cell_is_classified(self):
        task = apps.get_model("works", "Task")
        names = {field.name for field in task._meta.get_fields()}

        unknown = (
            names
            - self.PLACE
            - self.NAMING
            - self.LINKS
            - self.SHOWING
            - self.ANSWERING
        )
        self.assertEqual(
            unknown,
            set(),
            "новое поле у ячейки: решите, это место (PLACE), имя (NAMING), "
            "связь (LINKS), показ (SHOWING) или право ученика (ANSWERING) — и "
            "допишите сюда. Текста у ячейки быть не может: он живёт в "
            "bank.Problem",
        )


class AnAttemptBelongsToACellTests(SimpleTestCase):
    """
    Попытка привязана к **ячейке**, а не к условию, и это не мелочь.

    Одно условие, спрошенное в контрольной и в домашней, даёт две ячейки и два
    независимых счёта попыток. Привяжи попытку к условию — и первая работа
    съест попытки у второй, а объяснить это ученику будет нечем.

    Отсюда же берётся «след ученика»: он собирается через ячейку к условию, и
    другого пути к нему нет.
    """

    def test_a_submission_points_at_a_task_and_not_at_a_problem(self):
        submission = apps.get_model("works", "Submission")
        names = {field.name for field in submission._meta.get_fields()}

        self.assertIn("task", names)
        self.assertNotIn(
            "problem",
            names,
            "попытка не должна знать про условие напрямую: путь к нему — через "
            "ячейку, иначе счёт попыток начнёт складываться между работами",
        )


class AStemIsNotAQuestionTests(SchoolTestMixin, APITestCase):
    """
    Сюжет не бывает ячейкой работы.

    У него нет ни вопроса, ни ответа, ни балла: ячейка, показывающая на него,
    спрашивала бы «решите условие». Дверей, через которые он мог бы туда
    попасть, две — сборка из банка (она разворачивает сюжет по пунктам) и
    «накатить условие на ячейку» (она отказывает). Тест сторожит вторую: первая
    без второй бесполезна.
    """

    def test_taking_a_stem_into_a_cell_is_refused(self):
        from bank.models import Problem
        from config.errors import ApiError
        from schools.testing import assign, make_course, make_work
        from works import statements
        from works.models import Task

        course = make_course(self.school)
        assign(self.user, course)
        work = make_work(self.user, course)

        stem = Problem.objects.create(
            text="Дан треугольник", school=self.school, owner=self.user
        )
        Problem.objects.create(
            text="Найдите площадь", parent=stem, school=self.school, owner=self.user
        )

        with self.assertRaises(ApiError):
            statements.take(
                Task.objects.create(work=work, position=0), stem, user=self.user
            )


class EveryDoorAsksWhoIsComingTests(SimpleTestCase):
    """
    Каждое место, выдающее токен приложения, спрашивает список допущенных.

    Токен — это и есть вход: получивший его ходит по API как свой. Мест,
    которые его выдают, в проекте два, и второе легко упустить из виду —
    `/api/test/login/` заведена ради браузерных тестов, живёт за флагом и
    выглядит служебной. Ровно поэтому она и опасна: она выдаёт токен **кому
    угодно по адресу**, без Google и без пароля.

    Пока стенд был закрыт паролем nginx, второй двери снаружи не существовало.
    Пароля больше нет (на `/api/` он и не мог стоять: basic-auth и токен
    приложения делят заголовок `Authorization`), и закрывает вход теперь
    список допущенных — `accounts/door.py`. Правило, написанное у одной двери,
    оставило бы вторую открытой, и выглядело бы это как «контур закрыт», пока
    кто-нибудь не наберёт второй адрес.

    Сторож поверх **текста**, а не поведения, потому что ловить надо не
    сломанную дверь, а **новую**: третье место, выдающее токен, само о себе не
    скажет, а его тест напишут про то, что оно выдаёт токен, — не про то, кому.
    """

    # Место, выдающее токен, и чем оно оправдано.
    DOORS = {
        "accounts/e2e.py": "дев-дверь браузерных тестов: токен по адресу",
    }

    # Токен тут раздаётся, но входом это не является.
    NOT_A_DOOR = {
        "schools/testing.py": "фикстура тестов: токен для клиента APITestCase",
    }

    def _minting_modules(self):
        backend = Path(settings.BASE_DIR)
        found = {}

        for path in sorted(backend.rglob("*.py")):
            relative = path.relative_to(backend).as_posix()
            name = Path(relative).name
            # Фильтр по имени, а не по «начинается на test»: `testing.py` —
            # это фикстуры, и первая же версия сторожа проглядела их именно
            # так, посчитав тестовым модулем то, что тестами не является.
            if "/migrations/" in relative or name == "tests.py" or name.startswith(
                "test_"
            ):
                continue
            text = path.read_text(encoding="utf-8")
            if "Token.objects" in text:
                found[relative] = text

        return found

    def test_no_new_place_hands_out_a_token_unnoticed(self):
        found = self._minting_modules()
        known = set(self.DOORS) | set(self.NOT_A_DOOR)

        self.assertEqual(
            set(found),
            known,
            "Список мест, выдающих токен приложения, изменился. Решите, что это: "
            "дверь — тогда она обязана спросить accounts.door и попасть в DOORS; "
            "или не вход вовсе — тогда в NOT_A_DOOR с причиной.",
        )

    def test_every_door_consults_the_list(self):
        found = self._minting_modules()

        for module, why in self.DOORS.items():
            with self.subTest(module):
                self.assertIn(
                    "door",
                    found.get(module, ""),
                    f"{module} ({why}) выдаёт токен, не спросив accounts.door: "
                    "на контуре со списком допущенных это открытый вход.",
                )

    def test_the_google_door_consults_the_list_too(self):
        """
        Вход через Google токен не выдаёт сам — его выдаёт dj-rest-auth.

        Поэтому по слову `Token.objects` эта дверь не находится, и в общий
        обход она не попадает. Спрашивает список адаптер allauth, до
        авторегистрации, и проверяется он отдельно — иначе обход выглядел бы
        полным, не покрывая как раз ту дверь, которой входят люди.
        """
        adapter = (Path(settings.BASE_DIR) / "accounts" / "adapter.py").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "refuse_unless_allowed",
            adapter,
            "Адаптер allauth перестал спрашивать список допущенных: вход через "
            "Google открыт всем, кого пустил Google.",
        )
