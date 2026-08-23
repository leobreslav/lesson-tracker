"""
Двери фотографий: семья кладёт и смотрит, учитель размечает.

Дверей две, и они намеренно разные. Ученическая (`/api/student/…`) отвечает
на вопрос «моё ли это и не поздно ли» — как и все остальные ученические
адреса, отдельно от учительских. Дверь просмотрщика (`/api/works/photos/…`)
одна на обе стороны, потому что **смотрят они одну и ту же картинку с одними
и теми же пометками**: разведи её на две — и первая же правка развела бы то,
что видит учитель, и то, что видит ученик, а узнал бы об этом ученик.

Право тут поэтому не «кто вы по виду», а «чьё это»: отвечает `files.access`
на чтение и `works.photos` на всё остальное.
"""

from config.access import IsFamily, IsSchoolMember
from config.errors import Codes, api_denied, api_error
from django.shortcuts import get_object_or_404
from families.viewing import subject_of
from files import access as file_access
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import photos, services
from .models import PhotoNote


def whole(value, *, default=None):
    """
    Целое из тела запроса — или умолчание.

    Заведено ради одного случая, и случай этот успел стать ошибкой: `int(raw)
    if str(raw or "").isdigit()` читает **ноль** как «ничего не прислали»,
    потому что `0 or ""` в питоне даёт пустую строку. Поворот обратно в 0 —
    самое обычное действие в просмотрщике, и он отказывал.
    """
    if isinstance(value, bool) or value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def readable_photo(request, pk):
    """
    Снимок, который спрашивающему **есть чем** открыть.

    Ищется среди вложений школы, а отказ приходит из `can_read`, — тот же
    порядок, что у `AttachmentViewSet`, и по той же причине: внутри школы
    «не ваше» полезнее, чем «нет такого», а из чужой школы объекта нет вовсе.
    """
    attachment = get_object_or_404(
        file_access.school_attachments(request.user), pk=pk
    )
    if not file_access.can_read(request.user, attachment):
        api_denied(
            Codes.ATTACHMENT_FORBIDDEN,
            "This photo belongs to somebody else's work.",
        )
    return attachment


def require_drawing(request, attachment):
    if not photos.may_draw(request.user, attachment):
        api_denied(
            Codes.ATTACHMENT_FORBIDDEN,
            "Marking up a work is the teacher's own record of it.",
        )


# --- дверь семьи -------------------------------------------------------------


class StudentPhotosView(APIView):
    """
    Прислать фотографию работы: по задаче или на всю работу разом.

    Второе — не поблажка, а отдельный случай: задач в работе бывает
    пятнадцать, и требовать снимка к каждой значит получить снимки к трём.
    Тетрадь фотографируют целиком, а разложить это по задачам всё равно
    сможет только человек — и делать это ученику незачем.

    Ходит сюда **и родитель**: у младшего школьника телефона нет, и снимок
    присылает мама. Отвечать за ребёнка она по-прежнему не может — это
    другая вьюха и другое право.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsFamily]

    def post(self, request, pk):
        student = subject_of(request)
        work = get_object_or_404(services.visible_works(student), pk=pk)

        upload = request.FILES.get("file")
        if upload is None:
            # 400, а не 403: прислать нечего — это ошибка запроса, а не
            # запрет. Отказ правом отправил бы человека разбираться с
            # доступом там, где он просто не выбрал файл
            api_error(
                Codes.ATTACHMENT_OWNER_REQUIRED, "A photo is expected.", field="file"
            )

        attachment = photos.accept(
            work,
            student,
            upload=upload,
            task_id=whole(request.data.get("task")),
            by=request.user,
        )

        return Response(
            photos.photo_payload(attachment), status=status.HTTP_201_CREATED
        )


class StudentPhotoView(APIView):
    """
    Снять присланное — своё и пока окно открыто.

    Своя дверь, а не `DELETE /api/attachments/<id>/`: там вопрос «чей это
    урок», и ответ на него у семьи всегда «не ваш». Здесь вопрос другой —
    «ваше ли это и не поздно ли», — и второе учительская дверь не спрашивает
    вовсе, потому что учителю поздно не бывает.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsFamily]

    def delete(self, request, pk):
        attachment = readable_photo(request, pk)
        photos.may_remove(request.user, attachment)
        attachment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- дверь просмотрщика ------------------------------------------------------


class PhotoMarkupView(APIView):
    """
    Что нарисовано поверх снимка — и поворот самого снимка.

    Читают обе стороны: пометки учителя ученику показываются, иначе
    проверка красным была бы разговором с самим собой. Пишет поворот
    учитель: снятая боком тетрадь снята боком у всех, кто на неё смотрит.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember]

    def get(self, request, pk):
        attachment = readable_photo(request, pk)
        return Response(photos.markup_payload(attachment, user=request.user))

    def patch(self, request, pk):
        attachment = readable_photo(request, pk)
        require_drawing(request, attachment)

        # умолчание не 0, а заведомо неверное: пропущенный поворот — это
        # ошибка запроса, а нулём мы молча повернули бы снимок обратно
        photos.rotate(attachment, degrees=whole(request.data.get("rotation"), default=-1))
        return Response(photos.markup_payload(attachment, user=request.user))


class PhotoStrokesView(APIView):
    """
    Перо: положить мазок и снять последний свой.

    Мазок уходит на сервер сразу, как только его дорисовали, а не по кнопке
    «сохранить»: закрытая вкладка не должна стирать проверку. Поэтому и
    отмена ходит сюда же — снимать нечего, кроме того, что уже записано.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember]

    def post(self, request, pk):
        attachment = readable_photo(request, pk)
        require_drawing(request, attachment)

        stroke = photos.draw(
            attachment,
            author=request.user,
            color=request.data.get("color"),
            width=whole(request.data.get("width"), default=0),
            points=request.data.get("points"),
        )
        return Response(
            {
                "id": stroke.pk,
                "author": stroke.author_id,
                "color": stroke.color,
                "width": stroke.width,
                "points": stroke.points,
            },
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request, pk):
        attachment = readable_photo(request, pk)
        require_drawing(request, attachment)
        return Response({"undone": photos.undo(attachment, author=request.user)})


class PhotoNotesView(APIView):
    """Приколоть заметку к месту на снимке. Кладёт её учитель."""

    permission_classes = [IsAuthenticated, IsSchoolMember]

    def post(self, request, pk):
        attachment = readable_photo(request, pk)
        require_drawing(request, attachment)

        note = photos.pin(
            attachment,
            author=request.user,
            x=request.data.get("x"),
            y=request.data.get("y"),
            text=request.data.get("text", ""),
        )
        return Response(photos.note_payload(note), status=status.HTTP_201_CREATED)


class PhotoNoteView(APIView):
    """
    Одна заметка: сказать в ней слово или убрать её целиком.

    Говорят обе стороны — за этим её и заводили: «здесь потерян минус» без
    ответа «а почему?» было бы объявлением, а просили разговора. Убирает
    только тот, кто размечает: заметка — часть проверки, и снять её значит
    снять проверку.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember]

    def post(self, request, pk):
        note = self.mine(request, pk)
        if not photos.may_say(request.user, note.attachment):
            api_denied(
                Codes.ATTACHMENT_FORBIDDEN, "That conversation is not yours."
            )

        photos.say(note, author=request.user, text=request.data.get("text", ""))
        note.refresh_from_db()
        return Response(photos.note_payload(note))

    def delete(self, request, pk):
        note = self.mine(request, pk)
        require_drawing(request, note.attachment)
        note.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def mine(request, pk):
        """Заметка, снимок которой этот человек вправе открыть."""
        return get_object_or_404(
            PhotoNote.objects.filter(
                attachment__in=file_access.school_attachments(request.user)
            ).select_related("attachment", "attachment__student_work"),
            pk=pk,
        )
