"""
Применение разобранной пачки: страницы ученикам, клетки в оценки.

Проверяется то, что нельзя увидеть по частям: применение либо случилось
целиком, либо не случилось вовсе. Половина применённой пачки — это часть
класса с работами и оценками, а часть без, и какая именно, снаружи не видно.
"""

from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from files.models import Attachment
from rest_framework.test import APITestCase
from schools.services import enrol
from vision.models import AiSpend
from schools.testing import (
    SchoolTestMixin,
    make_course,
    make_user,
    make_work,
    make_year,
)

from . import services
from .models import Mark, ScanPage, StudentWork
from .test_splitting import book


class ScanApplyTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        services.set_questions(
            self.work,
            [{"question": f"Задача {n}", "maximum": 3} for n in range(1, 4)],
            by=self.user,
        )

        self.student.first_name, self.student.last_name = "Fil", "Burmov"
        self.student.save()
        self.second = make_user(self.school, "second@example.com", student=True)
        self.second.first_name, self.second.last_name = "Peter", "Tibora"
        self.second.save()
        enrol(self.student, self.course, by=self.admin)
        enrol(self.second, self.course, by=self.admin)

        self.client.force_authenticate(self.user)

    def read(self, index, first, surname, marks):
        cells = [None] * 16
        for question, value in marks.items():
            cells[question] = value
        services.save_scan_reading(
            self.work,
            index=index,
            fingerprint=f"f{index}",
            data={"first_name": first, "surname": surname, "values": cells},
        )

    def apply(self, pages=2):
        return self.client.post(
            reverse("work-scan-apply", args=[self.work.pk]),
            {"file": SimpleUploadedFile("scan.pdf", book(pages))},
            format="multipart",
        )

    def test_a_scan_that_would_change_a_standing_mark_says_so_first(self):
        """
        Молча переписать поставленное нельзя — об этом спрашивают человека.

        Прежний балл мог прийти откуда угодно: с проверки онлайн-ответа или
        с прошлого разбора той же пачки. Оба числа показываются, а решение
        остаётся за тем, кто нажимает «Записать всё».
        """
        row, _ = StudentWork.objects.get_or_create(
            work=self.work, student=self.student
        )
        first_task = self.work.tasks.order_by("position").first()
        Mark.objects.create(student_work=row, task=first_task, value=3)

        self.read(0, "Fil", "Burmov", {0: 1})
        state = self.client.get(
            reverse("work-scan-state", args=[self.work.pk])
        ).json()

        packet = next(p for p in state["packets"] if p["student"] == self.student.pk)
        self.assertIn("mark_differs", packet["trouble"])
        # вопрос назван так, как его зовёт работа: пусто в `label` значит
        # «зовусь номером по порядку», и это строка, а не число — иначе
        # переименованный вопрос («1а») выпал бы из типа
        self.assertEqual(
            packet["overwrites"], [{"question": "1", "was": 3, "now": 1}]
        )

    def test_the_same_mark_read_again_is_not_a_doubt(self):
        """
        Повторный разбор той же пачки — обычное дело.

        «Было 3, пришло 3» пятнадцатью строками превратило бы список
        сомнений в шум, а сомнением это не является вовсе.
        """
        row, _ = StudentWork.objects.get_or_create(
            work=self.work, student=self.student
        )
        first_task = self.work.tasks.order_by("position").first()
        Mark.objects.create(student_work=row, task=first_task, value=3)

        self.read(0, "Fil", "Burmov", {0: 3})
        state = self.client.get(
            reverse("work-scan-state", args=[self.work.pk])
        ).json()

        packet = next(p for p in state["packets"] if p["student"] == self.student.pk)
        self.assertEqual(packet["overwrites"], [])
        self.assertNotIn("mark_differs", packet["trouble"])

    def test_pages_become_attachments_and_cells_become_marks(self):
        self.read(0, "Fil", "Burmov", {0: 3, 1: 1})
        self.read(1, "Peter", "Tibora", {0: 2})

        response = self.apply()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["students"], 2)
        mine = StudentWork.objects.get(work=self.work, student=self.student)
        self.assertEqual(Attachment.objects.filter(student_work=mine).count(), 1)
        self.assertEqual(
            sorted(Mark.objects.filter(student_work=mine).values_list("value", flat=True)),
            [1, 3],
        )

    def test_two_pages_of_one_student_go_into_one_file(self):
        """Работа это один кусок, сколько бы листов она ни заняла."""
        self.read(0, "Fil", "Burmov", {0: 3})
        self.read(1, "", "", {2: 2})

        self.apply()

        mine = StudentWork.objects.get(work=self.work, student=self.student)
        self.assertEqual(Attachment.objects.filter(student_work=mine).count(), 1)
        self.assertEqual(
            sorted(Mark.objects.filter(student_work=mine).values_list("value", flat=True)),
            [2, 3],
        )

    def test_conditions_go_into_the_students_file(self):
        """
        Листы условий едут в PDF вместе с решением.

        Иначе ученик открывает свои ответы без вопросов — половину документа,
        — а ради того, чтобы он видел работу целиком, скан ему и отдают.
        """
        services.mark_headerless(self.work, index=0)
        self.read(1, "Fil", "Burmov", {0: 3})
        services.mark_headerless(self.work, index=2)
        self.read(3, "Peter", "Tibora", {0: 2})

        response = self.apply(pages=4)

        self.assertEqual(response.status_code, 200)
        mine = StudentWork.objects.get(work=self.work, student=self.student)
        paper = Attachment.objects.get(student_work=mine)
        from io import BytesIO

        from files import storage
        from pypdf import PdfReader

        with storage.backend().open(paper.stored_file.key) as fp:
            self.assertEqual(len(PdfReader(BytesIO(fp.read())).pages), 2)

    def test_the_rows_are_gone_once_it_is_applied(self):
        """Работа сделана: дальше про неё отвечают вложения и оценки."""
        self.read(0, "Fil", "Burmov", {0: 3})

        self.apply()

        self.assertFalse(ScanPage.objects.filter(work=self.work).exists())

    def test_a_page_outside_the_file_stops_everything(self):
        """Прочитали больше страниц, чем прислали, — не применяем ничего."""
        self.read(0, "Fil", "Burmov", {0: 3})
        self.read(5, "Peter", "Tibora", {0: 1})

        response = self.apply(pages=2)

        self.assertEqual(response.json()["code"], "split_out_of_range")
        self.assertFalse(Attachment.objects.filter(student_work__work=self.work).exists())
        self.assertTrue(ScanPage.objects.filter(work=self.work).exists())

    def test_nothing_read_is_refused(self):
        response = self.apply()

        self.assertEqual(response.json()["code"], "scan_nothing_read")

    def test_a_human_decision_survives_into_the_marks(self):
        """Сказали «эта страница Петра» — баллы уходят ему, а не тому, чьё имя."""
        self.read(0, "Fil", "Burmov", {0: 3})
        self.client.post(
            reverse("work-scan-page", args=[self.work.pk]),
            {"index": 0, "student": self.second.pk},
            format="json",
        )

        self.apply()

        theirs = StudentWork.objects.get(work=self.work, student=self.second)
        self.assertEqual(
            list(Mark.objects.filter(student_work=theirs).values_list("value", flat=True)),
            [3],
        )
        self.assertFalse(
            StudentWork.objects.filter(work=self.work, student=self.student).exists()
        )

    def test_a_work_with_online_tasks_opens_the_scan_wizard_too(self):
        """
        Отказ «эта работа не на бумаге» снят: обычный случай он и запирал.

        Класс писал онлайн, а сдал на бумаге; или работу завели пустой и
        принесли пачку. Флаг требовал решить это **заранее**, когда ещё
        неизвестно, чем работа окажется.
        """
        online = make_work(self.user, self.course)

        response = self.client.get(reverse("work-scan-state", args=[online.pk]))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["pages"], [])


class ScanSpendTests(SchoolTestMixin, APITestCase):
    """
    Во что обошлась пачка — вопрос отдельный от школьного потолка.

    Потолок отвечает «сколько школа потратила за месяц», и на него смотрит
    администратор. Учитель со стопкой в руках спрашивает другое: сколько
    стоило вот это чтение. Считать ему сумму за всю историю работы нельзя —
    одну и ту же работу разбирают повторно, пересняв пачку, — поэтому счёт
    идёт от начала нынешней пачки, а началом служит самая ранняя из живущих
    строк `ScanPage`: они заводятся первым чтением и уносятся применением.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        enrol(self.student, self.course, by=self.admin)

    def spend(self, micros, purpose=AiSpend.SCAN_HEADER, ago=None):
        row = AiSpend.objects.create(
            school=self.school,
            user=self.user,
            work=self.work,
            purpose=purpose,
            model="claude-haiku-4-5-20251001",
            input_tokens=1600,
            output_tokens=40,
            cost_micros=micros,
        )
        if ago is not None:
            AiSpend.objects.filter(pk=row.pk).update(created_at=ago)
        return row

    def test_the_batch_is_counted_from_its_first_page(self):
        old = timezone.now() - timedelta(days=30)
        self.spend(5000, ago=old)

        services.save_scan_reading(
            self.work,
            index=0,
            fingerprint="f0",
            data={"first_name": "Fil", "surname": "Burmov", "values": [None] * 16},
        )
        self.spend(1200)

        state = services.scan_state(self.work)

        self.assertEqual(state["spend"]["micros"], 1200)
        self.assertEqual(state["spend"]["calls"], 1)

    def test_the_journal_still_remembers_everything(self):
        """
        Прошлые пачки из счёта уходят, но не из журнала: «сколько эта работа
        стоила всего» — законный вопрос, и ответ на него рядом.
        """
        self.spend(5000, ago=timezone.now() - timedelta(days=30))
        services.save_scan_reading(
            self.work,
            index=0,
            fingerprint="f0",
            data={"first_name": "Fil", "surname": "Burmov", "values": [None] * 16},
        )
        self.spend(1200)

        self.assertEqual(services.scan_state(self.work)["spend"]["total_micros"], 6200)

    def test_the_reasons_are_told_apart(self):
        """
        Полоска шапки, перечитывание и лист условий стоят по-разному — на
        порядок, — и одна сумма не сказала бы, за что заплачено.
        """
        services.save_scan_reading(
            self.work,
            index=0,
            fingerprint="f0",
            data={"first_name": "Fil", "surname": "Burmov", "values": [None] * 16},
        )
        self.spend(1200, purpose=AiSpend.SCAN_HEADER)
        self.spend(1300, purpose=AiSpend.SCAN_HEADER)
        self.spend(23000, purpose=AiSpend.SCAN_QUESTIONS)

        by_purpose = services.scan_state(self.work)["spend"]["by_purpose"]

        self.assertEqual(by_purpose[AiSpend.SCAN_HEADER]["calls"], 2)
        self.assertEqual(by_purpose[AiSpend.SCAN_HEADER]["micros"], 2500)
        self.assertEqual(by_purpose[AiSpend.SCAN_QUESTIONS]["micros"], 23000)

    def test_nothing_read_costs_nothing(self):
        """Пустая пачка — это ноль, а не сумма прошлых разборов."""
        self.spend(5000, ago=timezone.now() - timedelta(days=30))

        self.assertEqual(services.scan_state(self.work)["spend"]["micros"], 0)


class ScanCandidateStateTests(SchoolTestMixin, APITestCase):
    """
    Кого экран предлагает по прочитанной странице.

    Тройка считается по самой странице и доезжает до состояния: до этого она
    бралась от пакета, у решённого пакета её нет вовсе, и экран показывал
    вместо неё первых по списку класса.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        self.student.first_name, self.student.last_name = "Varvara", "Mironova"
        self.student.save()
        enrol(self.student, self.course, by=self.admin)

    def test_the_page_offers_the_person_written_on_it(self):
        services.save_scan_reading(
            self.work,
            index=0,
            fingerprint="f0",
            data={
                "first_name": "Varvara",
                "surname": "Mironova",
                "values": [None] * 16,
            },
        )

        page = services.scan_state(self.work)["pages"][0]

        self.assertEqual(page["candidates"][0], self.student.id)


class ScanSuggestionTests(SchoolTestMixin, APITestCase):
    """
    Кого предложить странице, на которой имени нет вовсе.

    Своего свидетельства у такой страницы нет, и кандидатов ей взять неоткуда:
    список выходил либо пустым, либо набором случайных фамилий с нулевым
    сходством — сравнивать было не с чем. Между тем пачка лежит стопкой, и
    лист без подписи почти всегда продолжение предыдущего. Это ровно та
    догадка, по которой раскладка кладёт такие листы сама; человеку она
    предлагается кнопкой, а не применяется молча.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        self.student.first_name, self.student.last_name = "Fil", "Burmov"
        self.student.save()
        enrol(self.student, self.course, by=self.admin)

    def read(self, index, first="", surname="", marks=None):
        cells = [None] * 16
        for question, value in (marks or {}).items():
            cells[question] = value
        services.save_scan_reading(
            self.work,
            index=index,
            fingerprint=f"f{index}",
            data={"first_name": first, "surname": surname, "values": cells},
        )

    def test_an_unsigned_page_is_offered_the_previous_owner(self):
        self.read(0, "Fil", "Burmov", {0: 1})
        self.read(1, marks={1: 2})

        pages = services.scan_state(self.work)["pages"]

        self.assertEqual(pages[1]["candidates"], [self.student.id])

    def test_the_first_page_has_nobody_to_borrow_from(self):
        """Предлагать по соседу сверху нечего, если соседа нет."""
        self.read(0, marks={0: 1})

        self.assertEqual(services.scan_state(self.work)["pages"][0]["candidates"], [])

    def test_a_signed_page_keeps_its_own_candidates(self):
        """
        Подсказка соседа не заслоняет собственное имя: у подписанной страницы
        свидетельство своё, и оно сильнее порядка в стопке.
        """
        self.read(0, "Fil", "Burmov", {0: 1})
        self.read(1, "Fil", "Burmov", {1: 2})

        pages = services.scan_state(self.work)["pages"]

        self.assertEqual(pages[1]["candidates"][0], self.student.id)


class ScanHandFilledTests(SchoolTestMixin, APITestCase):
    """
    Балл, вписанный руками, говорит о странице больше, чем поиск шапки.

    Лист, на котором шапку не нашли, считается листом условий и в раскладку не
    попадает. Но баллы на нём человек видит глазами — и вписывает; после этого
    называть лист условиями значит выбросить только что сделанную работу.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        enrol(self.student, self.course, by=self.admin)

    def test_a_filled_cell_makes_it_an_answer_sheet(self):
        services.mark_headerless(self.work, index=0, ours=False)
        self.assertTrue(ScanPage.objects.get(work=self.work, index=0).headerless)

        services.edit_scan_page(self.work, index=0, cells=[2] + [None] * 15)

        self.assertFalse(ScanPage.objects.get(work=self.work, index=0).headerless)

    def test_clearing_the_cells_does_not_resurrect_it(self):
        """Пустые клетки ничего не утверждают — это стирание, а не решение."""
        services.mark_headerless(self.work, index=0, ours=False)

        services.edit_scan_page(self.work, index=0, cells=[None] * 16)

        self.assertTrue(ScanPage.objects.get(work=self.work, index=0).headerless)


class SecondReadingIsKeptTests(SchoolTestMixin, APITestCase):
    """
    Второе чтение живёт в строке страницы и доезжает до экрана.

    Спор двух читателей — событие, а не расчёт: он случился при чтении, за
    которое заплачено, и после этого его не пересчитывают. Иначе он исчезал бы
    ровно тогда, когда арбитр встал на сторону второго читателя.

    А исчерпывает его человек: он затем и позван, чтобы посмотреть на бумагу.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        enrol(self.student, self.course, by=self.admin)

    def reading(self, **over):
        return {
            "first_name": "Fil",
            "surname": "Burmov",
            "values": [1] + [None] * 15,
            "second": {
                "reader": "mathpix",
                "first_name": "Fil",
                "surname": "Burmova",
                "values": [1] + [None] * 15,
                "differs": ["name"],
            },
        } | over

    def test_the_second_reading_reaches_the_screen(self):
        services.save_scan_reading(
            self.work, index=0, fingerprint="f0", data=self.reading()
        )

        row = services.scan_state(self.work)["pages"][0]

        self.assertEqual(row["second"]["surname"], "Burmova")
        self.assertIn("readers_differ", row["trouble"])

    def test_a_human_looking_at_the_page_settles_the_argument(self):
        """
        Пометка, которую нельзя снять, перестаёт что-либо значить: она зовёт
        смотреть на то, что уже посмотрели.
        """
        services.save_scan_reading(
            self.work, index=0, fingerprint="f0", data=self.reading()
        )

        services.edit_scan_page(self.work, index=0, cells=[2] + [None] * 15)

        row = services.scan_state(self.work)["pages"][0]
        self.assertEqual(row["second"]["differs"], [])
        self.assertNotIn("readers_differ", row["trouble"])
        # само чтение второго читателя при этом никуда не делось: человек
        # решил спор, а не стёр свидетельство
        self.assertEqual(row["second"]["surname"], "Burmova")

    def test_a_page_read_without_a_second_reader_is_a_normal_page(self):
        """Ключей Mathpix может не быть вовсе — это законное состояние."""
        services.save_scan_reading(
            self.work,
            index=0,
            fingerprint="f0",
            data={"first_name": "Fil", "surname": "Burmov", "values": [1] + [None] * 15},
        )

        row = services.scan_state(self.work)["pages"][0]

        self.assertEqual(row["second"], {})
        self.assertNotIn("readers_differ", row["trouble"])


class SecondReaderIsAskedForTests(SchoolTestMixin, APITestCase):
    """
    Второго читателя зовут по просьбе человека, и просьба едет по HTTP.

    Проверяется именно дорога, а не сервис: галочка стоит на шаге выбора
    файла, то есть **до** платежа, а цикл чтения ведёт браузер — значит с
    каждой страницей уезжает и просьба. Оборвись она где-нибудь по пути,
    снаружи это выглядело бы как работающая галочка, которая ничего не
    меняет, и заметили бы это по счёту.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        enrol(self.student, self.course, by=self.admin)
        self.client.force_authenticate(self.user)

    def post(self, **extra):
        """Одна страница на чтение. Читатель подменён — настоящий стоит денег."""
        from unittest.mock import patch

        from works import views

        seen = {}

        def reading(**kwargs):
            seen.update(kwargs)
            return {
                "first_name": "Fil",
                "surname": "Burmov",
                "values": [None] * 16,
                "second": {"reader": "mathpix", "error": "not_asked", "differs": []},
            }

        with patch.object(views.vision_services, "read_and_charge", reading):
            answer = self.client.post(
                reverse("work-scan-read", args=[self.work.pk]),
                {
                    "index": 0,
                    "strip": SimpleUploadedFile("strip.jpg", b"picture"),
                    "fingerprint": "f0",
                }
                | extra,
                format="multipart",
            )
        self.assertEqual(answer.status_code, 200, answer.content)
        return seen

    def test_the_unticked_box_reaches_the_reader(self):
        self.assertFalse(self.post(second="false")["asked_second"])

    def test_the_ticked_box_reaches_the_reader(self):
        self.assertTrue(self.post(second="true")["asked_second"])

    def test_saying_nothing_means_reading_as_before(self):
        """
        Умолчание — «звать»: ключи Mathpix в контуре появляются не сами, и раз
        школа их поставила, второй читатель нужен. Галочка снимает его, а не
        включает.
        """
        self.assertTrue(self.post()["asked_second"])

    def test_the_screen_is_told_who_can_read_the_cells(self):
        """
        Галочка, которая ничем не управляет, — это ложь на экране. А список, а
        не флаг, потому что читателей клеток стало двое и экрану надо знать,
        кого именно галочка позовёт: у Mathpix способ один, у Yandex два.
        """
        with self.settings(MATHPIX_APP_ID="", MATHPIX_APP_KEY="", YANDEX_OCR_API_KEY=""):
            self.assertEqual(services.scan_state(self.work)["cells_readers"], [])
        with self.settings(MATHPIX_APP_ID="id", MATHPIX_APP_KEY="key"):
            self.assertEqual(services.scan_state(self.work)["cells_readers"], ["mathpix"])
        with self.settings(
            MATHPIX_APP_ID="id", MATHPIX_APP_KEY="key", YANDEX_OCR_API_KEY="key"
        ):
            self.assertEqual(
                services.scan_state(self.work)["cells_readers"], ["mathpix", "yandex"]
            )
