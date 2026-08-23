from config.access import IsSchoolMember
from config.errors import Codes, api_denied, api_error, api_unavailable
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import access, services, storage
from .models import KIND_FILE, OWNER_FIELDS, Attachment
from .serializers import (
    AttachmentCreateSerializer,
    AttachmentSerializer,
    with_sharing,
)


def refuse_upload(refused: services.UploadRefused):
    api_error(refused.code, refused.detail, field="file", **refused.params)


class AttachmentViewSet(viewsets.ModelViewSet):
    """
    Files and links hanging off one lesson.

    Not a `SchoolScopedViewSet`: an attachment reaches its school through two
    different paths (a plan node's teacher, or a template's school), and the
    read rule is finer than "everyone in the school" — see `access`.
    """

    # `IsTeacher` тут нет: сканы своих работ читает и ученик, а кто на что
    # имеет право, решает `access` — вопрос «чьё это вложение», а не «кто вы
    # по виду». Ученику при этом закрыто всё остальное: `readable_attachments`
    # отдаёт ему только его собственные работы
    permission_classes = [IsAuthenticated, IsSchoolMember]
    serializer_class = AttachmentSerializer

    def get_queryset(self):
        """The list: only what this person may actually read."""
        queryset = with_sharing(access.readable_attachments(self.request.user))
        params = self.request.query_params

        # Картинка, стоящая в содержании, в список материалов не попадает.
        # Список — это то, чем на уроке пользуются и что человек правит
        # строкой за строкой; картинкой же распоряжается текст, и строка
        # «image.png» рядом с «карточки.pdf» ничего не сказала бы о том,
        # где эта картинка и зачем.
        queryset = queryset.filter(inline=False)

        for name in OWNER_FIELDS:
            raw = params.get(name)
            if not raw:
                continue
            queryset = (
                queryset.filter(**{f"{name}_id": raw})
                if raw.isdigit()
                else queryset.none()
            )

        return queryset

    def get_object(self):
        """
        Detail lookup, with the two refusals kept apart.

        Looked up among the school's attachments rather than among the
        readable ones, so that a colleague's lesson answers "not yours"
        instead of "no such thing" — inside one school the second would be a
        lie anyone could see through.
        """
        attachment = get_object_or_404(
            with_sharing(access.school_attachments(self.request.user)),
            pk=self.kwargs["pk"],
        )

        allowed = (
            access.can_read(self.request.user, attachment)
            if self.request.method in SAFE_METHODS
            else access.can_write(self.request.user, attachment)
        )
        if not allowed:
            api_denied(
                Codes.ATTACHMENT_FORBIDDEN,
                "This attachment belongs to somebody else's lesson.",
            )

        return attachment

    def create(self, request, *args, **kwargs):
        form = AttachmentCreateSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        form.is_valid(raise_exception=True)
        data = form.validated_data

        owner = {
            name: data[name] for name in OWNER_FIELDS if data.get(name) is not None
        }

        inline = data.get("inline", False)

        stored = None
        if data["kind"] == KIND_FILE:
            upload = data["file"]
            try:
                stored, _ = services.store_upload(
                    upload=upload, school=request.user.school, user=request.user
                )
            except services.UploadRefused as refused:
                refuse_upload(refused)
            except storage.StorageUnavailable:
                api_unavailable(
                    Codes.STORAGE_UNAVAILABLE,
                    "The file store is not answering. The file was not saved.",
                )

        if inline:
            # Та же картинка, вставленная в тот же урок дважды, — одна
            # картинка. Байты уже свела дедупликация, а вторая ссылка на них
            # не дала бы ничего, кроме строки, которую нечем убрать: текст
            # называет файл, и обе ссылки для него неразличимы.
            twin = Attachment.objects.filter(
                **owner, inline=True, stored_file=stored
            ).first()
            if twin is not None:
                return Response(
                    AttachmentSerializer(
                        with_sharing(Attachment.objects.filter(pk=twin.pk)).first()
                    ).data
                )

        attachment = Attachment.objects.create(
            **owner,
            kind=data["kind"],
            stored_file=stored,
            inline=inline,
            url=data.get("url", ""),
            title=(
                data.get("title")
                or (stored.original_name if stored else data.get("url", ""))
            )[:200],
            position=services.next_position(**owner),
        )

        return Response(
            AttachmentSerializer(
                with_sharing(Attachment.objects.filter(pk=attachment.pk)).first()
            ).data,
            status=201,
        )

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """
        A five-minute link straight to R2.

        The bytes never pass through Django: proxying them would hold a
        gunicorn worker for the length of the download, and there are two.

        Answers with a redirect, which is what a browser or `curl` wants.
        The single-page app asks for `?json=1` instead: it has to send a
        token header, and a header cannot survive a redirect to another
        origin — so it takes the address and navigates to it itself.
        """
        attachment = self.get_object()

        if attachment.kind != KIND_FILE:
            api_error(
                Codes.ATTACHMENT_KIND_MISMATCH,
                "This attachment is a link, not a file.",
                field="kind",
            )

        try:
            url = storage.download_url(attachment.stored_file)
        except storage.StorageUnavailable:
            api_unavailable(
                Codes.STORAGE_UNAVAILABLE,
                "The file store is not answering. Try again in a moment.",
            )

        if request.query_params.get("json") in ("1", "true"):
            return Response({"url": url})

        return HttpResponseRedirect(url)


class ContentImageView(APIView):
    """
    Адрес картинки, стоящей **в тексте**: в содержании урока или в задании.

    Отдельная дверь от `/attachments/<id>/download/`, и не ради удобства:
    текст называет файл, а не вложение, потому что id вложения у каждой
    копии плана свой (см. `plans.content.IMAGE_REF`). Спрашивать по номеру
    вложения значило бы переписывать разметку при каждом копировании и
    откате — и молча ломать картинку в первом же забытом месте.

    Отвечает только JSON: `<img>` не умеет нести заголовок с токеном,
    поэтому страница берёт адрес сама и подставляет его в `src`. Ради
    перехода руками редирект тут был бы, но руками сюда никто не ходит.

    **Учительской эта дверь быть перестала, и звалась она поэтому
    `LessonImageView`.** Пока текст с картинками был только у урока, «читают
    его учитель и методист» было правдой, и `IsTeacher` стоял здесь честно.
    Пояснения к работе эту правду отменили: их пишут ровно затем, чтобы
    прочитал класс, и снимок доски в них — часть условия, а не заметка на
    полях. С `IsTeacher` ученик получал бы 403 на каждой картинке задания и
    видел пустое место там, где написано, что делать.

    Вид спрашивать вместо права было бы вторым ответом на тот же вопрос:
    кому что видно, отвечает `readable_stored_file` — по **своей** читаемой
    ссылке на файл. Ученику своими оказываются ровно две: работы, которые ему
    открыты, и его собственная тетрадь; ни урока, ни полки он не читает.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember]

    def get(self, request, file_id: int):
        stored = access.readable_stored_file(request.user, file_id)
        if stored is None:
            # ни «не ваше», ни «нет такого» по отдельности тут не сказать:
            # спрашивают не про объект, а про то, есть ли на него своя
            # ссылка, и отсутствие ссылки и есть отсутствие картинки
            raise Http404

        try:
            url = storage.download_url(stored)
        except storage.StorageUnavailable:
            api_unavailable(
                Codes.STORAGE_UNAVAILABLE,
                "The file store is not answering. Try again in a moment.",
            )

        return Response({"url": url})
