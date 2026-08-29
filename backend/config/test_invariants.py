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


def owners_named_in(node) -> set:
    """
    Имена владельцев, каждый из которых назван в условии ограничения.

    `owned_by` строит ветку «этот назван, остальные пусты», поэтому владелец
    ветки — единственное поле с `isnull=False`. Пустые части сверять незачем:
    их проставляет сам `OWNER_FIELDS`, и разойтись с ним они не могут.

    Владельцев в проекте два вида — у вложения и у строки плана, — и обход
    условия у них один и тот же. Две копии этого обхода разошлись бы в первой
    же правке, и вторая молча перестала бы что-либо проверять.
    """
    found = set()
    for child in node.children:
        if hasattr(child, "children"):
            found |= owners_named_in(child)
            continue
        lookup, value = child
        if lookup.endswith("__isnull") and value is False:
            found.add(lookup[: -len("__isnull")])
    return found


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

    def test_no_third_reader_for_the_whole_run(self):
        """
        Читателей стало трое, и правило у них общее.

        Yandex Vision OCR продаётся так же — за страницу, — и заведён он ради
        контура, до Anthropic не достающего. Ключ у него отдельный, значит и
        обнуление отдельное: список платных дверей растёт, и каждая новая
        обязана попасть сюда **в тот же день**, когда появилась. Забытая
        обнаружится не прогоном, а счётом.
        """
        self.assertEqual(
            getattr(settings, "YANDEX_OCR_API_KEY", ""),
            "",
            "YANDEX_OCR_API_KEY виден тестам: прогон способен платить за "
            "чтение шапок. Верните обнуление в config/testing.py.",
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


class EveryOwnerOfAnAttachmentAnnouncesItselfTests(SimpleTestCase):
    """
    У вложения ровно один владелец, и новый обязан о себе сказать.

    Владелец отвечает на вопрос «к чему это приложено», и из ответа следует
    **круг читателей** — а он у всех разный: материал урока читают ведущие
    курса, тетрадь — ученик с семьёй, личный стол — один человек, полку
    школы — все её сотрудники. Списком это выглядит одинаково, поэтому
    добавить шестого владельца и не решить про него ничего — правка на одну
    строку, и выглядит она безобидно.

    Молчит она в обе стороны. Забытая ветка в ограничении таблицы ничего не
    **запрещает**: строка с двумя владельцами сразу становится законной, и
    вложение оказывается в двух списках одновременно. Забытый разбор в
    `files/access.py` падает `AttributeError`'ом в `can_read` — не тихо, но
    и не там, где на него посмотрят: последним условием там стоит шаблон, и
    незнакомый владелец доходит до него как до «всего остального».

    Проверено на себе: за одну ветку владельцев стало на двух больше, а
    проза рядом с ними по-прежнему говорила «пять» — то есть следующий
    пришёл бы добавлять седьмого, прочитав неверное число.

    Приём тот же, что у `LessonFieldsTests` и `TheCellHasNoTextOfItsOwn`:
    список перечисляется здесь, и незнакомое имя роняет тест с требованием
    решить, кто это читает.
    """

    # владелец → чей это круг читателей. Строка нужна не для красоты: она и
    # есть то решение, которое иначе принимают молча
    OWNERS = {
        "plan_row": "материал урока: ведущие курса",
        "template_row": "строка шаблона: кому открыт шаблон",
        "work": "что здесь задано: ведущий, а класс — по `staff_only`",
        "student_work": "тетрадь ученика: он сам, его семья и ведущий",
        "bookmark_owner": "личный стол: хозяин, и никто больше — чужому 404",
        "school_shelf": "полка школы: читают сотрудники, пишет администратор",
    }

    def test_every_owner_is_named_with_the_circle_that_reads_it(self):
        from files.models import OWNER_FIELDS

        unknown = set(OWNER_FIELDS) - set(self.OWNERS)
        self.assertEqual(
            unknown,
            set(),
            "у вложения новый владелец: решите, кто его читает и кто правит "
            "(`files/access.py`, `can_read` и `can_write`), и допишите его "
            "сюда с этим кругом. Владелец без круга читателей — это список, "
            "в который вещь попадает неизвестно кому",
        )

        gone = set(self.OWNERS) - set(OWNER_FIELDS)
        self.assertEqual(
            gone,
            set(),
            "владелец исчез из OWNER_FIELDS, а строка про него осталась: "
            "уберите её, иначе следующий будет искать поле, которого нет",
        )

    def test_the_constraint_counts_the_same_owners(self):
        """
        Ограничение таблицы перечисляет ровно тех же, кого `OWNER_FIELDS`.

        Это та половина, которая молчит: `owned_by` расставляет пустые поля
        по списку сама, а вот **ветку** для нового владельца дописывают
        руками. Без неё «ровно один владелец» перестаёт быть правилом
        именно для него — и первая же строка с двумя владельцами пройдёт в
        базу, не встретив ни ошибки, ни отказа.
        """
        from files.models import OWNER_FIELDS, Attachment

        constraint = next(
            item
            for item in Attachment._meta.constraints
            if item.name == "attachment_has_exactly_one_owner"
        )

        self.assertEqual(
            owners_named_in(constraint.condition),
            set(OWNER_FIELDS),
            "ограничение «владелец ровно один» знает не тех владельцев, что "
            "OWNER_FIELDS: допишите ветку `owned_by(...)` — забытая ничего не "
            "запрещает, и вложение сможет лежать в двух местах сразу",
        )


class EveryOwnerOfAPlanAnnouncesItselfTests(SimpleTestCase):
    """
    У строки плана ровно один владелец, и новый обязан о себе сказать.

    Владелец отвечает на «чьё это дерево», и из ответа следуют две вещи,
    которые больше ниоткуда не выводятся: **кто вправе это править** и **есть
    ли у дерева календарь**. У курса правит назначенный ведущий либо
    администратор школы, и календарь есть — даты, раскладка, записи занятий,
    утверждение методистом. У шаблона правит автор, и календаря нет вовсе:
    план на полке к учебному году намеренно не привязан.

    Добавить третьего владельца и не решить про него ни того, ни другого —
    правка на одну строку, и выглядит она безобидно. Молчит она по-разному:
    без решения о праве дерево либо закрыто от всех (`writable_by` его не
    вернёт), либо открыто лишнему; без решения о календаре экран пойдёт за
    лентой слотов, которой у этого владельца не бывает, и уронит отказ на
    пустом месте.

    Забыть ветку в ограничении тут нельзя: условие собирается из
    `OWNER_FIELDS` само (`plans.owning.exactly_one_owner`) — в отличие от
    вложения, где ветки перечислены руками. Сторож всё равно сверяет обе
    стороны: переписанное руками условие вернуло бы ровно ту беду.
    """

    # владелец → кто правит и что у него с календарём. Строка нужна не для
    # красоты: она и есть то решение, которое иначе принимают молча
    OWNERS = {
        "course": "курс: правит ведущий или администратор школы, календарь есть",
        "template": "шаблон с полки: правит автор, календаря нет вовсе",
    }

    def test_every_owner_is_named_with_who_writes_it(self):
        from plans.owning import OWNER_FIELDS

        unknown = set(OWNER_FIELDS) - set(self.OWNERS)
        self.assertEqual(
            unknown,
            set(),
            "у строки плана новый владелец: решите, кто его правит "
            "(`config/access.py`) и есть ли у него календарь, и допишите его "
            "сюда с этим ответом. Владелец без ответа — это дерево, которое "
            "либо никому не открыть, либо открыто не тому",
        )

        gone = set(self.OWNERS) - set(OWNER_FIELDS)
        self.assertEqual(
            gone,
            set(),
            "владелец исчез из OWNER_FIELDS, а строка про него осталась: "
            "уберите её, иначе следующий будет искать поле, которого нет",
        )

    def test_the_constraint_counts_the_same_owners(self):
        """
        Ограничение таблицы перечисляет ровно тех же, кого `OWNER_FIELDS`.

        Проверка не про сегодняшний день, а про завтрашний: пока условие
        собирает `exactly_one_owner`, разойтись нечему. Разойдётся оно в тот
        день, когда кто-нибудь распишет ветки руками ради одного исключения,
        — и тогда «владелец ровно один» перестанет быть правилом именно для
        забытого, а первая же строка с двумя владельцами пройдёт в базу.
        """
        from plans.models import PlanNode
        from plans.owning import OWNER_FIELDS

        constraint = next(
            item
            for item in PlanNode._meta.constraints
            if item.name == "plan_node_has_exactly_one_owner"
        )

        self.assertEqual(
            owners_named_in(constraint.condition),
            set(OWNER_FIELDS),
            "ограничение «владелец ровно один» знает не тех владельцев, что "
            "OWNER_FIELDS: строка плана сможет принадлежать двум деревьям "
            "сразу или ни одному",
        )
