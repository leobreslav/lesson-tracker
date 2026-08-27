"""
Личный стол: чей он, что на нём лежит и что переживает уборку.

Проверяется здесь ровно то, чем этот раздел отличается от всего остального в
проекте. Всё прочее принадлежит школе или курсу, и «чужое» там означает
«другой школы» либо «не ваш курс»; тут владелец — человек, и чужой стол не
существует **вовсе**, даже для администратора школы. Ошибка в этом месте
выглядела бы не как лишняя кнопка, а как чужие записки в своём списке.
"""

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from files.models import Attachment, StoredFile
from schools.testing import (
    SchoolTestMixin,
    make_course,
    make_node,
    make_stored_file,
    make_upload,
    make_user,
)

from .models import Folder


class ShelfTestMixin(SchoolTestMixin):
    """Общее для всех тестов ниже: адреса и заведение вещей на стол."""

    def setUp(self):
        super().setUp()
        self.FOLDERS = reverse("bookmark-folder-list")

    def folder_url(self, folder):
        return reverse("bookmark-folder-detail", args=[folder.pk])

    def make_folder(self, owner=None, title="Методика"):
        return Folder.objects.create(owner=owner or self.user, title=title)

    def put_on_school_shelf(self, school=None, **fields):
        """Вещь на общей полке школы — мимо API, для тестов про чтение."""
        return Attachment.objects.create(
            school_shelf=school or self.school,
            kind=fields.pop("kind", "link"),
            url=fields.pop("url", "https://example.org/regulations"),
            title=fields.pop("title", "Регламент"),
            **fields,
        )

    def put_on_shelf(self, owner=None, *, folder=None, **fields):
        """Вещь на столе, заведённая мимо API: тестам про чтение так проще."""
        owner = owner or self.user
        return Attachment.objects.create(
            bookmark_owner=owner,
            bookmark_folder=folder,
            kind=fields.pop("kind", "link"),
            url=fields.pop("url", "https://example.org/toolkit"),
            title=fields.pop("title", "Набор задач"),
            **fields,
        )

    def add(self, **body):
        return self.client.post("/api/attachments/", body)


class TheShelfBelongsToOnePersonTests(ShelfTestMixin, APITestCase):
    def test_a_folder_is_created_for_the_person_who_asked(self):
        answer = self.client.post(self.FOLDERS, {"title": "  Методика  "})

        self.assertEqual(answer.status_code, 201, answer.content)
        folder = Folder.objects.get()
        self.assertEqual(folder.owner, self.user)
        # пробелы по краям — след копирования из письма, а не имя
        self.assertEqual(folder.title, "Методика")

    def test_a_nameless_folder_is_refused(self):
        answer = self.client.post(self.FOLDERS, {"title": "   "})

        self.assertEqual(answer.status_code, 400, answer.content)
        self.assertEqual(answer.json()["code"], "folder_title_required")

    def test_the_list_shows_my_folders_and_nobody_elses(self):
        mine = self.make_folder(title="Моё")
        self.make_folder(self.colleague, title="Чужое")

        answer = self.client.get(self.FOLDERS)

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual([row["id"] for row in answer.json()], [mine.pk])

    def test_a_colleagues_folder_does_not_exist_for_me(self):
        """
        Чужая папка отвечает 404, а не «не ваше».

        Тут проект отступает от своего же правила про соседний урок (403,
        «внутри школы все знают, что коллеги существуют»): про чужие
        закладки не знает никто, и сообщать, что папка под этим номером
        занята, значит рассказывать о человеке то, чего он не показывал.
        """
        theirs = self.make_folder(self.colleague)

        for method, kwargs in (
            ("get", {}),
            ("patch", {"data": {"title": "Переименую"}}),
            ("delete", {}),
        ):
            with self.subTest(method):
                answer = getattr(self.client, method)(self.folder_url(theirs), **kwargs)
                self.assertEqual(answer.status_code, 404, answer.content)

        theirs.refresh_from_db()
        self.assertEqual(theirs.title, "Методика")

    def test_an_administrator_sees_no_more_than_anybody_else(self):
        """
        Администратор школы правит школу, а не чужие столы.

        Проверяется отдельно, потому что во всех остальных разделах
        администратор как раз может больше — и правило «где-то может, значит
        и здесь» стоило бы человеку его личных записок.
        """
        mine = self.make_folder()
        self.sign_in(self.admin)

        self.assertEqual(self.client.get(self.FOLDERS).json(), [])
        self.assertEqual(self.client.get(self.folder_url(mine)).status_code, 404)

    def test_the_shelf_is_a_section_for_employees(self):
        """Ученику и родителю раздел закрыт: у них другой интерфейс целиком."""
        parent = make_user(self.school, "parent@example.com", parent=True)

        for person in (self.student, parent):
            with self.subTest(person.email):
                self.sign_in(person)
                answer = self.client.get(self.FOLDERS)
                self.assertEqual(answer.status_code, 403, answer.content)
                self.assertEqual(answer.json()["code"], "teachers_only")


class WhatLiesOnTheShelfTests(ShelfTestMixin, APITestCase):
    def test_a_link_a_note_and_a_file_all_go_on_the_shelf(self):
        """Виды здесь те же три, что у материала урока, — в этом весь довод."""
        folder = self.make_folder()

        link = self.add(
            bookmark_folder=folder.pk,
            url="https://desmos.com",
            title="Десмос",
        )
        note = self.add(
            bookmark_owner=self.user.pk,
            kind="text",
            title="Спросить у Петровой пароль от проектора",
        )
        stored = self.add(
            bookmark_folder=folder.pk,
            file=make_upload(name="blank.pdf"),
        )

        for answer in (link, note, stored):
            self.assertEqual(answer.status_code, 201, answer.content)

        self.assertEqual(
            sorted(Attachment.objects.values_list("kind", flat=True)),
            ["file", "link", "text"],
        )
        # хозяин выведен из папки: экран называет папку, а не себя
        self.assertEqual(
            set(Attachment.objects.values_list("bookmark_owner_id", flat=True)),
            {self.user.pk},
        )

    def test_a_note_carries_its_own_words(self):
        """
        Приписка — это то, ради чего заведён третий вид: «зачем это мне».

        Название отвечает на «что это» и годится списком, а объяснение в
        двести знаков названием быть не может.
        """
        answer = self.add(
            bookmark_owner=self.user.pk,
            url="https://example.org/blank.pdf",
            title="Бланк",
            note="Печатать по две страницы на лист, иначе не хватает",
        )

        self.assertEqual(answer.status_code, 201, answer.content)
        self.assertEqual(
            Attachment.objects.get().note,
            "Печатать по две страницы на лист, иначе не хватает",
        )

    def test_the_note_can_be_written_afterwards(self):
        item = self.put_on_shelf()

        answer = self.client.patch(
            f"/api/attachments/{item.pk}/", {"note": "дополнить к четвергу"}
        )

        self.assertEqual(answer.status_code, 200, answer.content)
        item.refresh_from_db()
        self.assertEqual(item.note, "дополнить к четвергу")

    def test_everything_on_my_shelf_comes_in_one_list(self):
        """
        Экран берёт стол одним запросом и раскладывает по папкам сам.

        Поэтому список спрашивается по **хозяину**, а не по папке: иначе
        поиск по всему столу стоил бы запроса на каждую папку, а вещи «на
        виду» не попали бы в него вовсе.
        """
        folder = self.make_folder()
        inside = self.put_on_shelf(folder=folder, title="В папке")
        loose = self.put_on_shelf(title="На виду")
        self.put_on_shelf(self.colleague, title="Чужое")

        answer = self.client.get(f"/api/attachments/?bookmark_owner={self.user.pk}")

        self.assertEqual(answer.status_code, 200, answer.content)
        rows = {row["id"]: row for row in answer.json()}
        self.assertEqual(set(rows), {inside.pk, loose.pk})
        self.assertEqual(rows[inside.pk]["bookmark_folder"], folder.pk)
        self.assertIsNone(rows[loose.pk]["bookmark_folder"])

    def test_the_list_comes_back_in_the_order_things_were_laid_out(self):
        """
        Список отдаётся по позиции, а не в том порядке, как вернула база.

        Стережёт починку, которую видно только отсюда. `with_sharing`
        навешивает агрегат («на этот файл ссылается ещё кто-то»), а запрос с
        GROUP BY Django лишает `Meta.ordering` — **молча**. Полтора года это
        совпадало с порядком id и потому не замечалось; первое же
        перекладывание закладки (позиция меняется, id остаётся) совпадение
        сломало, и вещь садилась не туда, куда её положили.
        """
        first = self.put_on_shelf(title="Первым", position=0)
        second = self.put_on_shelf(title="Вторым", position=1)
        # позиция меняется, id остаётся — ровно тот случай, на котором
        # порядок id перестаёт совпадать с порядком человека
        first.position = 5
        first.save(update_fields=["position"])

        answer = self.client.get(f"/api/attachments/?bookmark_owner={self.user.pk}")

        self.assertEqual(
            [row["id"] for row in answer.json()], [second.pk, first.pk]
        )

    def test_a_colleagues_bookmark_does_not_exist_for_me(self):
        theirs = self.put_on_shelf(self.colleague)

        answer = self.client.get(f"/api/attachments/{theirs.pk}/")

        # не 403 «чужой урок», а 404: чужого стола для меня нет вовсе
        self.assertEqual(answer.status_code, 404, answer.content)
        self.assertEqual(
            self.client.delete(f"/api/attachments/{theirs.pk}/").status_code, 404
        )

    def test_nothing_can_be_put_on_somebody_elses_shelf(self):
        """
        Владелец приезжает телом запроса, и границу держит выборка поля.

        Отказ выходит невалидным полем, а не отдельной проверкой, — тем же
        путём, каким отказывает чужая строка плана.
        """
        answers = [
            self.add(
                bookmark_owner=self.colleague.pk,
                url="https://example.org",
                title="Подложить коллеге",
            ),
            self.add(
                bookmark_folder=self.make_folder(self.colleague).pk,
                url="https://example.org",
                title="То же, но через папку",
            ),
        ]

        for answer in answers:
            self.assertEqual(answer.status_code, 400, answer.content)
        self.assertFalse(Attachment.objects.exists())

    def test_a_shelf_has_no_text_for_a_picture_to_stand_in(self):
        """
        `inline` — про картинку внутри содержания, а содержания тут нет.

        Молча принятый признак дал бы закладку, которой не видно ни в
        списке, ни в тексте: убрать её было бы нечем.
        """
        answer = self.add(
            bookmark_owner=self.user.pk,
            file=make_upload(name="board.png", kind="image/png"),
            inline="true",
        )

        self.assertEqual(answer.status_code, 400, answer.content)
        self.assertEqual(answer.json()["code"], "attachment_kind_mismatch")


class TidyingUpTheShelfTests(ShelfTestMixin, APITestCase):
    def test_a_folder_can_be_renamed(self):
        folder = self.make_folder()

        answer = self.client.patch(self.folder_url(folder), {"title": "Олимпиады"})

        self.assertEqual(answer.status_code, 200, answer.content)
        folder.refresh_from_db()
        self.assertEqual(folder.title, "Олимпиады")

    def test_removing_a_folder_keeps_what_was_inside_it(self):
        """
        Папка уходит, вещи ложатся на стол — и файл остаётся файлом.

        Ради этого папка и сделана адресом, а не владельцем: «прибрался в
        папках» не должно означать «удалил свои материалы», а удалять их
        пришлось бы каскадом, будь папка владельцем.
        """
        folder = self.make_folder()
        stored = make_stored_file(self.school, self.user)
        item = self.put_on_shelf(
            folder=folder, kind="file", url="", title="Бланк", stored_file=stored
        )

        answer = self.client.delete(self.folder_url(folder))

        self.assertEqual(answer.status_code, 204, answer.content)
        item.refresh_from_db()
        self.assertEqual(item.bookmark_owner, self.user)
        self.assertIsNone(item.bookmark_folder)
        self.assertTrue(StoredFile.objects.filter(pk=stored.pk).exists())

    def test_an_item_moves_between_folders_and_lands_last(self):
        """
        Переложить — это правка ссылки, а не вторая загрузка того же файла.

        Позиция при этом пересчитывается: иначе вещь, переехавшая из первой
        папки в третью, села бы в её середину — на место, которого ей никто
        не назначал.
        """
        first, second = self.make_folder(title="Первая"), self.make_folder(title="Вторая")
        moving = self.put_on_shelf(folder=first, title="Переезжает", position=0)
        self.put_on_shelf(folder=second, title="Уже лежит", position=1)

        answer = self.client.patch(
            f"/api/attachments/{moving.pk}/", {"bookmark_folder": second.pk}
        )

        self.assertEqual(answer.status_code, 200, answer.content)
        moving.refresh_from_db()
        self.assertEqual(moving.bookmark_folder, second)
        self.assertEqual(
            list(
                Attachment.objects.filter(bookmark_folder=second).values_list(
                    "title", flat=True
                )
            ),
            ["Уже лежит", "Переезжает"],
        )

    def test_an_item_cannot_move_into_a_colleagues_folder(self):
        item = self.put_on_shelf()
        theirs = self.make_folder(self.colleague)

        answer = self.client.patch(
            f"/api/attachments/{item.pk}/", {"bookmark_folder": theirs.pk}
        )

        self.assertEqual(answer.status_code, 400, answer.content)
        item.refresh_from_db()
        self.assertIsNone(item.bookmark_folder)

    def test_a_lesson_material_cannot_be_folded_into_a_personal_shelf(self):
        """
        Папка у чужого владельца — это не «переложить», а «сменить хозяина».

        Разреши это, и материал курса ушёл бы на личную полку — молча, и для
        следующего ведущего необратимо.
        """
        course = make_course(self.school)
        row = make_node(self.user, course)
        material = Attachment.objects.create(
            plan_row=row, kind="link", url="https://example.org", title="Карточки"
        )
        folder = self.make_folder()

        answer = self.client.patch(
            f"/api/attachments/{material.pk}/", {"bookmark_folder": folder.pk}
        )

        self.assertEqual(answer.status_code, 400, answer.content)
        self.assertEqual(answer.json()["code"], "attachment_kind_mismatch")
        material.refresh_from_db()
        self.assertIsNone(material.bookmark_folder)

    def test_the_last_reference_takes_the_object_with_it(self):
        """
        Снос закладки-файла ведёт себя так же, как снос материала урока.

        Проверяется здесь потому, что пятый владелец — новая дорога к тому
        же сигналу: забудь его, и стол копил бы объекты, на которые никто не
        ссылается.
        """
        stored = make_stored_file(self.school, self.user)
        item = self.put_on_shelf(
            kind="file", url="", title="Бланк", stored_file=stored
        )

        with self.captureOnCommitCallbacks(execute=True):
            answer = self.client.delete(f"/api/attachments/{item.pk}/")

        self.assertEqual(answer.status_code, 204, answer.content)
        self.assertFalse(StoredFile.objects.filter(pk=stored.pk).exists())

    def test_the_shelf_leaves_with_its_owner(self):
        """
        Ушёл человек — ушёл его стол: наследовать личное некому.

        Обратное было бы хуже отсутствия закладок: чужие записки, у которых
        больше нет хозяина, но которые кто-то однажды увидит.
        """
        folder = self.make_folder(self.colleague)
        self.put_on_shelf(self.colleague, folder=folder)

        self.colleague.delete()

        self.assertFalse(Folder.objects.filter(pk=folder.pk).exists())
        self.assertFalse(Attachment.objects.filter(bookmark_owner_id=None).exists())


class TheShelfIsNotACourseTests(ShelfTestMixin, APITestCase):
    def test_losing_a_course_does_not_touch_the_shelf(self):
        """
        Стол не принадлежит курсу, и в этом половина его смысла.

        План, расписание и работы курс забирает с собой при смене ведущего —
        это записано в правилах и верно. Личные ссылки так забирать нельзя:
        человек складывал их себе, а не курсу.
        """
        from schedule.models import CourseAssignment

        course = make_course(self.school)
        make_node(self.user, course)
        item = self.put_on_shelf()

        CourseAssignment.objects.filter(teacher=self.user).delete()

        answer = self.client.get(f"/api/attachments/?bookmark_owner={self.user.pk}")
        self.assertEqual([row["id"] for row in answer.json()], [item.pk])

    def test_a_stranger_from_another_school_reaches_nothing(self):
        item = self.put_on_shelf()
        folder = self.make_folder()

        client = APIClient()
        from schools.testing import sign_in

        sign_in(client, self.stranger)

        self.assertEqual(client.get(f"/api/attachments/{item.pk}/").status_code, 404)
        self.assertEqual(client.get(self.folder_url(folder)).status_code, 404)


class TheSchoolShelfTests(ShelfTestMixin, APITestCase):
    """
    Общая полка: администратор кладёт, сотрудники видят и не правят.

    Форма доступа тут обычная школьная — «читают все, пишет администратор», —
    и этим полка отличается от личного стола обоими краями. Проверять её
    поэтому надо отдельно: правило «чужое не видно», верное для стола,
    здесь неверно, и наоборот.
    """

    def test_an_administrator_puts_a_link_on_the_school_shelf(self):
        self.sign_in(self.admin)
        answer = self.add(
            school_shelf=self.school.pk,
            url="https://example.org/regulations",
            title="Регламент",
            note="Подписи собирает секретарь",
        )

        self.assertEqual(answer.status_code, 201, answer.content)
        item = Attachment.objects.get()
        self.assertEqual(item.school_shelf, self.school)
        self.assertIsNone(item.bookmark_owner)

    def test_an_ordinary_teacher_cannot_put_anything_there(self):
        """
        Отказ приходит **невалидным полем**, а не отдельной проверкой.

        Та же граница, что у чужого стола: выборка поля не знает школ, куда
        этому человеку класть нельзя, — и «положить на полку, не будучи
        администратором» отклоняется на входе, до всякой загрузки файла.

        Отказ поэтому 400, а не 403, и это осознанно. Право здесь спрашивает
        **поле**, а не вьюха: правил бы полку кто-то ещё — скажем, завуч, —
        и разрешение выражалось бы одной строкой в `writable_school_shelves`,
        а не второй проверкой в третьем месте. Цена названа: по коду ответа
        «нельзя вам» неотличимо от «нет такой школы».
        """
        answer = self.add(
            school_shelf=self.school.pk,
            url="https://example.org/mine",
            title="Подложу всем",
        )

        self.assertEqual(answer.status_code, 400, answer.content)
        self.assertFalse(Attachment.objects.exists())

    def test_every_employee_of_the_school_sees_the_shelf(self):
        item = self.put_on_school_shelf()

        for person in (self.user, self.colleague, self.admin):
            with self.subTest(person.email):
                self.sign_in(person)
                answer = self.client.get(
                    f"/api/attachments/?school_shelf={self.school.pk}"
                )
                self.assertEqual(answer.status_code, 200, answer.content)
                self.assertEqual([row["id"] for row in answer.json()], [item.pk])

    def test_a_teacher_reads_it_but_may_not_change_it(self):
        """
        Отказ здесь **403, а не 404**, и это не мелочь.

        Полка у учителя на экране: он на неё смотрит каждый день. Ответить
        «нет такого» на объект, который человек видит, значит соврать так,
        что это заметно, — а «не ваше» отвечает на его настоящий вопрос.
        """
        item = self.put_on_school_shelf()

        answer = self.client.patch(
            f"/api/attachments/{item.pk}/", {"title": "Переименую"}
        )
        self.assertEqual(answer.status_code, 403, answer.content)
        self.assertEqual(answer.json()["code"], "attachment_forbidden")

        self.assertEqual(
            self.client.delete(f"/api/attachments/{item.pk}/").status_code, 403
        )
        item.refresh_from_db()
        self.assertEqual(item.title, "Регламент")

    def test_the_administrator_renames_and_removes(self):
        item = self.put_on_school_shelf()
        self.sign_in(self.admin)

        renamed = self.client.patch(
            f"/api/attachments/{item.pk}/", {"title": "Регламент 2027"}
        )
        self.assertEqual(renamed.status_code, 200, renamed.content)

        self.assertEqual(
            self.client.delete(f"/api/attachments/{item.pk}/").status_code, 204
        )
        self.assertFalse(Attachment.objects.exists())

    def test_another_schools_shelf_does_not_exist_here(self):
        theirs = self.put_on_school_shelf(self.alien_school)

        answer = self.client.get(f"/api/attachments/{theirs.pk}/")

        self.assertEqual(answer.status_code, 404, answer.content)
        self.assertEqual(
            self.client.get(
                f"/api/attachments/?school_shelf={self.alien_school.pk}"
            ).json(),
            [],
        )

    def test_the_family_never_sees_the_school_shelf(self):
        """
        Ученику и родителю полка не показывается вовсе.

        На ней лежит то, что нужно **работающим**: регламенты, бланки,
        внутренние адреса. Семье это не «лишняя строка», а чужая изнанка
        школы, и попасть туда она может ровно одним способом — если кто-то
        забудет, что членство в школе есть и у неё.
        """
        self.put_on_school_shelf()
        parent = make_user(self.school, "parent@example.com", parent=True)

        for person in (self.student, parent):
            with self.subTest(person.email):
                self.sign_in(person)
                answer = self.client.get(
                    f"/api/attachments/?school_shelf={self.school.pk}"
                )
                self.assertEqual(answer.status_code, 200, answer.content)
                self.assertEqual(answer.json(), [])

    def test_the_school_shelf_is_not_a_personal_folder(self):
        """Папки — принадлежность личного стола: у общей полки их нет."""
        item = self.put_on_school_shelf()
        folder = self.make_folder()
        self.sign_in(self.admin)

        answer = self.client.patch(
            f"/api/attachments/{item.pk}/", {"bookmark_folder": folder.pk}
        )

        self.assertEqual(answer.status_code, 400, answer.content)
        item.refresh_from_db()
        self.assertIsNone(item.bookmark_folder)

    def test_the_shelf_outlives_the_person_who_filled_it(self):
        """
        Ушёл администратор — регламент остался.

        Ради этого полка и сделана владельцем, а не признаком «общее» у
        личной вещи: у признака остался бы хозяин, и `CASCADE` унёс бы
        общее у всех разом в день, когда человек уходит из школы.
        """
        self.sign_in(self.admin)
        answer = self.add(
            school_shelf=self.school.pk,
            url="https://example.org/regulations",
            title="Регламент",
        )
        self.assertEqual(answer.status_code, 201, answer.content)

        self.admin.delete()

        self.assertEqual(
            Attachment.objects.filter(school_shelf=self.school).count(), 1
        )
