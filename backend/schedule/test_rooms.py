"""
Кабинеты: справочник школы и предупреждение о занятости.

Занятость кабинета в этой школе **никогда не запрет**, и это решение
заказчика, а не упущение: два класса, загнанных в один кабинет, — обычное
дело, и отказ на этом месте заставил бы расписание врать. Остаётся
предупреждение, и здесь проверяется ровно то, из-за чего оно вообще имеет
смысл:

* оно видно **обоим** часам, а не только тому, кто пришёл вторым;
* оно видно **на чтение**, потому что конфликт создаёт чужая правка;
* у делимого помещения его нет вовсе — иначе горящий каждый день спортзал
  приучил бы отмахиваться и от настоящих.
"""

from datetime import timedelta

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import MONDAY, SchoolTestMixin, assign, make_course, make_year

from .models import Room, Slot

TUESDAY = MONDAY + timedelta(days=1)


class RoomTestCase(SchoolTestMixin, APITestCase):
    """Школа с двумя курсами разных учителей и парой кабинетов."""

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.mine = make_course(self.school, self.year, "9Б Алгебра")
        self.theirs = make_course(self.school, self.year, "10А Алгебра")
        assign(self.user, self.mine)
        assign(self.colleague, self.theirs)

        self.room = Room.objects.create(school=self.school, name="214")
        self.gym = Room.objects.create(
            school=self.school, name="Спортзал", is_shared=True
        )

    def slot(self, course, room=None, day=MONDAY, number=1, **flags):
        return Slot.objects.create(
            year=self.year,
            course=course,
            date=day,
            lesson_number=number,
            room=room,
            **flags,
        )

    def listing(self, **params):
        return self.client.get(
            reverse("slot-list"),
            {
                "scope": "school",
                "start": MONDAY.isoformat(),
                "end": (MONDAY + timedelta(days=6)).isoformat(),
                **params,
            },
        )

    def warnings_of(self, slot_id, **params):
        rows = self.listing(**params).json()
        return next(row["warnings"] for row in rows if row["id"] == slot_id)


class RoomListTests(RoomTestCase):
    """Справочник: читают все, правит администратор."""

    def test_a_teacher_reads_the_list_and_may_not_change_it(self):
        """
        Кабинет выбирает учитель, а заводит администратор.

        Тот же расклад, что у предметов и параллелей рядом: список
        принадлежит школе, а не тому, кто первым в него заглянул.
        """
        answer = self.client.get(reverse("room-list"))
        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual([row["name"] for row in answer.json()], ["214", "Спортзал"])

        refused = self.client.post(
            reverse("room-list"), {"name": "305"}, format="json"
        )
        self.assertEqual(refused.status_code, 403, refused.content)

    def test_an_administrator_adds_a_room(self):
        self.client.force_authenticate(self.admin)
        answer = self.client.post(
            reverse("room-list"), {"name": "305", "is_shared": True}, format="json"
        )

        self.assertEqual(answer.status_code, 201, answer.content)
        self.assertTrue(Room.objects.get(name="305").is_shared)

    def test_a_room_of_another_school_is_not_even_listed(self):
        Room.objects.create(school=self.alien_school, name="Чужой 101")

        names = [row["name"] for row in self.client.get(reverse("room-list")).json()]
        self.assertNotIn("Чужой 101", names)

    def test_a_room_with_lessons_is_not_deleted_but_archived(self):
        """
        «Урок шёл в 214» — факт прошедшего дня, и он не перестаёт быть
        правдой оттого, что кабинет отдали под склад. Для склада есть архив,
        о нём и говорит отказ.
        """
        self.slot(self.mine, room=self.room)
        self.client.force_authenticate(self.admin)

        refused = self.client.delete(reverse("room-detail", args=[self.room.pk]))
        self.assertEqual(refused.status_code, 400, refused.content)
        self.assertEqual(refused.json()["code"], "room_in_use")

        archived = self.client.patch(
            reverse("room-detail", args=[self.room.pk]),
            {"is_archived": True},
            format="json",
        )
        self.assertEqual(archived.status_code, 200, archived.content)
        self.assertTrue(Room.objects.get(pk=self.room.pk).is_archived)


class RoomIsBusyTests(RoomTestCase):
    """Предупреждение о занятости — то, ради чего кабинет вообще записан."""

    def test_two_lessons_in_one_room_warn_both_of_them(self):
        """
        Конфликт — свойство **пары**, и первый о нём узнаёт последним.

        Предупреждение, сказанное один раз в ответе на создание, увидел бы
        только тот, кто пришёл вторым. Поэтому оно считается на чтение и
        стоит у обоих часов, пока они стоят рядом.
        """
        first = self.slot(self.mine, room=self.room)
        second = self.slot(self.theirs, room=self.room)

        for slot in (first, second):
            (warning,) = self.warnings_of(slot.pk)
            self.assertEqual(warning["code"], "slot_room_busy")
            self.assertEqual(warning["params"]["room"], "214")

    def test_a_shared_room_says_nothing(self):
        """
        Спортзал вмещает два класса, и это норма, а не находка.

        Предупреждение, горящее каждый день, перестают читать через неделю —
        а вместе с ним перестают читать и все остальные.
        """
        first = self.slot(self.mine, room=self.gym)
        self.slot(self.theirs, room=self.gym)

        self.assertEqual(self.warnings_of(first.pk), [])

    def test_a_cancelled_lesson_frees_the_room(self):
        """Тем же правилом, что и номер у учителя: сорванный час места не занимает."""
        first = self.slot(self.mine, room=self.room)
        self.slot(self.theirs, room=self.room, is_cancelled=True, reason="Карантин")

        self.assertEqual(self.warnings_of(first.pk), [])

    def test_another_number_or_another_day_is_not_a_clash(self):
        first = self.slot(self.mine, room=self.room, number=1)
        self.slot(self.theirs, room=self.room, number=2)
        self.slot(self.theirs, room=self.room, day=TUESDAY, number=1)

        self.assertEqual(self.warnings_of(first.pk), [])

    def test_a_lesson_without_a_room_is_never_in_a_clash(self):
        """Пустое поле значит «не указан», а не «где-то там же, где все»."""
        first = self.slot(self.mine, room=None)
        self.slot(self.theirs, room=None)

        self.assertEqual(self.warnings_of(first.pk), [])

    def test_the_answer_to_one_slot_counts_the_clash_itself(self):
        """
        У одиночного ответа периода нет, и спросить он обязан сам.

        Иначе правка часа сообщала бы «всё в порядке» ровно там, где на
        экране рядом горит предупреждение, — и верить перестали бы обоим.
        """
        self.slot(self.theirs, room=self.room)
        mine = self.slot(self.mine, room=None)

        self.client.force_authenticate(self.admin)
        answer = self.client.patch(
            reverse("slot-detail", args=[mine.pk]),
            {"room": self.room.pk},
            format="json",
        )

        self.assertEqual(answer.status_code, 200, answer.content)
        (warning,) = answer.json()["warnings"]
        self.assertEqual(warning["code"], "slot_room_busy")

    def test_warnings_add_up_and_do_not_replace_each_other(self):
        """
        Урок в каникулы вполне может ещё и делить кабинет.

        Полем это было, пока предупреждение было одно; списком — потому что
        выбирать, о чём промолчать, тут нельзя: запрета нет ни у одного из
        них, и сказанное — единственное, что вообще сказано.
        """
        saturday = MONDAY + timedelta(days=5)
        first = self.slot(self.mine, room=self.room, day=saturday)
        self.slot(self.theirs, room=self.room, day=saturday)

        codes = {warning["code"] for warning in self.warnings_of(first.pk)}
        self.assertEqual(codes, {"slot_not_study_day", "slot_room_busy"})


class RoomTravelsWithTheLessonTests(RoomTestCase):
    """Кабинет — свойство клетки, и ведёт себя как остальные её поля."""

    def test_a_lesson_is_created_with_a_room(self):
        self.client.force_authenticate(self.admin)
        answer = self.client.post(
            reverse("slot-list"),
            {
                "course": self.mine.pk,
                "date": MONDAY.isoformat(),
                "lesson_number": 3,
                "room": self.room.pk,
            },
            format="json",
        )

        self.assertEqual(answer.status_code, 201, answer.content)
        self.assertEqual(answer.json()["room_name"], "214")
        self.assertEqual(Slot.objects.get(lesson_number=3).room, self.room)

    def test_a_room_alone_does_not_make_the_hour_a_record(self):
        """
        Проставленный кабинет — это «где стоит клетка», а не «что в ней
        произошло». Час, которому назначили кабинет и который так и не
        состоялся, остаётся пустой клеткой, и массовая чистка вправе его
        снести — иначе раскатанная по кабинетам сетка перестала бы
        перекопировываться.
        """
        empty = self.slot(self.mine, room=self.room)

        self.assertIn(empty, Slot.objects.filter(**Slot.empty_conditions()))

    def test_a_row_carries_the_room_into_every_hour_it_creates(self):
        """
        Кабинет — свойство **ряда**, а не той клетки, с которой он начался.

        «Вторник, третий час, 214, до конца года» — одно решение, и ряд без
        кабинета заставлял бы проставлять его потом по одному часу, то есть
        отменял бы смысл самого ряда. Спрашивают о нём в том же окне, что и
        о повторе, и терялся он молча: занятия появлялись, число в ответе
        сходилось, не хватало ровно того, о чём спросили рядом.
        """
        self.client.force_authenticate(self.admin)

        answer = self.client.post(
            reverse("slot-repeat"),
            {
                "course": self.mine.pk,
                "date": MONDAY.isoformat(),
                "lesson_number": 4,
                "step": 1,
                "until": (MONDAY + timedelta(days=14)).isoformat(),
                "room": self.room.pk,
            },
            format="json",
        )

        self.assertEqual(answer.status_code, 200, answer.content)
        row = Slot.objects.filter(course=self.mine, lesson_number=4)
        self.assertGreater(row.count(), 1, "ряд должен был завести больше часа")
        self.assertFalse(
            row.exclude(room=self.room).exists(),
            "часы ряда завелись без кабинета: он спрошен один раз на весь ряд",
        )

    def test_a_room_of_another_school_cannot_be_named(self):
        """
        Ключ в теле запроса идёт мимо фильтра вьюхи, поэтому сужено поле.

        Без сужения занятие вставало бы в кабинет соседней школы — и это не
        только неверная запись: имя кабинета едет обратно в `room_name`, то
        есть ответ рассказывал бы, как называются кабинеты у соседей.
        Спрашивают кабинет две двери, и сужены обе: одиночный час и ряд.
        """
        alien = Room.objects.create(school=self.alien_school, name="Чужой 101")
        self.client.force_authenticate(self.admin)

        one = self.client.post(
            reverse("slot-list"),
            {
                "course": self.mine.pk,
                "date": MONDAY.isoformat(),
                "lesson_number": 5,
                "room": alien.pk,
            },
            format="json",
        )
        row = self.client.post(
            reverse("slot-repeat"),
            {
                "course": self.mine.pk,
                "date": MONDAY.isoformat(),
                "lesson_number": 6,
                "step": 1,
                "until": (MONDAY + timedelta(days=14)).isoformat(),
                "room": alien.pk,
            },
            format="json",
        )

        self.assertEqual(one.status_code, 400, one.content)
        self.assertEqual(row.status_code, 400, row.content)
        self.assertFalse(Slot.objects.filter(room=alien).exists())
