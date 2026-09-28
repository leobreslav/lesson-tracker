"""
Применение разобранной пачки: страницы ученикам, клетки в оценки.

Шагов два, и гарантии у них разные. Работы учеников приезжают **по одной**
(`scan/piece/`), потому что пачка целиком до сервера не доезжает: скан класса
весит от тридцати до двухсот мегабайт. Оценки пишет завершение
(`scan/apply/`) — **одной транзакцией на весь класс** и только когда доехали
все работы. Не бывает класса, где половине оценки выставлены, а половине нет;
бывает разбор, оборвавшийся на середине отправки, и его продолжают с обрыва.
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
    make_pile,
    make_user,
    make_work,
    make_year,
)

from . import services
from .models import Mark, ScanAlias, ScanPage, StudentWork
from .test_splitting import book


def pages_of(attachment) -> int:
    """Сколько страниц в приложенном PDF — читая из бакета, как читает ученик."""
    from io import BytesIO

    from files import storage
    from pypdf import PdfReader

    with storage.backend().open(attachment.stored_file.key) as fp:
        return len(PdfReader(BytesIO(fp.read())).pages)


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

    def send(self, student, pages=1):
        """Работа одного ученика — так, как её присылает мастер."""
        return self.client.post(
            reverse("work-scan-piece", args=[self.work.pk]),
            {
                "student": getattr(student, "pk", student),
                "file": SimpleUploadedFile("piece.pdf", book(pages)),
            },
            format="multipart",
        )

    def finish(self):
        return self.client.post(reverse("work-scan-apply", args=[self.work.pk]))

    def apply(self):
        """
        То, что делает мастер: каждому, кому пачка что-то назначила, — его
        работа, потом завершение. Сколько страниц в куске, сказано раскладкой:
        решения вместе с условиями.
        """
        state = self.client.get(reverse("work-scan-state", args=[self.work.pk])).json()
        for packet in state.get("packets", []):
            if packet["student"]:
                self.send(
                    packet["student"],
                    pages=len(packet["pages"]) + len(packet["conditions"]),
                )
        return self.finish()

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

        response = self.apply()

        self.assertEqual(response.status_code, 200)
        mine = StudentWork.objects.get(work=self.work, student=self.student)
        paper = Attachment.objects.get(student_work=mine)
        # Режет теперь браузер, и сколько страниц положить, он узнаёт из
        # раскладки: решения пакета вместе с его условиями. Помощник `apply`
        # читает ровно её, так что два листа в файле — это её слова
        self.assertEqual(pages_of(paper), 2)

    def test_the_pile_is_not_kept_anywhere(self):
        """
        Пачка целиком не хранится — ни у работы, ни где-либо ещё.

        Хранили её, и на живой пачке это упёрлось сразу в два предела: скан
        класса весит от тридцати до двухсот мегабайт, а сервер принимает
        запрос в двадцать пять и хранит файл в двадцать. Да и лежала она
        дважды: каждая её страница уже есть в работе какого-то ученика.
        """
        self.read(0, "Fil", "Burmov", {0: 3})

        response = self.apply()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Attachment.objects.filter(work=self.work).exists())
        self.assertNotIn("batch", response.json())

    def test_a_work_that_has_not_arrived_stops_the_finish(self):
        """
        Завершить разбор, пока чья-то работа не доехала, нельзя.

        Завершение удаляет прочитанное о пачке. Оборвись связь на втором
        ученике, и после завершения он остался бы с оценкой без бумаги, а
        дослать её было бы уже не по чему: раскладки больше нет.
        """
        self.read(0, "Fil", "Burmov", {0: 3})
        self.read(1, "Peter", "Tibora", {0: 2})
        self.send(self.student)

        response = self.finish()

        self.assertEqual(response.json()["code"], "scan_pieces_missing")
        self.assertEqual(response.json()["params"]["students"], [self.second.pk])
        self.assertTrue(ScanPage.objects.filter(work=self.work).exists())
        self.assertFalse(Mark.objects.filter(student_work__work=self.work).exists())

    def test_the_finish_goes_through_once_everybody_has_arrived(self):
        """Дослали недостающее — и тот же запрос проходит: мастер продолжает с обрыва."""
        self.read(0, "Fil", "Burmov", {0: 3})
        self.read(1, "Peter", "Tibora", {0: 2})
        self.send(self.student)
        self.finish()

        self.send(self.second)
        response = self.finish()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["students"], 2)
        self.assertEqual(Mark.objects.filter(student_work__work=self.work).count(), 2)

    def test_a_piece_writes_no_marks_by_itself(self):
        """
        Оценки пишет завершение, всем разом, а не приём файла.

        Файл без оценки — состояние видимое и поправимое. Оценки у половины
        класса — нет: снаружи не видно, какой половине они выставлены.
        """
        self.read(0, "Fil", "Burmov", {0: 3})

        response = self.send(self.student)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(Mark.objects.filter(student_work__work=self.work).exists())

    def test_a_piece_for_somebody_the_pile_gave_nothing_is_refused(self):
        """
        Чей кусок, решает раскладка на сервере, а не присланное браузером.

        Иначе опечатка в номере ученика положила бы чужую работу человеку,
        которого в этой пачке не было вовсе.
        """
        self.read(0, "Fil", "Burmov", {0: 3})

        response = self.send(self.second)

        self.assertEqual(response.json()["code"], "scan_piece_unexpected")
        self.assertFalse(
            Attachment.objects.filter(student_work__work=self.work).exists()
        )

    def test_a_piece_that_is_not_a_pdf_is_refused(self):
        self.read(0, "Fil", "Burmov", {0: 3})

        response = self.client.post(
            reverse("work-scan-piece", args=[self.work.pk]),
            {
                "student": self.student.pk,
                "file": SimpleUploadedFile("piece.pdf", b"not a pdf at all"),
            },
            format="multipart",
        )

        self.assertEqual(response.json()["code"], "file_not_pdf")

    def test_a_work_sent_in_two_files_keeps_both(self):
        """
        Кусок тяжелее предела браузер делит пополам, и приезжают оба.

        Поэтому дверь принимает файл, а не «работу ученика целиком»: у
        ученика с двадцатью листами в шестистах точках файлов выйдет два.
        """
        self.read(0, "Fil", "Burmov", {0: 3})
        self.send(self.student, pages=1)
        self.send(self.student, pages=2)

        response = self.finish()

        self.assertEqual(response.status_code, 200, response.content)
        mine = StudentWork.objects.get(work=self.work, student=self.student)
        self.assertEqual(Attachment.objects.filter(student_work=mine).count(), 2)

    def test_a_repeated_run_does_not_double_the_student_s_file(self):
        """
        И ученику не достаётся второй копии собственной работы.

        Пока этого не было, каждый повторный разбор добавлял ему ещё один PDF
        с теми же байтами — а отличаются они или нет, ученику неоткуда узнать.
        """
        self.read(0, "Fil", "Burmov", {0: 3})
        self.apply()
        self.read(0, "Fil", "Burmov", {0: 3})
        self.apply()

        mine = StudentWork.objects.get(work=self.work, student=self.student)
        self.assertEqual(Attachment.objects.filter(student_work=mine).count(), 1)

    def test_a_pile_kept_before_still_reaches_the_table_and_the_wizard(self):
        """
        Пачки, приложенные до того, как их перестали хранить, остаются.

        Лежат они в базах школ, и удалять чужие файлы ради новой идеи
        незачем: таблица их показывает, мастер умеет с них начать.
        """
        make_pile(self.work, self.user)

        table = self.client.get(reverse("work-table", args=[self.work.pk])).json()
        state = self.client.get(
            reverse("work-scan-state", args=[self.work.pk])
        ).json()

        self.assertEqual(len(table["batches"]), 1)
        self.assertEqual(len(state["batches"]), 1)

    def test_the_table_lists_the_class_by_surname(self):
        """
        Таблица результатов идёт по фамилии, как бумажный журнал.

        Шла по имени, и один и тот же класс выглядел по-разному на соседних
        экранах: журнал курса по фамилии, таблица работы по имени. Имена
        выбраны так, чтобы два порядка расходились: по имени первым встал бы
        Adam, по фамилии — Adams.
        """
        self.student.first_name, self.student.last_name = "Zed", "Adams"
        self.student.save()
        self.second.first_name, self.second.last_name = "Adam", "Zimmer"
        self.second.save()

        table = self.client.get(reverse("work-table", args=[self.work.pk])).json()

        self.assertEqual(
            [row["name"] for row in table["students"]], ["Zed Adams", "Adam Zimmer"]
        )

    def test_the_pile_stands_in_the_table_and_not_among_the_work_s_files(self):
        """
        Пачка — не материал задания, и место ей в таблице результатов.

        Стояла она в обоих местах, и в файлах работы читалась как то, что к
        работе приложил учитель для класса, рядом с условиями и бланком.
        """
        make_pile(self.work, self.user)

        work = self.client.get(reverse("work-detail", args=[self.work.pk])).json()
        table = self.client.get(reverse("work-table", args=[self.work.pk])).json()

        self.assertEqual(work["files"], [])
        self.assertEqual(len(table["batches"]), 1)

    def test_a_file_hidden_from_the_class_is_not_a_pile(self):
        """
        Скрытое от класса и пачка — разные вещи.

        Пачкой считалось всё скрытое, и ответы к контрольной, приложенные к
        той же работе, показывались в таблице результатов «пачкой целиком».
        Первое про круг читателей, второе про то, что это за файл.
        """
        from files.services import store_upload

        stored, _ = store_upload(
            upload=SimpleUploadedFile(
                "answers.pdf", b"%PDF-1.4 answers", content_type="application/pdf"
            ),
            school=self.school,
            user=self.user,
        )
        Attachment.objects.create(
            work=self.work,
            kind="file",
            stored_file=stored,
            staff_only=True,
            title="answers.pdf",
        )

        work = self.client.get(reverse("work-detail", args=[self.work.pk])).json()
        table = self.client.get(reverse("work-table", args=[self.work.pk])).json()

        self.assertEqual([item["title"] for item in work["files"]], ["answers.pdf"])
        self.assertEqual(table["batches"], [])

    def test_the_file_of_all_works_is_named_after_the_work(self):
        """
        «Все работы одним файлом» собирает браузер, а имя файлу даём мы.

        Сканер зовёт файл `scan.pdf`, и через месяц таких в загрузках десять.
        Имя собирается из того, что знаем мы: работа, её дата, курс. Дата —
        работы, а не скачивания: привязана к занятию — день занятия, иначе
        день открытия окна. И знаки, которых не терпит файловая система, в
        имя не попадают: оно уедет на диск.
        """
        from django.utils import timezone

        self.work.title = 'Углы: "сумма" / разность'
        self.work.save(update_fields=["title"])

        table = self.client.get(reverse("work-table", args=[self.work.pk])).json()
        day = timezone.localdate(self.work.opens_at).isoformat()

        self.assertEqual(
            table["work"]["pile_name"],
            f"Углы сумма разность, {day}, {self.course.name}.pdf",
        )

    def test_a_piece_the_store_refuses_says_why(self):
        """
        Отказ хранилища доезжает до человека кодом, а не пятисотой.

        Упереться кусок может в предел файла или в квоту школы, и чинятся
        эти два по-разному: первое делит кусок пополам сам мастер, второе
        решает администратор.
        """
        from unittest.mock import patch

        from files.services import UploadRefused

        self.read(0, "Fil", "Burmov", {0: 3})

        with patch.object(
            services,
            "attach_piece",
            side_effect=UploadRefused("file_too_large", "too big", limit_mb=20),
        ):
            response = self.send(self.student)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "file_too_large")
        self.assertTrue(ScanPage.objects.filter(work=self.work).exists())

    def drop(self, index, dropped=True):
        return self.client.post(
            reverse("work-scan-page", args=[self.work.pk]),
            {"index": index, "dropped": dropped},
            format="json",
        )

    def test_a_page_taken_out_of_the_pile_stops_cutting_it(self):
        """
        Убранная страница границей не служит.

        Пустой оборот шапки не несёт и потому читается листом условий, а
        ряды условий **режут пачку на работы**. На живой пачке из
        восьмидесяти листов одиннадцать таких разрезали её на двадцать два
        пакета при двадцати учениках. Убранная, она в раскладку не входит
        вовсе, и страницы по обе стороны от неё — одна работа.
        """
        self.read(0, "Fil", "Burmov", {0: 3})
        services.mark_headerless(self.work, index=1)
        self.read(2, "", "", {1: 1})
        services.mark_headerless(self.work, index=3)
        self.read(4, "Peter", "Tibora", {0: 2})

        before = self.client.get(
            reverse("work-scan-state", args=[self.work.pk])
        ).json()
        self.assertGreater(len(before["packets"]), 2, "пустой оборот пачку не резал")

        state = self.drop(1).json()

        mine = next(p for p in state["packets"] if p["student"] == self.student.pk)
        self.assertEqual(mine["pages"], [0, 2])
        self.assertEqual(mine["conditions"], [])
        self.assertEqual(len(state["packets"]), 2)

    def test_a_page_taken_out_asks_for_no_owner_and_goes_to_nobody(self):
        """
        Своё состояние, а не «ничья».

        «Ничья» держит шаг разбора запертым и зовёт назначить хозяина, а
        назначать пустому обороту некого. И в работу ученика она не едет:
        режет браузер по тому, что отвечает раскладка, и страница, которой в
        ответе нет, в его PDF не попадёт.
        """
        self.read(0, "Fil", "Burmov", {0: 3})
        self.read(1, "", "unreadable scrawl", {})

        state = self.drop(1).json()
        page = next(p for p in state["pages"] if p["index"] == 1)

        self.assertTrue(page["dropped"])
        self.assertIsNone(page["student"])
        self.assertEqual(page["trouble"], [])
        self.assertEqual(state["doubts"], [])
        self.assertEqual(
            [p["pages"] for p in state["packets"] if p["student"]], [[0]]
        )

    def test_a_page_taken_out_comes_back_the_same_way(self):
        """Строка остаётся: прочитанное стоило денег, и вернуть страницу можно."""
        self.read(0, "Fil", "Burmov", {0: 3})
        self.drop(0)

        state = self.drop(0, dropped=False).json()

        page = next(p for p in state["pages"] if p["index"] == 0)
        self.assertFalse(page["dropped"])
        self.assertEqual(page["student"], self.student.pk)
        self.assertEqual(page["cells"][0], 3)

    def test_naming_an_owner_brings_the_page_back(self):
        """
        Убранная страница с хозяином — противоречие, и верно последнее слово.

        Оставь мы её убранной, назначенная страница молча не попала бы
        ученику в работу: на экране хозяин стоит, а в PDF листа нет.
        """
        self.read(0, "", "", {0: 3})
        self.drop(0)

        state = self.client.post(
            reverse("work-scan-page", args=[self.work.pk]),
            {"index": 0, "student": self.student.pk},
            format="json",
        ).json()

        page = next(p for p in state["pages"] if p["index"] == 0)
        self.assertFalse(page["dropped"])
        self.assertEqual(page["student"], self.student.pk)

    def test_a_pile_with_a_page_taken_out_is_written_without_it(self):
        """
        Запись идёт по той же раскладке, что и экран.

        Отсей убранное только экран, и завершение ждало бы работу от
        ученика, которому досталась одна убранная страница, — а мастер её не
        прислал бы, потому что на экране такого ученика нет.
        """
        self.read(0, "Fil", "Burmov", {0: 3})
        self.read(1, "Peter", "Tibora", {0: 2})
        self.drop(1)

        response = self.apply()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["students"], 1)
        self.assertFalse(
            StudentWork.objects.filter(work=self.work, student=self.second).exists()
        )

    def test_the_rows_are_gone_once_it_is_applied(self):
        """Работа сделана: дальше про неё отвечают вложения и оценки."""
        self.read(0, "Fil", "Burmov", {0: 3})

        self.apply()

        self.assertFalse(ScanPage.objects.filter(work=self.work).exists())

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

    def test_the_unticked_box_reaches_the_reading(self):
        self.assertFalse(self.post(second="false")["second"])

    def test_the_ticked_box_reaches_the_reading(self):
        self.assertTrue(self.post(second="true")["second"])

    def test_saying_nothing_means_reading_as_before(self):
        """
        Умолчание — «звать»: ключи в контуре появляются не сами, и раз школа их
        поставила, второй свидетель нужен. Галочка снимает его, а не включает.
        """
        self.assertTrue(self.post()["second"])

    def test_the_screen_is_told_whether_the_second_reader_can_be_called(self):
        """
        Заглушённая галочка объясняет себя, пропавшая — нет. Контур без ключей
        Mathpix выглядел раньше как контур, где Mathpix не бывает вовсе, и
        починить это настройкой человек не шёл: чинить, судя по экрану, было
        нечего.
        """
        with self.settings(MATHPIX_APP_ID="", MATHPIX_APP_KEY=""):
            self.assertEqual(
                services.scan_state(self.work)["second_reader"],
                {"name": "mathpix", "able": False, "why": "not_configured"},
            )
        with self.settings(MATHPIX_APP_ID="id", MATHPIX_APP_KEY="key"):
            self.assertEqual(
                services.scan_state(self.work)["second_reader"],
                {"name": "mathpix", "able": True, "why": ""},
            )

    def test_the_screen_is_offered_both_readers_of_the_header(self):
        """
        Читателей шапки двое, и показываются оба — недоступный заглушённым.
        Mathpix среди них нет: он второй свидетель, а не выбор.
        """
        with self.settings(YANDEX_OCR_API_KEY=""):
            self.assertEqual(
                [one["name"] for one in services.scan_state(self.work)["readers"]],
                ["anthropic", "yandex"],
            )


class RememberedWritingTests(SchoolTestMixin, APITestCase):
    """
    Курс помнит, как читается почерк его учеников.

    Учитель на шаге разбора и так называет хозяина спорной страницы. Раньше это
    решение жило одну пачку: следующая контрольная того же класса начиналась с
    того же вопроса про того же ученика.

    Помнится **написанное**, а не имя, и потому память покрывает то, чего не
    покроет никакой словарь имён: устойчивый промах распознавания. Mathpix
    читает кириллицу латиницей, и «Степанов» у него всегда `Cocramol` — один
    раз названный, он узнаётся дальше сам.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.student.first_name, self.student.last_name = "Артём", "Степанов"
        self.student.save()
        enrol(self.student, self.course, by=self.admin)

    def pile(self, first, surname):
        """Пачка из одного листа с таким написанием."""
        work = make_work(self.user, self.course)
        services.save_scan_reading(
            work,
            index=0,
            fingerprint="f0",
            data={"first_name": first, "surname": surname, "values": [1] + [None] * 15},
        )
        return work

    def test_the_course_remembers_what_the_human_said(self):
        first = self.pile("", "Cocramol")
        services.edit_scan_page(first, index=0, student=self.student.pk)

        again = self.pile("", "Cocramol")
        state = services.scan_state(again)

        self.assertEqual(state["pages"][0]["student"], self.student.pk)

    def test_a_page_without_a_name_is_not_remembered(self):
        """
        Страница без имени похожа на любую другую такую же: запоминать по ней
        нечего, а запомнив — раздали бы по ней всю следующую пачку.
        """
        first = self.pile("", "")
        services.edit_scan_page(first, index=0, student=self.student.pk)

        self.assertEqual(ScanAlias.objects.count(), 0)

    def test_the_newer_decision_wins(self):
        """Человек передумал — значит прежняя пара была ошибкой."""
        other = make_user(self.school, "other@example.com", student=True)
        other.first_name, other.last_name = "Пётр", "Тиборов"
        other.save()
        enrol(other, self.course, by=self.admin)

        first = self.pile("", "Cocramol")
        services.edit_scan_page(first, index=0, student=self.student.pk)
        second = self.pile("", "Cocramol")
        services.edit_scan_page(second, index=0, student=other.pk)

        third = self.pile("", "Cocramol")

        self.assertEqual(ScanAlias.objects.count(), 1)
        self.assertEqual(services.scan_state(third)["pages"][0]["student"], other.pk)

    def test_memory_belongs_to_the_course_and_not_to_the_school(self):
        """
        Список класса курсовой, и две «Ксюши» в разных курсах одной школы — это
        норма, а не совпадение. Память школы свела бы их в одну.
        """
        first = self.pile("Ксюша", "")
        services.edit_scan_page(first, index=0, student=self.student.pk)

        elsewhere = make_course(self.school, self.year, name="Другой курс")
        stranger = make_user(self.school, "ksenia@example.com", student=True)
        stranger.first_name, stranger.last_name = "Ксения", "Панова"
        stranger.save()
        enrol(stranger, elsewhere, by=self.admin)
        work = make_work(self.user, elsewhere)
        services.save_scan_reading(
            work,
            index=0,
            fingerprint="f0",
            data={"first_name": "Ксюша", "surname": "", "values": [1] + [None] * 15},
        )

        self.assertEqual(services.scan_state(work)["pages"][0]["student"], stranger.pk)


class ConditionsBelongToSomebodyTests(SchoolTestMixin, APITestCase):
    """
    Лист условий — страница того ученика, чьи решения идут за ним.

    Раздают условия **перед** работой, поэтому ряд таких листов и режет пачку:
    он принадлежит следующему, а не предыдущему и не никому. Разрезка это знала
    давно, а экран — нет: хозяин строки страницы брался только со страниц
    решений, и лист условий показывался ничьим. В PDF ученика он при этом
    уезжал правильно, то есть человек шёл назначать вручную уже назначенное.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        self.student.first_name, self.student.last_name = "Fil", "Burmov"
        self.student.save()
        self.second = make_user(self.school, "second@example.com", student=True)
        self.second.first_name, self.second.last_name = "Peter", "Tibora"
        self.second.save()
        enrol(self.student, self.course, by=self.admin)
        enrol(self.second, self.course, by=self.admin)

    def test_a_condition_sheet_belongs_to_the_work_that_follows_it(self):
        # условия, решение, условия, решение — два ряда, значит пачка режется
        services.mark_headerless(self.work, index=0)
        services.save_scan_reading(
            self.work,
            index=1,
            fingerprint="f1",
            data={"first_name": "Fil", "surname": "Burmov", "values": [1] + [None] * 15},
        )
        services.mark_headerless(self.work, index=2)
        services.save_scan_reading(
            self.work,
            index=3,
            fingerprint="f3",
            data={"first_name": "Peter", "surname": "Tibora", "values": [2] + [None] * 15},
        )

        pages = {p["index"]: p for p in services.scan_state(self.work)["pages"]}

        self.assertEqual(pages[0]["student"], self.student.pk, "условия первого ничьи")
        self.assertEqual(pages[2]["student"], self.second.pk, "условия второго ничьи")
        self.assertEqual(pages[1]["student"], self.student.pk)
        self.assertEqual(pages[3]["student"], self.second.pk)


class ConditionsAtTheTopBelongToEverybodyTests(SchoolTestMixin, APITestCase):
    """
    Ряд условий, лежащий **один раз в начале**, — общий, а не чей-то.

    Границ он не задаёт: делить ему нечего, за ним идут все работы подряд. Зато
    в PDF он уезжает каждому — иначе ученик открывает свои ответы без вопросов.

    На экране у такой страницы до сих пор стоял хозяин — последний ученик
    пачки, тот, кому её положили последним при обходе пакетов. Человек видел
    уверенно названного владельца и шёл исправлять правильное, а исправить
    «общий лист» на «лист Петра» значило бы отобрать условия у остальных
    двенадцати.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        services.set_questions(
            self.work, [{"question": "Задача 1", "maximum": 3}], by=self.user
        )
        self.student.first_name, self.student.last_name = "Fil", "Burmov"
        self.student.save()
        self.second = make_user(self.school, "second@example.com", student=True)
        self.second.first_name, self.second.last_name = "Peter", "Tibora"
        self.second.save()
        enrol(self.student, self.course, by=self.admin)
        enrol(self.second, self.course, by=self.admin)
        self.client.force_authenticate(self.user)

        # условия, работа первого, работа второго: один ряд условий на всех
        services.mark_headerless(self.work, index=0)
        for index, person in ((1, self.student), (2, self.second)):
            services.save_scan_reading(
                self.work,
                index=index,
                fingerprint=f"f{index}",
                data={
                    "first_name": person.first_name,
                    "surname": person.last_name,
                    "values": [1] + [None] * 15,
                },
            )

    def test_the_shared_sheet_is_named_as_shared_and_not_as_somebody_s(self):
        state = services.scan_state(self.work)
        pages = {page["index"]: page for page in state["pages"]}

        self.assertTrue(pages[0]["common_conditions"])
        self.assertIsNone(pages[0]["student"], "у общего листа хозяина нет")
        self.assertEqual(state["common_conditions"], [0])
        self.assertFalse(pages[1]["common_conditions"])

    def test_the_shared_sheet_is_counted_once_and_not_once_per_packet(self):
        """
        Листов условий столько, сколько их в пачке.

        Считалось это суммой по пакетам, а общий ряд лежит в каждом, — и два
        листа условий на тринадцать работ объявлялись двадцатью шестью.
        """
        self.assertEqual(services.scan_state(self.work)["conditions"], 1)

    def test_the_shared_sheet_opens_every_student_s_file(self):
        """
        И уезжает оно в работу каждого: раскладка называет его в каждом пакете.

        Режет работы браузер, и что в какую положить, он узнаёт отсюда. Лист,
        не названный в пакете, не попал бы ученику вовсе — он открыл бы свои
        ответы без вопросов. В начало работы лист встаёт сам: страницы куска
        идут по номерам, а общий ряд лежит в пачке первым.
        """
        state = services.scan_state(self.work)
        packets = {packet["student"]: packet for packet in state["packets"]}

        for person in (self.student, self.second):
            self.assertEqual(
                packets[person.pk]["conditions"],
                [0],
                f"условий нет у {person.last_name}",
            )

    def test_a_human_naming_the_owner_takes_the_sheet_out_of_the_shared_run(self):
        """
        Сказанное человеком сильнее раскладки — и здесь тоже.

        «Общий лист» это наш вывод, а не факт с бумаги: ряд без шапки бывает и
        плохо снятой работой. Назвали хозяина — лист перестал быть общим.
        """
        # хозяин называется тот, чья работа идёт следом: лист лежит перед ней,
        # и в стопке это его первая страница, а не чужая
        services.edit_scan_page(self.work, index=0, student=self.student)

        state = services.scan_state(self.work)
        pages = {page["index"]: page for page in state["pages"]}

        self.assertFalse(pages[0]["common_conditions"])
        self.assertEqual(pages[0]["student"], self.student.pk)
        self.assertEqual(state["common_conditions"], [])
