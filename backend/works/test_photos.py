"""
Фотографии работы и разметка на них.

Проверяется здесь три вещи, и все три — про границы, а не про механику.

**Чужого не видно.** Тетрадь одноклассника для ученика не существует вовсе, и
не «запрещена»: знать, что у соседа что-то лежит, ему тоже незачем.

**Кто и когда кладёт.** Снимок принимается по тем же двум условиям, что и
ответ (окно и зачисление), и **не** спрашивает про открытость ячейки: закрытая
ячейка значит «решайте на листе», а фотография листа — ровно то, чем её и
сдают. Родитель кладёт за ребёнка; отвечать за него он по-прежнему не может.

**Кто размечает.** Обводка и приколотая заметка — слова учителя о работе, и
рисовать их ученик не может. Разговаривать в заметке — может: за этим её и
заводили.
"""

from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from families.models import Guardianship
from files.models import Attachment
from rest_framework.test import APITestCase
from schools.services import enrol
from schools.testing import (
    SchoolTestMixin,
    make_course,
    make_task,
    make_user,
    make_work,
    make_year,
)

from .models import PhotoNote, PhotoStroke, StudentWork

# однопиксельный PNG: тесты проверяют правила, а не картинку
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c63000100000500010d0a2db4000000"
    "0049454e44ae426082"
)


def photo(name="тетрадь.png"):
    return SimpleUploadedFile(name, PNG, content_type="image/png")


class PhotoTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        self.task = make_task(self.work)

        self.classmate = make_user(self.school, "classmate@example.com", student=True)
        enrol(self.student, self.course, by=self.admin)
        enrol(self.classmate, self.course, by=self.admin)

        self.mum = make_user(self.school, "mum@example.com", parent=True)
        Guardianship.objects.create(parent=self.mum, child=self.student)

    def send(self, who, *, task=None, child=None, work=None):
        self.client.force_authenticate(who)
        body = {"file": photo()}
        if task is not None:
            body["task"] = task.pk
        if child is not None:
            body["child"] = child.pk
        return self.client.post(
            reverse("student-photos", args=[(work or self.work).pk]),
            body,
            format="multipart",
        )

    def sent(self, *, task=None, by=None):
        """Снимок, лежащий на работе, — заведённый обычной дверью."""
        answer = self.send(by or self.student, task=task)
        self.assertEqual(answer.status_code, 201, answer.data)
        return Attachment.objects.get(pk=answer.data["id"])


class SendingAPhotoTests(PhotoTestCase):
    def test_a_student_sends_a_photo_of_one_question(self):
        answer = self.send(self.student, task=self.task)

        self.assertEqual(answer.status_code, 201, answer.data)
        shot = Attachment.objects.get(pk=answer.data["id"])
        self.assertEqual(shot.task_id, self.task.pk)
        self.assertEqual(shot.student_work.student_id, self.student.pk)
        self.assertEqual(shot.added_by_id, self.student.pk)

    def test_a_photo_of_the_whole_work_names_no_question(self):
        """
        Снимок всей тетради — отдельный случай, а не снимок без адреса.

        Задач в работе бывает пятнадцать, и требовать снимка к каждой значит
        получить снимки к трём.
        """
        shot = self.sent()

        self.assertIsNone(shot.task_id)
        self.assertIsNotNone(shot.student_work_id)

    def test_several_photos_land_on_one_question(self):
        """Тетрадь снимают в нескольких кадрах, и это обычное дело."""
        self.sent(task=self.task)
        self.sent(task=self.task)

        self.assertEqual(Attachment.objects.filter(task=self.task).count(), 2)

    def test_one_row_serves_every_photo_of_one_student(self):
        """
        Строка «работа и ученик» заводится по требованию — и одна на всё.

        Снимок по задаче и снимок всей работы лежат на ней же, рядом с
        оценкой и комментарием: иначе просмотрщику пришлось бы собирать
        тетрадь ученика из двух источников.
        """
        self.sent(task=self.task)
        self.sent()

        self.assertEqual(
            StudentWork.objects.filter(work=self.work, student=self.student).count(), 1
        )

    def test_a_closed_question_still_takes_a_photo(self):
        """
        Закрытая ячейка — это «решайте на листе», а не запрет.

        Спроси мы `open_for_answers`, единственный законный способ сдать
        такой вопрос оказался бы закрыт: поля ответа нет, и фотография листа
        и есть ответ.
        """
        self.task.open_for_answers = False
        self.task.save(update_fields=["open_for_answers"])

        self.assertEqual(self.send(self.student, task=self.task).status_code, 201)

    def test_a_closed_work_takes_nothing(self):
        """Окно решает, принимается ли решение, — снимок это решение тоже."""
        self.work.opens_at = timezone.now() - timedelta(days=3)
        self.work.closes_at = timezone.now() - timedelta(days=1)
        self.work.save(update_fields=["opens_at", "closes_at"])

        answer = self.send(self.student, task=self.task)

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "work_closed")

    def test_a_student_removed_from_the_course_sends_nothing(self):
        from schedule.models import CourseStudent

        CourseStudent.objects.filter(course=self.course, student=self.student).update(
            removed_at=timezone.now()
        )

        answer = self.send(self.student, task=self.task)

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "not_in_course")

    def test_only_a_picture_comes_in(self):
        """
        Сюда шлют **снимок**, а не документ.

        Список — это то, что **просмотрщик умеет открыть**, а не «любой файл».
        Иначе работа ученика превратилась бы во второе файловое хранилище, где
        рядом с тетрадью лежит архив, который нечем ни показать, ни разметить.

        Раньше в списке были одни картинки, и PDF отказывали справедливо: мы
        обещали бы страницу, которую просмотрщик не нарисует. Теперь рисует —
        и отказ снят вместе с причиной, а не вместо неё (см.
        `AWorkThatCameAsAPdfTests`).
        """
        self.client.force_authenticate(self.student)

        answer = self.client.post(
            reverse("student-photos", args=[self.work.pk]),
            {"file": SimpleUploadedFile("работа.zip", b"PK\x03\x04", "application/zip")},
            format="multipart",
        )

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "photo_type_not_allowed")

    def test_a_question_of_another_work_does_not_exist_here(self):
        other = make_work(self.user, self.course, title="Другая")
        alien = make_task(other)

        answer = self.send(self.student, task=alien)

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "task_question_required")


class AParentSendsForTheChildTests(PhotoTestCase):
    """
    Родитель фотографирует тетрадь за ребёнка — и это не то же самое, что
    решать за него.

    У младшего школьника телефона нет, и требовать, чтобы снимок пришёл
    именно от ученика, значит не дать этой возможности вовсе. А вот ответ в
    поле остаётся за ним: смотреть за учёбой и учиться — разные вещи.
    """

    def test_a_parent_sends_a_photo_of_their_child(self):
        answer = self.send(self.mum, task=self.task, child=self.student)

        self.assertEqual(answer.status_code, 201, answer.data)
        shot = Attachment.objects.get(pk=answer.data["id"])
        self.assertEqual(shot.student_work.student_id, self.student.pk)

    def test_who_sent_it_is_written_down(self):
        """«Прислала мама» и «прислал Петя» — разные события."""
        answer = self.send(self.mum, task=self.task, child=self.student)

        self.assertEqual(
            Attachment.objects.get(pk=answer.data["id"]).added_by_id, self.mum.pk
        )

    def test_somebody_elses_child_does_not_exist(self):
        answer = self.send(self.mum, task=self.task, child=self.classmate)

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "not_your_child")

    def test_a_parent_still_cannot_answer(self):
        """Право на ответ осталось ученическим, и снимок его не расширил."""
        self.client.force_authenticate(self.mum)

        answer = self.client.post(
            reverse("student-answer", args=[self.task.pk]),
            {"answer": "42"},
            format="json",
        )

        self.assertEqual(answer.status_code, 403)


class WhoSeesAPhotoTests(PhotoTestCase):
    def setUp(self):
        super().setUp()
        self.shot = self.sent(task=self.task)

    def markup(self, who):
        self.client.force_authenticate(who)
        return self.client.get(reverse("photo-markup", args=[self.shot.pk]))

    def test_the_teacher_of_the_course_sees_it(self):
        self.assertEqual(self.markup(self.user).status_code, 200)

    def test_the_student_sees_their_own(self):
        self.assertEqual(self.markup(self.student).status_code, 200)

    def test_the_parent_sees_their_childs(self):
        self.assertEqual(self.markup(self.mum).status_code, 200)

    def test_a_classmate_gets_nothing_at_all(self):
        """
        Чужая тетрадь для ученика **не существует**, а не «запрещена».

        Разница здесь не педантичная: 403 сообщил бы, что у одноклассника
        что-то есть, — а знать об этом ему незачем.
        """
        self.assertEqual(self.markup(self.classmate).status_code, 404)

    def test_a_teacher_of_another_course_is_told_it_is_not_theirs(self):
        """Внутри школы «не ваше» полезнее, чем притворяться, что id свободен."""
        answer = self.markup(self.colleague)

        self.assertEqual(answer.status_code, 403)
        self.assertEqual(answer.data["code"], "attachment_forbidden")

    def test_another_school_sees_nothing(self):
        self.assertEqual(self.markup(self.stranger).status_code, 404)


class RemovingAPhotoTests(PhotoTestCase):
    def remove(self, who, shot):
        self.client.force_authenticate(who)
        return self.client.delete(reverse("student-photo", args=[shot.pk]))

    def test_a_student_takes_back_their_own_photo(self):
        shot = self.sent(task=self.task)

        self.assertEqual(self.remove(self.student, shot).status_code, 204)
        self.assertFalse(Attachment.objects.filter(pk=shot.pk).exists())

    def test_a_parent_takes_back_what_they_sent(self):
        answer = self.send(self.mum, task=self.task, child=self.student)
        shot = Attachment.objects.get(pk=answer.data["id"])

        self.assertEqual(self.remove(self.mum, shot).status_code, 204)

    def test_a_parent_does_not_take_back_what_the_child_sent(self):
        """
        Снимает **свой**, а не «семейный».

        Кто прислал, тот и передумал; чужую присланную работу не отзывает
        никто, даже мама, — иначе «я это не отправлял» перестало бы иметь
        ответ.
        """
        shot = self.sent(task=self.task, by=self.student)

        answer = self.remove(self.mum, shot)

        self.assertEqual(answer.status_code, 403)
        self.assertEqual(answer.data["code"], "attachment_forbidden")

    def test_a_closed_work_keeps_what_was_handed_in(self):
        """
        После закрытия окна снять присланное нельзя.

        Иначе это способ забрать работу задним числом: сдал, увидел отметку,
        отозвал. Окно решает, принимаются ли решения, — и «снять» тут ровно
        такое же решение, как «прислать».
        """
        shot = self.sent(task=self.task)
        self.work.closes_at = timezone.now() - timedelta(hours=1)
        self.work.save(update_fields=["closes_at"])

        answer = self.remove(self.student, shot)

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "work_closed")

    def test_the_teacher_removes_anything_on_their_course(self):
        shot = self.sent(task=self.task)
        self.client.force_authenticate(self.user)

        answer = self.client.delete(reverse("attachment-detail", args=[shot.pk]))

        self.assertEqual(answer.status_code, 204)

    def test_the_family_door_of_the_teacher_stays_shut(self):
        """
        Учительская дверь семье закрыта **вовсе**, даже за своим снимком.

        Две двери здесь не дублирование: та спрашивает «чей это урок», эта —
        «ваше ли это и не поздно ли». Пропусти семью в первую, и «не поздно
        ли» перестало бы спрашиваться никогда.
        """
        shot = self.sent(task=self.task)
        self.client.force_authenticate(self.student)

        answer = self.client.delete(reverse("attachment-detail", args=[shot.pk]))

        self.assertEqual(answer.status_code, 403)


class MarkingUpAPhotoTests(PhotoTestCase):
    def setUp(self):
        super().setUp()
        self.shot = self.sent(task=self.task)

    def stroke(self, who, **fields):
        self.client.force_authenticate(who)
        body = {
            "color": "#e11d48",
            "width": 8,
            "points": [[0.1, 0.1], [0.2, 0.3]],
            **fields,
        }
        return self.client.post(
            reverse("photo-strokes", args=[self.shot.pk]), body, format="json"
        )

    def test_the_teacher_draws_over_the_photo(self):
        answer = self.stroke(self.user)

        self.assertEqual(answer.status_code, 201, answer.data)
        self.assertEqual(PhotoStroke.objects.count(), 1)

    def test_the_photo_itself_is_never_rewritten(self):
        """
        Разметка — мазки поверх, а не переделанная картинка.

        То же решение, по которому у содержания урока хранится Markdown, а не
        HTML: вжечь пометки в изображение значило бы завести второй файл на
        каждую исправленную работу, потерять исходник и убить отмену.
        """
        before = self.shot.stored_file_id
        self.stroke(self.user)
        self.shot.refresh_from_db()

        self.assertEqual(self.shot.stored_file_id, before)

    def test_a_student_draws_nothing(self):
        """
        Красное на работе — слова учителя. Нарисуй его ученик, и «исправлено
        красным» перестало бы что-либо значить.
        """
        answer = self.stroke(self.student)

        self.assertEqual(answer.status_code, 403)
        self.assertEqual(answer.data["code"], "attachment_forbidden")

    def test_a_point_outside_the_picture_is_refused_and_not_squeezed(self):
        """
        Зажать в границы было бы хуже отказа: мазок молча переехал бы на
        край, и объяснить ученику, почему пометка не там, было бы нечем.
        """
        answer = self.stroke(self.user, points=[[1.4, 0.2]])

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "point_invalid")

    def test_the_pen_has_a_floor_and_a_ceiling(self):
        answer = self.stroke(self.user, width=900)

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "pen_width_invalid")

    def test_a_colour_is_six_digits_and_a_hash(self):
        answer = self.stroke(self.user, color="red; background: url(x)")

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "colour_invalid")

    def test_undo_takes_back_the_last_stroke(self):
        self.stroke(self.user)
        self.stroke(self.user)
        self.client.force_authenticate(self.user)

        answer = self.client.delete(reverse("photo-strokes", args=[self.shot.pk]))

        self.assertEqual(answer.status_code, 200)
        self.assertTrue(answer.data["undone"])
        self.assertEqual(PhotoStroke.objects.count(), 1)

    def test_undo_with_nothing_drawn_is_not_an_error(self):
        """Край — не ошибка, ровно как у перемещения задачи."""
        self.client.force_authenticate(self.user)

        answer = self.client.delete(reverse("photo-strokes", args=[self.shot.pk]))

        self.assertEqual(answer.status_code, 200)
        self.assertFalse(answer.data["undone"])

    def test_undo_never_reaches_somebody_elses_stroke(self):
        """
        Отменяется **свой** последний мазок.

        Иначе двое, проверяющие одну работу — учитель и заменяющий его
        администратор, — стирали бы друг за другом, и виноватого не найти.
        """
        self.stroke(self.user)
        self.client.force_authenticate(self.admin)

        answer = self.client.delete(reverse("photo-strokes", args=[self.shot.pk]))

        self.assertFalse(answer.data["undone"])
        self.assertEqual(PhotoStroke.objects.count(), 1)

    def test_the_student_sees_what_the_teacher_drew(self):
        """
        Проверка красным, которой не видно, — разговор с самим собой.
        """
        self.stroke(self.user)
        self.client.force_authenticate(self.student)

        answer = self.client.get(reverse("photo-markup", args=[self.shot.pk]))

        self.assertEqual(len(answer.data["strokes"]), 1)
        self.assertFalse(answer.data["can_draw"])


class RotatingAPhotoTests(PhotoTestCase):
    def setUp(self):
        super().setUp()
        self.shot = self.sent(task=self.task)

    def turn(self, who, degrees):
        self.client.force_authenticate(who)
        return self.client.patch(
            reverse("photo-markup", args=[self.shot.pk]),
            {"rotation": degrees},
            format="json",
        )

    def test_the_teacher_turns_a_sideways_photo(self):
        """
        Поворот хранится, а не живёт во вкладке.

        Снятая боком тетрадь снята боком навсегда: поворот в памяти экрана
        каждый делал бы заново при каждом открытии, а ученик не увидел бы
        его вовсе.
        """
        self.assertEqual(self.turn(self.user, 90).status_code, 200)

        self.shot.refresh_from_db()
        self.assertEqual(self.shot.rotation, 90)

    def test_turning_back_to_upright_works(self):
        """
        Ноль — такой же поворот, как остальные три.

        Читался он как «поворот не прислали»: разбор стоял на `raw or ""`, а
        `0 or ""` в питоне даёт пустую строку. Снаружи это выглядело так, что
        снимок крутится по кругу, но не возвращается в исходное положение, —
        и объяснить это было нечем.
        """
        self.turn(self.user, 90)

        self.assertEqual(self.turn(self.user, 0).status_code, 200)

        self.shot.refresh_from_db()
        self.assertEqual(self.shot.rotation, 0)

    def test_a_turn_left_unsaid_is_refused_rather_than_read_as_zero(self):
        """Пропущенный поворот — ошибка запроса, а не тихий возврат к нулю."""
        self.turn(self.user, 180)
        self.client.force_authenticate(self.user)

        answer = self.client.patch(
            reverse("photo-markup", args=[self.shot.pk]), {}, format="json"
        )

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "rotation_invalid")
        self.shot.refresh_from_db()
        self.assertEqual(self.shot.rotation, 180)

    def test_only_four_turns_exist(self):
        answer = self.turn(self.user, 45)

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "rotation_invalid")

    def test_turning_leaves_the_marks_where_they_were(self):
        """
        Мазки живут в осях **исходника**, и поворот их не переписывает.

        Считай мы координаты от повёрнутой картинки, каждый поворот пришлось
        бы переписывать во всех мазках разом — и первый же пропущенный
        оставил бы пометку не на том месте, молча.
        """
        self.client.force_authenticate(self.user)
        self.client.post(
            reverse("photo-strokes", args=[self.shot.pk]),
            {"color": "#111111", "width": 5, "points": [[0.1, 0.2]]},
            format="json",
        )
        self.turn(self.user, 270)

        self.assertEqual(PhotoStroke.objects.get().points, [[0.1, 0.2]])

    def test_a_student_turns_nothing(self):
        answer = self.turn(self.student, 90)

        self.assertEqual(answer.status_code, 403)


class NotesOnAPhotoTests(PhotoTestCase):
    def setUp(self):
        super().setUp()
        self.shot = self.sent(task=self.task)

    def pin(self, who, text="Здесь потерян минус", x=0.4, y=0.6):
        self.client.force_authenticate(who)
        return self.client.post(
            reverse("photo-notes", args=[self.shot.pk]),
            {"x": x, "y": y, "text": text},
            format="json",
        )

    def say(self, who, note, text):
        self.client.force_authenticate(who)
        return self.client.post(
            reverse("photo-note", args=[note]), {"text": text}, format="json"
        )

    def test_the_teacher_pins_a_note_to_a_place(self):
        answer = self.pin(self.user)

        self.assertEqual(answer.status_code, 201, answer.data)
        self.assertEqual(PhotoNote.objects.count(), 1)
        self.assertEqual(len(answer.data["messages"]), 1)

    def test_a_note_without_words_is_not_pinned(self):
        """
        Булавка без слов — точка на картинке, которую некому объяснить.

        Оставь мы такую в базе, ученик увидел бы пустой кружок и пошёл
        спрашивать, что он значит.
        """
        answer = self.pin(self.user, text="   ")

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "message_empty")
        self.assertFalse(PhotoNote.objects.exists())

    def test_the_student_answers_in_the_note(self):
        """За этим её и заводили: «здесь потерян минус» без ответа — объявление."""
        note = self.pin(self.user).data["id"]

        answer = self.say(self.student, note, "А почему? Я же подставил.")

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(len(answer.data["messages"]), 2)

    def test_the_parent_answers_too(self):
        note = self.pin(self.user).data["id"]

        self.assertEqual(self.say(self.mum, note, "Разберём дома").status_code, 200)

    def test_a_classmate_finds_no_such_note(self):
        note = self.pin(self.user).data["id"]

        self.assertEqual(self.say(self.classmate, note, "ха").status_code, 404)

    def test_a_student_pins_nothing(self):
        answer = self.pin(self.student)

        self.assertEqual(answer.status_code, 403)

    def test_only_the_one_who_marks_up_removes_a_note(self):
        """Заметка — часть проверки, и снять её значит снять проверку."""
        note = self.pin(self.user).data["id"]
        self.client.force_authenticate(self.student)

        answer = self.client.delete(reverse("photo-note", args=[note]))

        self.assertEqual(answer.status_code, 403)
        self.assertTrue(PhotoNote.objects.filter(pk=note).exists())

    def test_a_message_belongs_to_one_conversation(self):
        """
        У сообщения один предмет: тред задачи **или** место на снимке.

        Одна таблица с двумя владельцами — тем же приёмом, что у оценки и у
        вложения: чат будет читать их одной лентой, а две таблицы разошлись
        бы в первой же правке.
        """
        from .models import Message

        note = self.pin(self.user).data["id"]
        message = Message.objects.get(note_id=note)

        self.assertIsNone(message.thread_id)


class ThePhotosOfOneStudentTests(PhotoTestCase):
    """
    Просмотрщик листает **внутри набора**, и наборов два.

    Открыли снимки задачи — листаются снимки этой задачи; открыли работу
    целиком — снимки, приложенные к ней целиком. Смешать их значило бы
    показывать при листании то, за чем не приходили.
    """

    def test_the_teacher_asks_for_one_students_photos(self):
        self.sent(task=self.task)
        self.sent()
        self.client.force_authenticate(self.user)

        answer = self.client.get(
            f"{reverse('work-student-photos', args=[self.work.pk])}"
            f"?student={self.student.pk}"
        )

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(len(answer.data["work"]), 1)
        self.assertEqual(len(answer.data["tasks"][0]["photos"]), 1)

    def test_the_student_gets_their_photos_with_the_work(self):
        """
        Свои снимки видны **всегда**, а не по `show_result`.

        Тот флаг про отметку, разошедшуюся по классу; собственная исписанная
        тетрадь ни к кому больше не относится.
        """
        self.sent(task=self.task)
        self.work.show_result = False
        self.work.save(update_fields=["show_result"])
        self.client.force_authenticate(self.student)

        answer = self.client.get(reverse("student-work", args=[self.work.pk]))

        self.assertEqual(len(answer.data["tasks"][0]["photos"]), 1)

    def test_a_photo_of_a_question_is_not_a_paper_of_the_whole_work(self):
        """
        У снимка задачи свой адрес, и в общем списке он читался бы как
        снимок всей тетради.
        """
        self.sent(task=self.task)
        self.client.force_authenticate(self.student)

        answer = self.client.get(reverse("student-work", args=[self.work.pk]))

        self.assertEqual(answer.data["papers"], [])

    def test_a_new_photo_moves_the_polling_mark(self):
        """
        Класс снимает тетради на уроке, и снимки обязаны появляться в
        таблице сами — иначе учитель обновляет страницу руками весь урок.
        """
        from . import services

        before = services.table_version(self.work)
        self.sent(task=self.task)

        self.assertNotEqual(before, services.table_version(self.work))

    def test_a_pinned_note_moves_the_students_mark(self):
        """Прикреплённая к клетке фраза — это проверка, и доехать она обязана."""
        from . import services

        shot = self.sent(task=self.task)
        before = services.student_version(self.work, self.student)

        self.client.force_authenticate(self.user)
        self.client.post(
            reverse("photo-notes", args=[shot.pk]),
            {"x": 0.5, "y": 0.5, "text": "Смотри знак"},
            format="json",
        )

        self.assertNotEqual(
            before, services.student_version(self.work, self.student)
        )


# минимальный PDF в две страницы: тесты проверяют правила приёма, а не вёрстку
PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R 4 0 R]/Count 2>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
    b"4 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


class AWorkThatCameAsAPdfTests(PhotoTestCase):
    """
    Тетрадь приходит и снимком, и PDF'ом, и разметить надо обе.

    Отказ на приёме был честным ровно до тех пор, пока просмотрщик не умел
    страницу: обещать разметку файла, который нечем показать, хуже, чем не
    принять его. Теперь умеет — и отказ снят вместе с причиной, а не вместо
    неё.

    Телефонный сканер отдаёт именно PDF, и до этого он был тупиком: ученик
    сдал работу, учитель видит строку со скрепкой и обвести в ней нечего.
    """

    def pdf(self, name="тетрадь.pdf"):
        return SimpleUploadedFile(name, PDF, content_type="application/pdf")

    def send_pdf(self, who=None, name="тетрадь.pdf"):
        self.client.force_authenticate(who or self.student)
        return self.client.post(
            reverse("student-photos", args=[self.work.pk]),
            {"file": self.pdf(name)},
            format="multipart",
        )

    def test_a_pdf_of_the_notebook_is_accepted(self):
        answer = self.send_pdf()

        self.assertEqual(answer.status_code, 201, answer.data)

    def test_the_screen_is_told_it_can_open_it(self):
        """
        Два разных вопроса, и разошлись они ровно тут: нарисовать это одним
        тегом нельзя (`image`), а открыть и разметить — можно (`viewable`).
        Ответь мы одним полем, PDF-тетрадь осталась бы строкой со скрепкой.
        """
        self.send_pdf()
        self.client.force_authenticate(self.user)

        sheet = self.client.get(
            f"/api/works/{self.work.pk}/photos/", {"student": self.student.pk}
        ).json()
        shot = sheet["work"][0]

        self.assertFalse(shot["image"])
        self.assertTrue(shot["viewable"])
        self.assertTrue(shot["pdf"])


class MarksKnowTheirPageTests(PhotoTestCase):
    """
    Страница — часть адреса пометки, ровно как доля координаты.

    Доли отвечают «где на листе», страница — «на каком листе». У снимка второй
    вопрос имеет единственный ответ, у семистраничной тетради — нет, и без
    него пометка со второй страницы легла бы на первую. Молча: доли-то в
    границах, мазок нарисован, просто не там.
    """

    def setUp(self):
        super().setUp()
        self.shot = self.sent(task=self.task)
        self.client.force_authenticate(self.user)

    def stroke(self, page=None, **fields):
        body = {"color": "#e11d48", "width": 8, "points": [[0.1, 0.1]], **fields}
        if page is not None:
            body["page"] = page
        return self.client.post(
            reverse("photo-strokes", args=[self.shot.pk]), body, format="json"
        )

    def test_a_stroke_remembers_its_page(self):
        answer = self.stroke(page=3)

        self.assertEqual(answer.status_code, 201, answer.data)
        self.assertEqual(answer.data["page"], 3)
        self.assertEqual(PhotoStroke.objects.get().page, 3)

    def test_a_photo_says_nothing_and_means_the_only_page(self):
        """
        У снимка страниц нет, и ноль тут — не «страница не указана», а «она
        единственная». NULL завёл бы два кода на один случай.
        """
        self.stroke()

        self.assertEqual(PhotoStroke.objects.get().page, 0)

    def test_a_page_that_is_not_a_number_is_refused(self):
        self.assertEqual(self.stroke(page="вторая").status_code, 400)
        self.assertEqual(self.stroke(page=-1).data["code"], "page_invalid")

    def test_undo_takes_the_stroke_off_the_page_in_front_of_you(self):
        """
        Человек смотрит на седьмую страницу и нажимает «отменить». Сними мы
        мазок с третьей — на экране не произойдёт ничего, а работа пропадёт;
        и нажмут ещё раз.
        """
        self.stroke(page=0)
        self.stroke(page=7)

        answer = self.client.delete(
            reverse("photo-strokes", args=[self.shot.pk]) + "?page=7"
        )

        self.assertTrue(answer.data["undone"])
        self.assertEqual([one.page for one in PhotoStroke.objects.all()], [0])

    def test_undo_on_an_untouched_page_takes_nothing(self):
        self.stroke(page=0)

        answer = self.client.delete(
            reverse("photo-strokes", args=[self.shot.pk]) + "?page=5"
        )

        self.assertFalse(answer.data["undone"])
        self.assertEqual(PhotoStroke.objects.count(), 1)

    def test_a_note_is_pinned_to_a_page_too(self):
        answer = self.client.post(
            reverse("photo-notes", args=[self.shot.pk]),
            {"x": 0.4, "y": 0.6, "text": "здесь потерян минус", "page": 2},
            format="json",
        )

        self.assertEqual(answer.status_code, 201, answer.data)
        self.assertEqual(answer.data["page"], 2)
        self.assertEqual(PhotoNote.objects.get().page, 2)

    def test_the_markup_arrives_in_one_answer_for_the_whole_document(self):
        """
        Одним ответом, а не по странице: листание тогда стоило бы запроса на
        каждое нажатие «дальше», и ответ был бы тот же самый. Раскладывает
        мазки по страницам экран — у него они уже есть.
        """
        self.stroke(page=0)
        self.stroke(page=4)

        markup = self.client.get(reverse("photo-markup", args=[self.shot.pk])).json()

        self.assertEqual(sorted(one["page"] for one in markup["strokes"]), [0, 4])
