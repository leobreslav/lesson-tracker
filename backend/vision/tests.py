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

from . import agreement, client, mathpix, services
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

    def test_the_arbiter_has_a_price_too(self):
        """
        Арбитра зовут по спорным страницам, и цена ему нужна такая же. Пустая
        настройка — законное состояние: «не перечитывать».
        """
        from django.conf import settings

        arbiter = getattr(settings, "SCAN_ARBITER_MODEL", "")
        if arbiter:
            self.assertTrue(prices.known(arbiter))


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
        self.assertEqual(cost_micros(prices.MATHPIX, 0, 0), 4_000)
        self.assertEqual(cost_micros(prices.MATHPIX, 9999, 9999), 4_000)


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
        reading = mathpix.reading_from(
            ["First name: Varvara Surname: Mironova Grade: 7B Date: 3.05.26"]
        )

        self.assertEqual(reading["first_name"], "Varvara")
        self.assertEqual(reading["surname"], "Mironova")
        self.assertEqual(reading["date"], "3.05.26")

    def test_the_marks_are_taken_from_the_labels_we_printed(self):
        """
        Подпись над плиткой режет текст на куски: что стоит после подписи, то и
        написано в её клетке. Это чтение, а не счёт клеток слева.
        """
        reading = mathpix.reading_from(["First name: Ann Surname: Lee", "Q1 3 Q2 1 Q15 2 Σ 6"])

        self.assertEqual(reading["values"][0], 3)
        self.assertEqual(reading["values"][1], 1)
        self.assertEqual(reading["values"][14], 2)
        self.assertEqual(reading["values"][15], 6)

    def test_an_empty_tile_says_nothing(self):
        """Пустая клетка не называется вовсе: её отсутствие и есть пустота."""
        reading = mathpix.reading_from(["Surname: Lee", "Q1 Q2 4 Q3"])

        self.assertIsNone(reading["values"][0])
        self.assertEqual(reading["values"][1], 4)
        self.assertIsNone(reading["values"][2])

    def test_two_numbers_in_one_tile_are_a_refusal(self):
        """
        Взять первое попавшееся значило бы выдать догадку за свидетельство — а
        свидетельство тут единственное, ради чего второй читатель заведён.
        """
        reading = mathpix.reading_from(["Surname: Lee", "Q1 3 5 Q2 1"])

        self.assertIsNone(reading["values"][0])
        self.assertEqual(reading["values"][1], 1)

    def test_latex_around_a_digit_is_still_a_digit(self):
        """Рукописное Mathpix отдаёт то текстом, то формулой. Цифра та же."""
        reading = mathpix.reading_from([r"Surname: Lee", r"Q1 $3$ Q2 \(1\)"])

        self.assertEqual(reading["values"][0], 3)
        self.assertEqual(reading["values"][1], 1)

    def test_without_the_printed_labels_two_words_are_the_name(self):
        """
        Подписей не нашлось — значит прочитано одно рукописное. Ошибиться в
        графах тут не страшно: сверяются чтения парой слов целиком.
        """
        reading = mathpix.reading_from(["Varvara Mironova"])

        self.assertEqual(
            agreement.words(reading["first_name"], reading["surname"]),
            agreement.words("Mironova", "Varvara"),
        )

    def test_the_name_row_is_kept_as_it_was_read(self):
        """
        Человеку показывают прочитанное, а не наш разбор его на графы: разбор
        мог и не сойтись, а бумага перед глазами.
        """
        reading = mathpix.reading_from(["First name: Ann Surname: Lee", "Q1 3"])

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


class TwoReadersTests(SchoolTestMixin, APITestCase):
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
        self.arbiter_says = {
            "first_name": "Denis",
            "surname": "Orlov",
            "date": "",
            "guess": "",
            "values": [2] + [None] * 15,
        }

    def read(self, **settings_over):
        """Прочитать одну страницу подменёнными читателями."""
        from unittest.mock import patch

        def reader(image, **kwargs):
            self.seen.append(kwargs)
            answer = self.arbiter_says if kwargs.get("rivals") else self.model_says
            return dict(answer), 100, 10

        defaults = {
            "MATHPIX_APP_ID": "id",
            "MATHPIX_APP_KEY": "key",
            "SCAN_ARBITER_MODEL": SONNET,
        }
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
        """
        self.read()

        self.assertIsNone(self.seen[0].get("rivals"))

    def test_a_disagreement_calls_a_third_reader(self):
        """Спор решает не большинство и не мы, а тот, кто ещё раз посмотрит."""
        self.mathpix_says["surname"] = "Orlova"

        data = self.read()

        self.assertEqual(data["second"]["differs"], ["name"])
        self.assertEqual(len(self.seen), 2)
        self.assertEqual(self.seen[1]["model"], SONNET)
        # арбитр увидел обе версии — и ни одна не названа правой
        self.assertEqual(len(self.seen[1]["rivals"]), 2)
        # ...и его чтение стало чтением страницы
        self.assertEqual(data["values"][0], 2)
        self.assertEqual(self.purposes(), ["scan_header", "scan_reread", "scan_second"])

    def test_the_argument_survives_the_arbiter(self):
        """
        Пометка ставится **до** арбитража и потом не пересчитывается. Иначе она
        исчезала бы ровно тогда, когда арбитр встал на сторону второго
        читателя: чтение сошлось бы с ним, и страница, о которой спорили трое,
        выглядела бы бесспорной.
        """
        self.mathpix_says["values"] = [2] + [None] * 15  # арбитр придёт к тому же
        data = self.read()

        self.assertEqual(data["second"]["differs"], ["cell:0"])
        self.assertEqual(data["values"][0], 2)

    def test_without_an_arbiter_the_argument_is_only_marked(self):
        """
        Пустая настройка — честный выбор школы, у которой каждая страница стоит
        денег: расхождение помечается, а решает его человек.
        """
        self.mathpix_says["first_name"] = "Misha"

        data = self.read(SCAN_ARBITER_MODEL="")

        self.assertEqual(data["second"]["differs"], ["name"])
        self.assertEqual(len(self.seen), 1)
        self.assertEqual(self.purposes(), ["scan_header", "scan_second"])

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
        self.assertEqual(data["second"]["differs"], [])
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
