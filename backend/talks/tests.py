"""
Разговор двух людей: кому можно писать, кто это читает и как оно собирается.

Часть этих проверок пришла из `families/tests.py` вместе с перепиской: там они
стерегли разговор родителя с учителем, и правила эти никуда не делись — мама с
папой по-прежнему пишут порознь, чужой разговор по-прежнему не читается. Просто
теперь это случай общего разговора, а не свой вид.
"""

from django.urls import reverse
from families.models import link
from rest_framework import status
from rest_framework.test import APITestCase
from schools.testing import (
    SchoolTestMixin,
    assign,
    make_course,
    make_user,
    make_year,
    sign_in,
)
from works.models import Message

from . import access, services
from .models import Talk


class WhoMayWriteTests(SchoolTestMixin, APITestCase):
    """
    Вопрос один — «есть ли вам о чём говорить», — а ответов три.

    Собеседник не меняет природы разговора, но меняет то, кто его начинает:
    коллеги свободно, семья по участию, семья с семьёй — никак.
    """

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        assign(self.user, self.course)

        self.nobodys_teacher = make_user(self.school, "teaches-nothing@example.com")
        self.child = make_user(self.school, "kid@example.com", student=True)
        self.course.students.create(student=self.child)
        self.mother = make_user(self.school, "mama@example.com", parent=True)
        link(self.mother, self.child, relation="мама")
        self.other_kid = make_user(self.school, "mate@example.com", student=True)

    def test_a_colleague_is_always_a_colleague(self):
        """
        Сотрудники школы пишут друг другу свободно.

        «Только по общим курсам» отсекло бы ровно те разговоры, ради которых
        мессенджер и заводят: «у тебя есть свободный кабинет во вторник?».
        """
        self.assertTrue(access.may_write_to(self.user, self.colleague))
        self.assertTrue(access.may_write_to(self.colleague, self.user))

    def test_the_family_writes_to_those_who_teach_it(self):
        self.assertTrue(access.may_write_to(self.child, self.user))
        self.assertTrue(access.may_write_to(self.mother, self.user))
        self.assertFalse(access.may_write_to(self.mother, self.nobodys_teacher))

    def test_the_family_does_not_write_to_the_family(self):
        """
        Школьный журнал не социальная сеть: переписку одноклассников в нём
        никто не модерирует, и отказ здесь — решение, а не недоделка.
        """
        self.assertFalse(access.may_write_to(self.child, self.other_kid))
        self.assertFalse(access.may_write_to(self.mother, self.child))

    def test_nobody_writes_to_another_school(self):
        # `stranger` из оснастки — учитель другой школы: разговор за школу не
        # выходит, и вид собеседника тут ничего не меняет
        self.assertFalse(access.may_write_to(self.user, self.stranger))

    def test_the_offered_list_and_the_check_agree(self):
        """
        Список «кому можно» и проверка «можно ли» считаются одним местом.

        Разойдись они — и экран предлагал бы собеседника, которому сервер
        писать не даёт: отказ на действии, которое сам же и предложил.
        """
        for person in access.partners(self.mother):
            self.assertTrue(access.may_write_to(self.mother, person), person)
        for person in access.partners(self.user):
            self.assertTrue(access.may_write_to(self.user, person), person)


class TalkingTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        assign(self.user, self.course)

        self.child = make_user(self.school, "kid@example.com", student=True)
        self.course.students.create(student=self.child)
        self.mother = make_user(self.school, "mama@example.com", parent=True)
        self.father = make_user(self.school, "papa@example.com", parent=True)
        link(self.mother, self.child, relation="мама")
        link(self.father, self.child, relation="папа")

    def test_the_pair_is_one_talk_whichever_side_starts(self):
        """
        «Иванова с Петровым» и «Петров с Ивановой» — один разговор.

        Без нормализации пары первый же ответ завёл бы второй, и переписка
        разъехалась бы на две ленты, каждая со своей половиной сказанного.
        """
        services.say(self.user, self.colleague, text="Привет")
        services.say(self.colleague, self.user, text="И тебе")

        self.assertEqual(Talk.objects.count(), 1)
        self.assertEqual(Message.objects.filter(talk__isnull=False).count(), 2)

    def test_mother_and_father_do_not_share_a_talk(self):
        """Иначе каждому показали бы чужую переписку."""
        services.say(self.mother, self.user, text="Как дела?", child=self.child)
        services.say(self.father, self.user, text="А у нас?", child=self.child)

        self.assertEqual(Talk.objects.filter(child=self.child).count(), 2)

    def test_an_empty_message_is_not_a_message(self):
        with self.assertRaises(Exception) as caught:
            services.say(self.user, self.colleague, text="   ")

        self.assertIn("message_empty", str(caught.exception.detail))

    def test_a_stranger_may_not_write(self):
        nobodys_teacher = make_user(self.school, "teaches-nothing@example.com")

        with self.assertRaises(Exception) as caught:
            services.say(self.mother, nobodys_teacher, text="Здравствуйте")

        self.assertIn("not_a_teacher_of_this_child", str(caught.exception.detail))

    def test_the_topic_has_to_be_your_own_child(self):
        """
        «Есть ли вам о чём говорить» и «о ком вы говорите» — разные вопросы.

        Второй права не даёт: разговор с учителем законен, а пометить его чужим
        ребёнком нельзя — иначе учитель видел бы у себя переписку о чужом
        ученике с посторонним взрослым.
        """
        somebody = make_user(self.school, "other-kid@example.com", student=True)
        self.course.students.create(student=somebody)

        with self.assertRaises(Exception) as caught:
            services.say(self.mother, self.user, text="Здравствуйте", child=somebody)

        self.assertIn("not_your_child", str(caught.exception.detail))

    def test_reading_a_conversation_marks_it_read(self):
        """
        Непрочитанное нужно затем, чтобы найти, где тебя ждут, — а не затем,
        чтобы им управлять. Поэтому открытое и есть прочитанное.
        """
        services.say(self.colleague, self.user, text="Загляни после урока")

        before = services.ribbon(self.user)["started"]
        self.assertEqual(before[0]["unread"], 1)

        services.conversation(self.user, self.colleague)

        after = services.ribbon(self.user)["started"]
        self.assertEqual(after[0]["unread"], 0)

    def test_my_own_message_is_not_unread(self):
        services.say(self.user, self.colleague, text="Привет")

        self.assertEqual(services.ribbon(self.user)["started"][0]["unread"], 0)


class OneRibbonTests(SchoolTestMixin, APITestCase):
    """
    Лента собирается **по собеседнику**, а не по поводу.

    Человек помнит, с кем он говорил, а не в какой таблице это лежало: вопрос
    ученика о задаче и ответ ему же «зайди после урока» — один разговор.
    """

    def setUp(self):
        super().setUp()
        from schools.testing import make_task, make_work

        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        assign(self.user, self.course)
        self.child = make_user(self.school, "kid@example.com", student=True)
        self.course.students.create(student=self.child)

        self.work = make_work(self.user, self.course)
        self.task = make_task(self.work)

    def test_a_question_about_a_task_and_a_plain_note_are_one_ribbon(self):
        from works import threads

        threads.say(self.task, student_id=self.child.pk, author=self.child, text="Не понял")
        services.say(self.user, self.child, text="Зайди после урока")

        ribbon = services.conversation(self.user, self.child)
        said = [row["text"] for row in ribbon["messages"]]

        self.assertEqual(said, ["Не понял", "Зайди после урока"])
        # у первой реплики есть повод, и по нему экран рисует ссылку к задаче
        self.assertEqual(ribbon["messages"][0]["task"], self.task.pk)
        self.assertIsNone(ribbon["messages"][1]["task"])

    def test_the_list_shows_one_row_per_person(self):
        """Разговор с человеком один, сколько бы поводов в нём ни было."""
        from works import threads

        threads.say(self.task, student_id=self.child.pk, author=self.child, text="Не понял")
        services.say(self.user, self.child, text="Зайди после урока")

        started = services.ribbon(self.user)["started"]

        self.assertEqual([row["id"] for row in started], [self.child.pk])


class TalkDoorTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        assign(self.user, self.course)
        self.child = make_user(self.school, "kid@example.com", student=True)
        self.course.students.create(student=self.child)

    def test_both_sides_see_the_talk_in_their_list(self):
        services.say(self.user, self.colleague, text="Привет")

        sign_in(self.client, self.user)
        mine = self.client.get(reverse("talks")).json()
        sign_in(self.client, self.colleague)
        theirs = self.client.get(reverse("talks")).json()

        self.assertEqual([row["id"] for row in mine["started"]], [self.colleague.pk])
        self.assertEqual([row["id"] for row in theirs["started"]], [self.user.pk])

    def test_a_stranger_does_not_read_the_conversation(self):
        """Разговор двух людей читают эти двое — и никто больше."""
        services.say(self.user, self.colleague, text="Привет")
        outsider = make_user(self.school, "third@example.com")

        sign_in(self.client, outsider)
        answer = self.client.get(reverse("talk", args=[self.user.pk]))

        # разговор чужой не «запрещён», а пуст: между этими двумя ничего не
        # было, и заглянуть в чужую переписку отсюда нельзя вовсе
        self.assertEqual(answer.status_code, status.HTTP_200_OK)
        self.assertEqual(answer.json()["messages"], [])

    def test_writing_to_somebody_you_have_nothing_to_do_with_is_refused(self):
        student_of_nobody = make_user(self.school, "far-kid@example.com", student=True)

        sign_in(self.client, student_of_nobody)
        answer = self.client.post(
            reverse("talk", args=[self.user.pk]), {"text": "Здравствуйте"}
        )

        self.assertEqual(answer.status_code, status.HTTP_403_FORBIDDEN)

    def test_another_school_does_not_exist(self):
        sign_in(self.client, self.user)
        answer = self.client.get(reverse("talk", args=[self.stranger.pk]))

        self.assertEqual(answer.status_code, status.HTTP_404_NOT_FOUND)

    def test_the_teacher_finally_reads_what_the_family_wrote(self):
        """
        Сторож на дыру, с которой всё началось: сервер отвечал обеим сторонам,
        а экран был смонтирован только у родителя. Учитель не мог ни прочитать
        сообщение, ни ответить.
        """
        mother = make_user(self.school, "mama@example.com", parent=True)
        link(mother, self.child, relation="мама")
        services.say(mother, self.user, text="Здравствуйте", child=self.child)

        sign_in(self.client, self.user)
        answer = self.client.get(reverse("talk", args=[mother.pk])).json()

        self.assertEqual([row["text"] for row in answer["messages"]], ["Здравствуйте"])
