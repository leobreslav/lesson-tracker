"""
Потолок расхода и журнал трат.

Проверяется не арифметика — она в две строки, — а три решения, каждое из
которых легко откатить назад по недосмотру: ноль значит «нельзя», потолок
считается за календарный месяц, и журнал показывает учителю **его** строки, а
администратору все.
"""

from datetime import timedelta

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin

from . import agreement, client, mathpix, reach, services, strip, yandex
from .models import AiSpend
from . import prices
from .prices import HAIKU, SONNET, cost_micros


class PromptTests(SimpleTestCase):
    """
    Что модель знает о листе — и чего ей знать не следует.

    Правило одно, и выведено оно дважды, дорого: **всё, что подсказывает
    ожидаемый ответ, будет подставлено вместо увиденного.** Сперва это был
    список класса, который подменил фамилию — «Lape» стала «Jerbi», потому что
    Jerbi в списке был. Потом максимум за задачу: у работы со шкалой «четыре
    задачи по одному баллу» промпт говорил «оценка от 0 до 1, большее число
    почти наверняка неверно прочитанная цифра, посмотри ещё раз», и лист с
    выставленными «1 2 0 3 2» прочитался как «1 2 0 3 0». Модель не ошиблась —
    она послушалась.

    Проверять «бывает ли такое число» — работа сервера: `troubles` ставит
    `mark_too_big`, и человек видит и цифру, и лист. Проверка на месте, а
    чтение не искажено.
    """

    def test_the_prompt_does_not_say_what_it_expects(self):
        prompt = client._system_prompt()

        self.assertNotIn("look again", prompt)
        self.assertNotIn("between 0 and", prompt)

    def test_the_prompt_asks_for_what_is_seen(self):
        self.assertIn("never adjust a mark", client._system_prompt())

    def test_the_prompt_takes_no_scale(self):
        """
        Максимум не просто не упоминается — его сюда и не передают. Пока
        параметр был, вернуть фразу стоило одной строки, а стоит она пачки
        неверно прочитанных баллов.
        """
        from inspect import signature

        self.assertEqual(list(signature(client._system_prompt).parameters), [])
        self.assertNotIn("max_mark", signature(client.read_header).parameters)


class CellLabelTests(SimpleTestCase):
    """
    Клетку называют подписью, а не местом в списке.

    Список из шестнадцати значений требует от модели считать клетки слева, и
    счёт сбивается: на живой странице баллы стояли в Q14, Q15 и в сумме, а
    приехали в Q13, Q14 и Q15 — сдвиг на одну, — да ещё сумма попала разом в
    Q15 и в свою клетку. Ошибка молчаливая: пятнадцать чисел выглядят одинаково
    правдоподобно, где бы они ни стояли, и заметить сдвиг можно только по
    бумаге.

    Подпись над каждой клеткой на бланке напечатана (`Q1`…`Q15` и сигма),
    поэтому «прочти подпись» — это чтение, а не счёт.
    """

    def test_a_question_label_finds_its_place(self):
        self.assertEqual(client.cell_index("Q14"), 13)
        self.assertEqual(client.cell_index("Q1"), 0)
        self.assertEqual(client.cell_index("Q15"), 14)

    def test_the_label_is_taken_generously(self):
        """Форма подписи — не повод потерять верно прочитанный балл."""
        for label in ("q14", "14", "Q 14", " Q14 "):
            self.assertEqual(client.cell_index(label), 13, label)

    def test_the_sum_is_a_cell_of_its_own(self):
        """Сигму модель зовёт по-разному, а клетка у суммы одна и последняя."""
        for label in ("sum", "total", "Σ pg", "σ"):
            self.assertEqual(client.cell_index(label), 15, label)

    def test_a_label_we_do_not_know_is_dropped(self):
        for label in ("", "Q0", "Q16", "Q99", "какая-то"):
            self.assertIsNone(client.cell_index(label), label)

    def test_marks_land_where_they_are_labelled(self):
        values = client.values_from_marks(
            [{"cell": "Q14", "value": 3}, {"cell": "Q15", "value": 3}, {"cell": "sum", "value": 6}]
        )

        self.assertEqual(values[13], 3)
        self.assertEqual(values[14], 3)
        self.assertEqual(values[15], 6)

    def test_an_unnamed_cell_stays_empty(self):
        """Пустая клетка не называется вовсе: её отсутствие и есть пустота."""
        values = client.values_from_marks([{"cell": "Q2", "value": 1}])

        self.assertEqual(values[1], 1)
        self.assertEqual([v for v in values if v is not None], [1])

    def test_rubbish_does_not_break_the_page(self):
        """
        Половина прочитанного лучше отказа: страница с одной непонятой клеткой
        доедет до человека с остальными, а не исчезнет целиком.
        """
        values = client.values_from_marks(
            ["не словарь", {"cell": "Q3"}, {"cell": "Q4", "value": "два"}, {"cell": "Q5", "value": 2}]
        )

        self.assertEqual(values[4], 2)
        self.assertEqual(len(values), 16)

    def test_nothing_read_is_sixteen_empties(self):
        self.assertEqual(client.values_from_marks(None), [None] * 16)


class ModelChoiceTests(SimpleTestCase):
    """
    Какой моделью читается шапка — настройка, а не константа в коде.

    На цифрах, вырезанных в отдельные квадратики, разницы между моделями нет:
    задача простая. Разница есть на рукописном имени, и стоит она втрое —
    значит, это выбор хозяина ключа, а не наш. Проверяется он единственным
    способом, живой пачкой, и переключение поэтому обязано стоить строки в
    `.env`.

    Сторож нужен ровно затем, чтобы модель не вернулась в код константой: там
    её меняют правкой и выкаткой, то есть не меняют вовсе.
    """

    def test_the_model_comes_from_the_settings(self):
        from django.conf import settings

        self.assertTrue(hasattr(settings, "SCAN_HEADER_MODEL"))

    def test_the_default_model_has_a_price(self):
        """
        Модель без цены к вызову не допускается вовсе — иначе расход считался
        бы по нулю, и это тихо снятый потолок. Настройка тут опаснее кода:
        опечатку в `.env` не увидит ни один обзор.
        """
        from django.conf import settings

        self.assertIsNotNone(prices.price_of(settings.SCAN_HEADER_MODEL))

    def test_every_reader_we_may_call_has_a_price(self):
        """
        Читателей стало трое, и цена нужна каждому: вызов без цены считался бы
        по нулю, то есть тихо снимал бы потолок. Список берётся из кода, а не
        переписывается сюда, — иначе четвёртый читатель прошёл бы молча.
        """
        for name in (prices.MATHPIX, prices.YANDEX):
            self.assertIn(name, prices.PER_REQUEST, name)


class TheCallToTheModelIsBoundedInTimeTests(SimpleTestCase):
    """
    Вызов модели обязан сдаваться быстро, если соединения нет.

    Стоило это пятисотой на первой же живой пачке. На контуре, откуда
    Anthropic не отвечает, пакеты не отбиваются, а **пропадают**: соединение
    не падает, а висит. Умолчания SDK — нет предела на connect и три
    повтора — превращали это в минуту внутри одного запроса, а воркера
    gunicorn убивают по таймауту. Страница отвечала `SystemExit`, то есть
    пятисотой, в которой ни слова о причине; и хуже всего, что запасной
    читатель, ради которого всё это заведено, до вызова не доживал.

    Сторож нужен затем, что умолчания возвращаются молча: строку легко
    упростить при следующей правке, а узнать об этом можно только с живой
    пачки на закрытом контуре.
    """

    def test_connecting_gives_up_in_seconds_not_minutes(self):
        with self.settings(ANTHROPIC_API_KEY="not-a-real-key"):
            made = client._client()

        self.assertIsNotNone(
            made.timeout.connect,
            "у соединения с моделью нет предела: на глухой сети запрос "
            "провисит до смерти воркера",
        )
        self.assertLessEqual(made.timeout.connect, 10)

    def test_the_retries_do_not_multiply_the_wait(self):
        """
        Повторы сами по себе полезны — они про 429 и 5xx, где сервер ответил.
        Опасны они вместе с долгим соединением: столько же ожиданий подряд.
        Предел на connect держит их в узде, но и число попыток должно быть
        обозримым.
        """
        with self.settings(ANTHROPIC_API_KEY="not-a-real-key"):
            made = client._client()

        self.assertLessEqual(made.max_retries * made.timeout.connect, 20)


class PriceTests(SchoolTestMixin, APITestCase):
    def test_the_cost_is_counted_in_millionths(self):
        # 1000 входных по $1/M и 100 выходных по $5/M
        self.assertEqual(cost_micros(HAIKU, 1000, 100), 1500)

    def test_an_unknown_model_is_refused(self):
        """Неизвестная цена — это тихо снятый потолок, поэтому отказ."""
        with self.assertRaises(ValueError):
            cost_micros("claude-something-new", 10, 10)

    def test_the_second_reader_is_priced_by_the_request(self):
        """
        Токенов у Mathpix нет вовсе: он продаётся запросами, сколько бы текста
        ни нашлось на картинке. Дверь при этом одна — считать расход двумя
        способами в двух местах значит завести два ответа на вопрос «сколько
        школа потратила».
        """
        self.assertEqual(cost_micros(prices.MATHPIX, 0, 0), 2_000)
        self.assertEqual(cost_micros(prices.MATHPIX, 9999, 9999), 2_000)


class BudgetTests(SchoolTestMixin, APITestCase):
    def spend(self, micros, *, user=None, when=None):
        row = AiSpend.objects.create(
            school=self.school,
            user=user or self.user,
            purpose=AiSpend.SCAN_HEADER,
            model=HAIKU,
            cost_micros=micros,
        )
        if when:
            AiSpend.objects.filter(pk=row.pk).update(created_at=when)
        return row

    def test_zero_means_no(self):
        """Школа без выставленного лимита не тратит: ноль это «нельзя»."""
        self.school.ai_month_limit_cents = 0
        self.school.save()

        with self.assertRaises(Exception) as caught:
            services.check_budget(self.school)
        self.assertEqual(caught.exception.detail["code"], "ai_budget_exceeded")

    def test_last_month_does_not_count(self):
        """Граница — календарный месяц, и кончается он сам."""
        self.school.ai_month_limit_cents = 1
        self.school.save()
        self.spend(1_000_000, when=timezone.now() - timedelta(days=40))

        self.assertEqual(services.spent_this_month(self.school), 0)
        services.check_budget(self.school)  # не поднимает

    def test_spending_up_to_the_limit_closes_the_door(self):
        self.school.ai_month_limit_cents = 1  # один цент = 10 000 микродолларов
        self.school.save()
        self.spend(10_000)

        with self.assertRaises(Exception):
            services.check_budget(self.school)


class BudgetApiTests(SchoolTestMixin, APITestCase):
    def test_the_administrator_sets_the_limit(self):
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            reverse("ai-budget"), {"limit_cents": 2500}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.ai_month_limit_cents, 2500)

    def test_a_teacher_only_looks(self):
        self.client.force_authenticate(self.user)

        self.assertEqual(self.client.get(reverse("ai-budget")).status_code, 200)
        refused = self.client.patch(
            reverse("ai-budget"), {"limit_cents": 999999}, format="json"
        )
        self.assertEqual(refused.json()["code"], "school_admin_required")

    def test_a_negative_limit_is_refused(self):
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            reverse("ai-budget"), {"limit_cents": -5}, format="json"
        )

        self.assertEqual(response.json()["code"], "ai_limit_negative")


class SpendLogTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        for who in (self.user, self.colleague):
            AiSpend.objects.create(
                school=self.school,
                user=who,
                purpose=AiSpend.SCAN_HEADER,
                model=SONNET,
                cost_micros=1234,
            )

    def test_the_teacher_sees_only_their_own(self):
        """Кто сколько потратил — вопрос администратора, а не коллеги."""
        self.client.force_authenticate(self.user)

        rows = self.client.get(reverse("ai-spend")).json()["rows"]

        self.assertEqual(len(rows), 1)

    def test_the_administrator_sees_the_whole_school(self):
        self.client.force_authenticate(self.admin)

        rows = self.client.get(reverse("ai-spend")).json()["rows"]

        self.assertEqual(len(rows), 2)

    def test_the_administrator_can_narrow_it_to_their_own(self):
        self.client.force_authenticate(self.admin)

        rows = self.client.get(reverse("ai-spend"), {"mine": "true"}).json()["rows"]

        self.assertEqual(rows, [])


class SecondReaderParseTests(SimpleTestCase):
    """
    Ответ Mathpix -> то же самое, что возвращает чтение моделью.

    Разбор проверяется отдельно от сети, потому что ломается он отдельно от
    сети: у второго читателя нет ни схемы ответа, ни инструмента с полями — он
    отдаёт текст, и весь смысл его свидетельства держится на том, что из этого
    текста мы вычитали.

    Форма ответа совпадает с моделью нарочно: сверять два чтения можно только
    тогда, когда они одной формы.
    """

    def test_the_printed_labels_split_the_name_row(self):
        """
        Печать на бланке и режет строку: `First name:` и `Surname:` стоят
        типографской краской, а рукописное лежит между ними.
        """
        reading = strip.reading_from(
            ["First name: Varvara Surname: Mironova Grade: 7B Date: 3.05.26"],
            reader="mathpix",
        )

        self.assertEqual(reading["first_name"], "Varvara")
        self.assertEqual(reading["surname"], "Mironova")
        self.assertEqual(reading["date"], "3.05.26")

    def test_the_marks_are_taken_from_the_labels_we_printed(self):
        """
        Подпись над плиткой режет текст на куски: что стоит после подписи, то и
        написано в её клетке. Это чтение, а не счёт клеток слева.
        """
        reading = strip.reading_from(["First name: Ann Surname: Lee", "Q1 3 Q2 1 Q15 2 Σ 6"], reader="mathpix")

        self.assertEqual(reading["values"][0], 3)
        self.assertEqual(reading["values"][1], 1)
        self.assertEqual(reading["values"][14], 2)
        self.assertEqual(reading["values"][15], 6)

    def test_an_empty_tile_says_nothing(self):
        """Пустая клетка не называется вовсе: её отсутствие и есть пустота."""
        reading = strip.reading_from(["Surname: Lee", "Q1 Q2 4 Q3"], reader="mathpix")

        self.assertIsNone(reading["values"][0])
        self.assertEqual(reading["values"][1], 4)
        self.assertIsNone(reading["values"][2])

    def test_two_numbers_in_one_tile_are_a_refusal(self):
        """
        Взять первое попавшееся значило бы выдать догадку за свидетельство — а
        свидетельство тут единственное, ради чего второй читатель заведён.
        """
        reading = strip.reading_from(["Surname: Lee", "Q1 3 5 Q2 1"], reader="mathpix")

        self.assertIsNone(reading["values"][0])
        self.assertEqual(reading["values"][1], 1)

    def test_latex_around_a_digit_is_still_a_digit(self):
        """Рукописное Mathpix отдаёт то текстом, то формулой. Цифра та же."""
        reading = strip.reading_from([r"Surname: Lee", r"Q1 $3$ Q2 \(1\)"], reader="mathpix")

        self.assertEqual(reading["values"][0], 3)
        self.assertEqual(reading["values"][1], 1)

    def test_without_the_printed_labels_two_words_are_the_name(self):
        """
        Подписей не нашлось — значит прочитано одно рукописное. Ошибиться в
        графах тут не страшно: сверяются чтения парой слов целиком.
        """
        reading = strip.reading_from(["Varvara Mironova"], reader="mathpix")

        self.assertEqual(
            agreement.words(reading["first_name"], reading["surname"]),
            agreement.words("Mironova", "Varvara"),
        )

    def test_the_name_row_is_kept_as_it_was_read(self):
        """
        Человеку показывают прочитанное, а не наш разбор его на графы: разбор
        мог и не сойтись, а бумага перед глазами.
        """
        reading = strip.reading_from(["First name: Ann Surname: Lee", "Q1 3"], reader="mathpix")

        self.assertIn("Ann", reading["text"])
        self.assertIn("Lee", reading["text"])

    def test_line_data_is_preferred_to_flat_text(self):
        """
        Строки с координатами лучше плоского текста: строка имени отделена от
        плиток самим распознавателем, а не нашей догадкой.
        """
        lines = mathpix.lines_of(
            {
                "text": "всё одной строкой",
                "line_data": [
                    {"text": "First name: Ann"},
                    {"text": "мусор", "included": False},
                    {"text": "Q1 3"},
                ],
            }
        )

        self.assertEqual(lines, ["First name: Ann", "Q1 3"])

    def test_no_line_data_is_not_a_refusal(self):
        """Половина ответа лучше отказа: плоский текст тоже читается."""
        self.assertEqual(mathpix.lines_of({"text": "Surname: Lee\nQ1 3"}), ["Surname: Lee", "Q1 3"])

    def test_without_keys_there_is_no_second_reader(self):
        """
        Ключей нет — второго читателя нет, и это законное состояние: пачка
        разбирается ровно так, как разбиралась до него.
        """
        with self.settings(MATHPIX_APP_ID="", MATHPIX_APP_KEY=""):
            self.assertFalse(mathpix.configured())
            self.assertEqual(mathpix.read_strip(b"picture")["error"], "not_configured")


class AgreementTests(SimpleTestCase):
    """
    Сошлись ли два чтения — и о чём вообще спорить.

    Смысл второго читателя весь здесь. Одна модель ошибается **молча**: на
    живой пачке «Denis» прочитался как «Misha» и ушёл Мише, у которого своя
    страница уже была. Двое молча ошибаются только вместе.

    Отвечает сверка не на вопрос «кто прав» — этого она знать не может, — а на
    вопрос «есть ли о чём спросить человека».
    """

    def test_the_same_name_is_no_argument(self):
        self.assertEqual(
            agreement.compare(
                {"first_name": "Varvara", "surname": "Mironova"},
                {"first_name": "varvara", "surname": "MIRONOVA"},
            ),
            [],
        )

    def test_the_fields_may_be_swapped(self):
        """
        В какую графу попало слово — не свидетельство: подписываются «фамилия
        имя», да и читатель может переставить графы. Это то же правило, по
        которому лист сверяется с составом курса накрест.
        """
        self.assertEqual(
            agreement.compare(
                {"first_name": "Mironova", "surname": "Varvara"},
                {"first_name": "Varvara", "surname": "Mironova"},
            ),
            [],
        )

    def test_a_different_name_is_the_whole_point(self):
        self.assertEqual(
            agreement.compare(
                {"first_name": "Denis", "surname": ""},
                {"first_name": "Misha", "surname": ""},
            ),
            ["name"],
        )

    def test_silence_is_not_an_objection(self):
        """
        Пустое поле значит «я этого не увидел», а не «там написано другое».
        Считай мы молчание спором, спорной оказалась бы каждая страница — а
        пометка, стоящая везде, не значит ничего.
        """
        self.assertEqual(
            agreement.compare(
                {"first_name": "Denis", "surname": "Orlov", "values": [3, None]},
                {"first_name": "", "surname": "", "values": [None, 2]},
            ),
            [],
        )

    def test_two_digits_in_one_cell_are_an_argument(self):
        self.assertEqual(
            agreement.compare({"values": [3, 1]}, {"values": [3, 2]}),
            ["cell:1"],
        )

    def test_a_reader_who_did_not_answer_does_not_argue(self):
        """Отказ второго читателя — это «меня не было», а не «там другое»."""
        self.assertEqual(
            agreement.compare(
                {"first_name": "Denis", "values": [3]},
                {"reader": "mathpix", "error": "unreachable"},
            ),
            [],
        )


class PretendsThereIsAKey:
    """
    Сделать вид, что ключ Anthropic у контура есть.

    Прогон обнуляет его целиком (`config/testing.py`), и это правильно: так
    случайный вызов упирается в отказ, а не в счёт. Но выбор читателя теперь
    спрашивает «есть ли чем звать» — и без ключа модель не предлагается вовсе,
    то есть тесты про двух читателей проверяли бы контур без модели.

    Подменяется поэтому **ответ на вопрос**, а не сам ключ. Разница
    существенная: поставь мы ключ, и тест, забывший подменить чтение, ушёл бы
    наружу за настоящие деньги — ровно то, чего обнуление избегает.
    """

    def pretend_key(self):
        from unittest.mock import patch

        patcher = patch.object(services.client, "configured", lambda: True)
        patcher.start()
        self.addCleanup(patcher.stop)


class TwoReadersTests(PretendsThereIsAKey, SchoolTestMixin, APITestCase):
    """
    Двое читают одну полоску, а деньги считаются по-прежнему в одном месте.

    Проверяется здесь не распознавание — его без живой пачки не проверить
    никак, — а **устройство**: кому показали чужой ответ, кого позвали третьим
    и что записалось в журнал трат. Ровно эти три вещи и ломаются молча.

    Читатели подменены оба: настоящий вызов стоил бы денег на каждом прогоне,
    а прогонов четыре шарда в CI и ночью (CLAUDE.md, «Живые запросы к
    Anthropic»).
    """

    def setUp(self):
        super().setUp()
        # Ключ Anthropic обнулён на весь прогон (`config/testing.py`), а выбор
        # читателя теперь на него смотрит: без ключа модель не предлагается
        # вовсе. Подменяем именно ответ «ключ есть», а не сам ключ — иначе
        # тест, у которого чтение не подменено, ушёл бы наружу за деньги.
        self.pretend_key()
        self.seen = []
        self.model_says = {
            "first_name": "Denis",
            "surname": "Orlov",
            "date": "",
            "guess": "",
            "values": [3] + [None] * 15,
        }
        self.mathpix_says = {
            "reader": "mathpix",
            "first_name": "Denis",
            "surname": "Orlov",
            "date": "",
            "values": [3] + [None] * 15,
            "text": "Denis Orlov",
        }

    def read(self, **settings_over):
        """Прочитать одну страницу подменёнными читателями."""
        from unittest.mock import patch

        def reader(image, **kwargs):
            self.seen.append(kwargs)
            return dict(self.model_says), 100, 10

        defaults = {"MATHPIX_APP_ID": "id", "MATHPIX_APP_KEY": "key"}
        with self.settings(**(defaults | settings_over)):
            with patch.object(services, "read_header", reader), patch.object(
                services.mathpix, "read_strip", lambda *a, **k: dict(self.mathpix_says)
            ):
                return services.read_and_charge(
                    school=self.school,
                    user=self.user,
                    work=None,
                    image=b"strip",
                )

    def purposes(self):
        return sorted(AiSpend.objects.values_list("purpose", flat=True))

    def test_agreement_costs_two_readings_and_no_argument(self):
        """
        Сошлись — спорить не о чем, и третьего звать незачем. Странице после
        этого можно верить сильнее: двое молча ошибаются только вместе.
        """
        data = self.read()

        self.assertEqual(data["second"]["differs"], [])
        self.assertEqual(self.purposes(), ["scan_header", "scan_second"])
        self.assertEqual(len(self.seen), 1)

    def test_the_first_readers_are_never_told_what_the_other_saw(self):
        """
        Закон проекта выведен дважды и дорого: подсказанное подставляется
        вместо увиденного. Подскажи мы модели ответ второго читателя — их
        согласие перестало бы значить что-либо, а вместе с ним и вся затея.

        Стережётся это **подписью функции**, а не вызовом: пока чужому чтению
        неоткуда взяться, подсказать его нельзя даже по недосмотру. Раньше
        параметр был — им пользовался арбитр, — и тогда закон держался на том,
        что первым двум читателям его не передают.
        """
        from inspect import signature

        forbidden = {"rivals", "second", "other", "reading", "readings"}
        self.assertEqual(
            forbidden & set(signature(client.read_header).parameters),
            set(),
            "у чтения появился параметр под чужой ответ — подсказка вернулась",
        )
        self.read()
        self.assertEqual(len(self.seen), 1)

    def test_the_name_is_taken_from_the_model(self):
        """
        Имя читает модель, и спор об имени решается в её пользу.

        Знание это про читателей, а не про страницу: распознаватель видит
        буквы по одной и на рукописной фамилии ошибается заметно чаще, а модель
        знает, что перед ней имя, и держит слово целиком. Поэтому правило
        отвечает точнее, чем третье чтение, — и не стоит ничего.
        """
        self.mathpix_says["surname"] = "Orlova"

        data = self.read()

        self.assertEqual(data["surname"], "Orlov")
        # ...но человеку о споре всё равно сказано: правило говорит, чья
        # версия правдоподобнее, а не что модель непогрешима
        self.assertEqual(data["second"]["differs"], ["name"])

    def test_the_cells_are_taken_from_the_recogniser(self):
        """
        Клетки читает распознаватель, и спор о клетке решается в его пользу.

        Плитки — это таблица, а цифра в квадратике требует зрения, не
        понимания: модель на них сбивается со счёта и путает соседние клетки,
        распознаватель — нет.
        """
        self.mathpix_says["values"] = [7] + [None] * 15

        data = self.read()

        self.assertEqual(data["values"][0], 7)
        self.assertEqual(data["second"]["differs"], ["cell:0"])

    def test_nobody_is_called_a_third_time(self):
        """
        Арбитра больше нет, и это осознанная потеря.

        Он перечитывал спорную страницу дорогой моделью; правило же отвечает
        на тот же вопрос точнее — потому что опирается не на догадку о
        странице, а на знание о читателях, — и бесплатно. Сторож нужен затем,
        чтобы третье чтение не вернулось «на всякий случай»: цена ему пачка
        спорных страниц, а польза с появлением приоритета исчезла.
        """
        self.mathpix_says["first_name"] = "Misha"

        data = self.read()

        self.assertEqual(data["second"]["differs"], ["name"])
        self.assertEqual(len(self.seen), 1)
        self.assertEqual(self.purposes(), ["scan_header", "scan_second"])

    def test_silence_does_not_rub_out_a_mark_someone_did_read(self):
        """
        Хозяин клеток — распознаватель, но не любой ценой.

        Он не разбирает половину плиток на бледном скане, и его молчание — это
        «я не увидел», а не «там пусто». Стирай оно прочитанное другим, и
        приоритет работал бы против той самой точности, ради которой заведён.
        """
        self.model_says["values"] = [3, 4] + [None] * 14
        self.mathpix_says["values"] = [None, 4] + [None] * 14

        data = self.read()

        self.assertEqual(data["values"][0], 3)
        self.assertEqual(data["values"][1], 4)

    def test_the_human_may_refuse_the_second_reader(self):
        """
        Галочка на шаге выбора файла: второй читатель удваивает цену пачки, а
        нужен он не всегда — у стопки, где имена вписаны учителем печатными
        буквами, спорить не о чем. Решает тот, кто платит.
        """
        from unittest.mock import patch

        with self.settings(MATHPIX_APP_ID="id", MATHPIX_APP_KEY="key"):
            with patch.object(
                services, "read_header", lambda image, **kw: (dict(self.model_says), 100, 10)
            ), patch.object(
                services.mathpix, "read_strip", self.fail_if_called
            ):
                data = services.read_and_charge(
                    school=self.school,
                    user=self.user,
                    work=None,
                    image=b"strip",
                    asked_second=False,
                )

        self.assertEqual(data["second"]["error"], "not_asked")
        self.assertEqual(self.purposes(), ["scan_header"])

    def fail_if_called(self, *args, **kwargs):
        self.fail("второго читателя позвали, хотя человек его снял")

    def test_why_there_is_no_second_opinion_is_said_in_words(self):
        """
        Причин «второго мнения нет» несколько, и они разные: не просили, нечем
        звать, нечем платить, не ответил. Общий пустой словарь на все случаи
        сделал бы снятую галочку и отвалившийся сервис неразличимыми на экране.
        """
        from unittest.mock import patch

        with self.settings(MATHPIX_APP_ID="", MATHPIX_APP_KEY=""):
            with patch.object(
                services, "read_header", lambda image, **kw: (dict(self.model_says), 100, 10)
            ):
                data = services.read_and_charge(
                    school=self.school, user=self.user, work=None, image=b"strip"
                )

        self.assertEqual(data["second"]["error"], "not_configured")

    def test_a_reader_who_did_not_answer_is_not_charged(self):
        """
        Отказ второго читателя не отменяет чтения и не стоит денег: страница
        читается ровно так, как читалась до него.
        """
        from unittest.mock import patch

        with self.settings(MATHPIX_APP_ID="id", MATHPIX_APP_KEY="key"):
            with patch.object(
                services, "read_header", lambda image, **kw: (dict(self.model_says), 100, 10)
            ), patch.object(
                services.mathpix,
                "read_strip",
                lambda *a, **k: {"reader": "mathpix", "error": "unreachable"},
            ):
                data = services.read_and_charge(
                    school=self.school, user=self.user, work=None, image=b"strip"
                )

        self.assertEqual(data["second"]["error"], "unreachable")
        # Спора нет и быть не может: спорить не с кем. Пустой список тут
        # означал бы «сверили и сошлись», то есть уверенность, которой не было.
        self.assertNotIn("differs", data["second"])
        self.assertEqual(self.purposes(), ["scan_header"])

    def test_the_extras_stop_at_the_ceiling_instead_of_refusing(self):
        """
        Потолок кончился — прибавок не будет, но уже сделанное чтение доедет.
        Отказ здесь стоил бы страницы, за которую уже заплачено.
        """
        self.school.ai_month_limit_cents = 1
        self.school.save()
        AiSpend.objects.create(
            school=self.school, user=self.user, purpose=AiSpend.SCAN_HEADER,
            model=HAIKU, cost_micros=10_000,
        )

        with self.assertRaises(Exception):
            self.read()  # главное чтение отказывает честно
        self.assertEqual(self.purposes(), ["scan_header"])


class ThirdReaderTests(SimpleTestCase):
    """
    Yandex Vision OCR — ещё один читатель той же полоски.

    Форму его ответа мы **не видели живьём**: запрос стоит денег, и правило
    CLAUDE.md про это прямое. Отсюда и предмет проверки — не распознавание, а
    терпимость к форме: неожиданный ключ обязан кончаться словом «не понял», а
    не пятисотой и не пустой шапкой, свалившей чужую беду на бумагу.
    """

    def answer(self, payload):
        """Ответить на запрос вот таким телом, никуда не ходя."""
        import io
        import json as js
        from contextlib import contextmanager
        from unittest.mock import patch

        @contextmanager
        def urlopen(request, timeout=None):
            yield io.BytesIO(js.dumps(payload).encode())

        with self.settings(YANDEX_OCR_API_KEY="key"):
            with patch.object(yandex.urllib.request, "urlopen", urlopen):
                return yandex.read_strip(b"picture")

    def test_without_a_key_there_is_no_reader(self):
        """Отказ, а не исключение: решает вызывающий, мы только сообщаем."""
        with self.settings(YANDEX_OCR_API_KEY=""):
            self.assertFalse(yandex.configured())
            self.assertEqual(yandex.read_strip(b"picture")["error"], "not_configured")

    def test_lines_come_from_the_blocks(self):
        lines = yandex.lines_of(
            {
                "result": {
                    "textAnnotation": {
                        "blocks": [
                            {"lines": [{"text": "First name: Ann Surname: Lee"}]},
                            {"lines": [{"text": "Q1 3 Q2 1"}]},
                        ]
                    }
                }
            }
        )

        self.assertEqual(lines, ["First name: Ann Surname: Lee", "Q1 3 Q2 1"])

    def test_flat_text_is_better_than_nothing(self):
        """
        Разложенных строк может не оказаться — тогда берём сплошной текст.
        Половина ответа лучше отказа, и это то же решение, что у Mathpix.
        """
        lines = yandex.lines_of(
            {"result": {"textAnnotation": {"fullText": "Surname: Lee\nQ1 3"}}}
        )

        self.assertEqual(lines, ["Surname: Lee", "Q1 3"])

    def test_a_shape_we_do_not_know_is_not_a_crash(self):
        for payload in ({}, {"result": None}, {"result": {"textAnnotation": []}}):
            self.assertEqual(yandex.lines_of(payload), [], payload)

    def test_an_answer_we_cannot_read_says_so(self):
        """
        Двухсотый с пустым разбором — это «мы не поняли ответ», а не «на бумаге
        пусто». Пустая шапка тут свалила бы на скан чужую беду, и учитель искал
        бы причину в сканере.
        """
        self.assertEqual(self.answer({"result": {}})["error"], "unreadable")

    def test_the_reading_has_the_same_shape_as_everyone_elses(self):
        """
        Сверять два чтения можно только тогда, когда они одинаковой формы.
        Разъехавшись, читатели потребовали бы третьего места, где форма живёт,
        — а `agreement.compare` знает ровно одну.
        """
        reading = self.answer(
            {
                "result": {
                    "textAnnotation": {
                        "blocks": [
                            {"lines": [{"text": "First name: Ann Surname: Lee"}]},
                            {"lines": [{"text": "Q1 3 Σ 3"}]},
                        ]
                    }
                }
            }
        )

        self.assertEqual(reading["reader"], "yandex")
        self.assertEqual(reading["first_name"], "Ann")
        self.assertEqual(reading["surname"], "Lee")
        self.assertEqual(reading["values"][0], 3)
        self.assertEqual(reading["values"][15], 3)
        self.assertEqual(
            sorted(reading),
            sorted(strip.reading_from(["First name: Ann"], reader="mathpix")),
        )

    def test_the_third_reader_is_priced_by_the_request_too(self):
        """Как и Mathpix: страница, а не токены. Дверь подсчёта одна."""
        self.assertEqual(cost_micros(prices.YANDEX, 0, 0), 1_300)
        self.assertEqual(cost_micros(prices.YANDEX, 9999, 9999), 1_300)


class WhatCountsAsOutOfReachTests(SimpleTestCase):
    """
    Четыре отказа SDK, и только три из них значат «не достучаться».

    Различие тут не вкусовое. «Не достучаться» переводит контур на запасного
    читателя — молча и надолго; значит всё, что попало в эту графу по ошибке,
    оборачивается ослабленным чтением, о котором никто не просил. Опечатка в
    ключе — самый вероятный кандидат: она выглядит как отказ сервера и
    случается ровно в тот день, когда ключ меняли.
    """

    def call(self, error):
        """Позвать модель, у которой вместо ответа — вот такой отказ."""
        from unittest.mock import patch

        class Messages:
            def create(self, **kwargs):
                raise error

        class Fake:
            messages = Messages()

        with patch.object(client, "_client", lambda: Fake()):
            return client._ask(model="m", max_tokens=1, messages=[])

    def sdk(self):
        import anthropic
        import httpx

        return anthropic, httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    def test_a_dropped_connection_means_out_of_reach(self):
        anthropic, request = self.sdk()
        with self.assertRaises(client.ModelUnreachable):
            self.call(anthropic.APIConnectionError(request=request))

    def test_a_timeout_is_the_same_thing(self):
        """
        Блокировка чаще выглядит не отказом, а молчанием: пакеты уходят и не
        возвращаются. Таймаут — частный случай отказа связи, и ловится тем же
        `except`; проверяем, потому что иначе это знание живёт в чужой
        библиотеке.
        """
        anthropic, request = self.sdk()
        with self.assertRaises(client.ModelUnreachable):
            self.call(anthropic.APITimeoutError(request=request))

    def test_a_country_block_answers_403_and_still_means_out_of_reach(self):
        """
        Сервер ответил — но ответил, что разговора не будет. Снаружи это
        «связь есть», и без этой ветки контур считал бы модель доступной,
        получая 403 на каждой странице пачки.
        """
        import httpx

        anthropic, request = self.sdk()
        with self.assertRaises(client.ModelUnreachable):
            self.call(
                anthropic.PermissionDeniedError(
                    "unsupported country",
                    response=httpx.Response(403, request=request),
                    body=None,
                )
            )

    def test_a_wrong_key_stays_a_wrong_key(self):
        """
        401 — это ошибка настройки, и она обязана быть громкой. Прими мы её за
        блокировку, опечатка в ключе тихо и навсегда оставила бы школу с
        одним распознавателем вместо двух читателей, а искать причину пришлось
        бы в стране размещения сервера.
        """
        import httpx

        anthropic, request = self.sdk()
        with self.assertRaises(anthropic.AuthenticationError):
            self.call(
                anthropic.AuthenticationError(
                    "bad key",
                    response=httpx.Response(401, request=request),
                    body=None,
                )
            )


class ModelOutOfReachTests(PretendsThereIsAKey, SchoolTestMixin, APITestCase):
    """
    Сервер, который не достаёт до модели, обязан всё равно прочитать пачку.

    Случай не выдуманный: контур стоит там, откуда Anthropic не отвечает, а
    ключ у него настоящий. Ни одна настройка об этом не говорит — узнаётся это
    попыткой, и до того, как путь появился, выглядело оно как пятисотая на
    каждой странице.

    Проверяется не распознавание, а **развилка**: кого позвали вместо модели,
    что записали в журнал, и не пришлось ли пачке из тридцати четырёх листов
    выяснять недоступность тридцать четыре раза подряд.
    """

    def setUp(self):
        super().setUp()
        self.pretend_key()
        # Вердикт живёт в кэше и переживает тест: непочищенный, он красит
        # следующий тест в зелёный по неверной причине.
        reach.forget()
        self.addCleanup(reach.forget)
        self.asked = []
        self.mathpix_says = {
            "reader": "mathpix",
            "first_name": "Denis",
            "surname": "Orlov",
            "date": "",
            "values": [3] + [None] * 15,
            "text": "Denis Orlov",
        }

    def read(self, *, strip=None, **settings_over):
        """Прочитать страницу на контуре, который до модели не достаёт."""
        from unittest.mock import patch

        def blocked(image, **kwargs):
            self.asked.append(kwargs)
            raise client.ModelUnreachable("blocked")

        says = self.mathpix_says if strip is None else strip
        defaults = {"MATHPIX_APP_ID": "id", "MATHPIX_APP_KEY": "key"}
        with self.settings(**(defaults | settings_over)):
            with patch.object(services, "read_header", blocked), patch.object(
                services.mathpix, "read_strip", lambda *a, **k: dict(says)
            ):
                return services.read_and_charge(
                    school=self.school,
                    user=self.user,
                    work=None,
                    image=b"strip",
                )

    def purposes(self):
        return sorted(AiSpend.objects.values_list("purpose", flat=True))

    def test_a_server_without_a_model_reads_with_what_it_has(self):
        """«Хуже» спорит здесь не с «лучше», а с «никак»."""
        data = self.read()

        self.assertEqual(data["first_name"], "Denis")
        self.assertEqual(data["surname"], "Orlov")
        self.assertEqual(data["model"], prices.MATHPIX)

    def test_the_reading_is_charged_as_a_header_by_whoever_read_it(self):
        """
        Повод отвечает на вопрос «за что заплачено», а заплачено за чтение
        шапки. Кем именно — сказано в `model`, и по нему в журнале видно, что
        читал не тот, кто обычно.
        """
        self.read()

        self.assertEqual(self.purposes(), ["scan_header"])
        row = AiSpend.objects.get()
        self.assertEqual(row.model, prices.MATHPIX)
        self.assertEqual(row.cost_micros, prices.PER_REQUEST[prices.MATHPIX])

    def test_the_missing_second_opinion_says_why_it_is_missing(self):
        """
        Пустой словарь значил бы «второй читатель промолчал» — то есть свалил
        бы на него отсутствующую модель. Слово тут своё: имя читал тот же, кто
        читал бы клетки, и звать его второй раз значило бы заплатить дважды за
        один и тот же ответ.
        """
        self.assertEqual(self.read()["second"]["error"], "same_reader")

    def test_the_pile_finds_out_once_and_not_on_every_page(self):
        """
        Тридцать четыре страницы по три попытки с таймаутом — это не «медленно»,
        это чтение, неотличимое от зависшего. Спросить один раз — то же самое
        знание, только вовремя.
        """
        self.read()
        self.read()

        self.assertEqual(len(self.asked), 1)
        self.assertFalse(reach.model_reachable())

    def test_with_no_other_reader_the_refusal_says_so(self):
        """
        Отказ, а не пустая страница: «шапки не разобрать» свалило бы на бумагу
        вину сети, и учитель искал бы причину в сканере.
        """
        with self.assertRaises(Exception) as caught:
            self.read(MATHPIX_APP_ID="", MATHPIX_APP_KEY="")

        self.assertEqual(caught.exception.detail["code"], "ai_unreachable")
        self.assertEqual(self.purposes(), [])

    def test_the_only_reader_going_silent_is_not_an_empty_page(self):
        """
        У второго читателя молчание — законное состояние, у единственного —
        непрочитанная страница. Роль изменилась, значит изменился и ответ.

        Код при этом называет **первую** беду: до модели не достучались, и
        подменить её оказалось некем. Назови мы вторую, человек чинил бы
        распознаватель, не зная, что его позвали только из-за закрытой сети.
        """
        with self.assertRaises(Exception) as caught:
            self.read(strip={"reader": "mathpix", "error": "unreachable"})

        self.assertEqual(caught.exception.detail["code"], "ai_unreachable")
        self.assertEqual(self.purposes(), [])

    def test_a_contour_with_nothing_set_up_says_so_the_old_way(self):
        """
        Ни ключа, ни распознавателей — это «не настроено», а не «не
        достучаться»: достукиваться не до чего.

        Разница не словесная, и стоила она красного прогона. Контур без ключей
        отвечал `ai_key_missing` с первого дня, и на этой фразе стоит
        браузерный тест: человеку, который просто не вписал ключ, «сеть
        закрыта» отправило бы искать несуществующую беду.
        """
        from unittest.mock import patch

        with patch.object(services.client, "configured", lambda: False):
            with self.assertRaises(Exception) as caught:
                self.read(MATHPIX_APP_ID="", MATHPIX_APP_KEY="")

        self.assertEqual(caught.exception.detail["code"], "ai_key_missing")

    def test_a_reader_that_simply_did_not_answer_says_that_instead(self):
        """
        Модель в этой беде не участвовала: ключа у контура нет вовсе, читатель
        был один и промолчал. Отказ поэтому другой — чинить надо не сеть, а
        повторить страницу.
        """
        from unittest.mock import patch

        with patch.object(services.client, "configured", lambda: False):
            with self.assertRaises(Exception) as caught:
                self.read(strip={"reader": "mathpix", "error": "unreachable"})

        self.assertEqual(caught.exception.detail["code"], "scan_reader_silent")
