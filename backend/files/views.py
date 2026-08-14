from config.access import IsSchoolMember, IsTeacher
from config.errors import Codes, api_denied, api_error, api_unavailable
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response

from . import access, services, storage
from .models import KIND_FILE, Attachment
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

    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]
    serializer_class = AttachmentSerializer

    def get_queryset(self):
        """The list: only what this person may actually read."""
        queryset = with_sharing(access.readable_attachments(self.request.user))
        params = self.request.query_params

        for name in ("plan_row", "template_row"):
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

        owner = (
            {"plan_row": data["plan_row"]}
            if data.get("plan_row") is not None
            else {"template_row": data["template_row"]}
        )

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

        attachment = Attachment.objects.create(
            **owner,
            kind=data["kind"],
            stored_file=stored,
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
