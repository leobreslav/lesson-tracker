"""
Accepting an upload, and copying references without copying bytes.

The two halves of this module answer the two questions the feature raises:
may this file come in at all, and what happens when a lesson carrying files
is copied. Neither belongs in a view — the import from the library needs the
second one just as much as the upload endpoint needs the first.
"""

from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath

from django.conf import settings
from django.db.models import Count, Sum

from plans import content

from . import storage
from .models import Attachment, KIND_FILE, StoredFile

# What may be uploaded, by extension, with the content types a browser is
# expected to declare for it.
#
# Both are checked, as they answer different questions: the extension is what
# a colleague's machine will act on when the file is saved, the content type
# is what the uploader claims it is. Neither alone is worth much.
ALLOWED = {
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".gif": {"image/gif"},
    ".webp": {"image/webp"},
    # svg is script-capable, but it is only ever handed out with
    # Content-Disposition: attachment, from a domain that is not ours — the
    # browser saves it, it never renders it in our origin
    ".svg": {"image/svg+xml"},
    ".pdf": {"application/pdf"},
    ".txt": {"text/plain"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    },
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    },
    ".zip": {"application/zip", "application/x-zip-compressed"},
}

# Что можно поставить **в текст** урока, а не приложить к нему списком.
#
# Список уже: показывать картинку в чужой странице — не то же самое, что
# отдать её файлом. `.svg` сюда не входит намеренно: он умеет нести скрипт,
# и всё, что его спасает как вложение, — отдача с чужого домена и
# `Content-Disposition: attachment`, то есть ровно «браузер его не
# показывает». Инлайновая картинка просит обратного.
INLINE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


# A browser that does not recognise a file sends this, and the file is
# perfectly fine. Refusing it would reject real uploads for no gain, so an
# unknown type passes when the extension is on the list — the extension is
# what the check actually rests on.
UNKNOWN_TYPES = {"", "application/octet-stream"}


class UploadRefused(Exception):
    """The file is not coming in. Carries a code the view turns into 400."""

    def __init__(self, code: str, detail: str, **params):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.params = params


def extension_of(name: str) -> str:
    return PurePosixPath((name or "").replace("\\", "/")).suffix.lower()


def shows_in_text(name: str) -> bool:
    """Годится ли этот файл на то, чтобы стоять в содержании урока."""
    return extension_of(name) in INLINE_EXTENSIONS


# Что открывается в просмотрщике работ и по чему можно рисовать.
VIEWER_EXTENSIONS = INLINE_EXTENSIONS | {".pdf"}


def opens_in_viewer(name: str) -> bool:
    """
    Умеет ли просмотрщик работ показать это и дать по этому рисовать.

    Список **шире**, чем у картинки в тексте, и это не небрежность: в текст
    урока ставят картинку, а в просмотрщике проверяют работу, и работа
    приходит либо снимком с телефона, либо PDF'ом — сканом от учителя или
    вывернутой в PDF тетрадью из телефонного сканера. Пока список был один на
    оба вопроса, PDF отказывали на приёме со словами «просмотрщик не нарисует
    страницу» — и это была правда ровно до того, как он научился.

    `.svg` сюда не попадает и попасть не должен: он умеет нести скрипт, и всё,
    что его спасает как вложение, — отдача с чужого домена и
    `Content-Disposition: attachment`. Просмотрщик просит обратного.
    """
    return extension_of(name) in VIEWER_EXTENSIONS


def quota_used(school_id: int) -> int:
    """
    How much of the school's quota is taken.

    Sums `StoredFile`, not attachments: a file three lessons point at is one
    file in the bucket and is charged once.
    """
    return (
        StoredFile.objects.filter(school_id=school_id).aggregate(total=Sum("size"))[
            "total"
        ]
        or 0
    )


def check_upload(*, name: str, size: int, content_type: str, school_id: int) -> None:
    """Size, type and quota. Raises `UploadRefused`, otherwise says nothing."""
    limit = settings.FILE_MAX_BYTES

    if size > limit:
        raise UploadRefused(
            "file_too_large",
            f"The file is larger than {limit // 1024 // 1024} MB.",
            limit_mb=limit // 1024 // 1024,
        )

    extension = extension_of(name)
    declared = (content_type or "").split(";")[0].strip().lower()

    if extension not in ALLOWED or (
        declared not in ALLOWED[extension] and declared not in UNKNOWN_TYPES
    ):
        raise UploadRefused(
            "file_type_not_allowed",
            "This kind of file cannot be attached to a lesson.",
            extension=extension,
            content_type=declared,
            allowed=sorted(ALLOWED),
        )

    quota = settings.SCHOOL_FILE_QUOTA_BYTES
    if quota_used(school_id) + size > quota:
        raise UploadRefused(
            "school_quota_exceeded",
            "The school has used up its storage quota.",
            quota_mb=quota // 1024 // 1024,
            used_mb=quota_used(school_id) // 1024 // 1024,
        )


def find_twin(*, school_id: int, checksum: str, size: int) -> StoredFile | None:
    """The same bytes already in this school, if they are."""
    return StoredFile.objects.filter(
        school_id=school_id, checksum=checksum, size=size
    ).first()


def store_upload(*, upload, school, user) -> tuple[StoredFile, bool]:
    """
    Take an uploaded file in. Returns the row and whether it is new.

    The hash is computed before anything is sent, so the same file uploaded
    twice into one school costs one object and one row — which matters here
    more than it usually would: a template's worksheet lands in the plans of
    everybody who takes it, and a teacher who saves it and re-uploads it is
    the normal way that happens.
    """
    checksum, size = storage.digest(upload)

    check_upload(
        name=upload.name,
        size=size,
        content_type=upload.content_type,
        school_id=school.pk,
    )

    twin = find_twin(school_id=school.pk, checksum=checksum, size=size)
    if twin is not None:
        return twin, False

    key = storage.save(storage.build_key(school.pk, upload.name), upload)

    stored = StoredFile.objects.create(
        school=school,
        uploaded_by=user,
        key=key,
        original_name=upload.name[:255],
        size=size,
        content_type=(upload.content_type or "application/octet-stream")[:120],
        checksum=checksum,
    )
    return stored, True


# --- copying references ------------------------------------------------------


def copy_attachments(sources, *, plan_row=None, template_row=None) -> int:
    """
    Point a new row at the same files as an old one.

    This is the shareable bit made concrete: nothing is uploaded, nothing is
    downloaded, `stored_file` is carried across unchanged. Two teachers who
    took the same template are then reading one object in the bucket, and
    either of them removing it from their plan leaves the other's intact.

    `inline` едет вместе с остальным, и это не мелочь: картинка, вставленная
    в текст, при переносе шаблона обязана остаться картинкой в тексте. Иначе
    копия показала бы её строкой в списке материалов — при том, что в тексте
    она по-прежнему нарисована.
    """
    copies = [
        Attachment(
            plan_row=plan_row,
            template_row=template_row,
            kind=source.kind,
            stored_file_id=source.stored_file_id,
            url=source.url,
            inline=source.inline,
            title=source.title,
            position=position,
        )
        for position, source in enumerate(sources)
    ]

    Attachment.objects.bulk_create(copies)
    return len(copies)


def prune_inline(row) -> int:
    """
    Убрать картинки, на которые содержание больше не ссылается.

    У материала и у картинки в тексте разные часы, и это записано прямо
    здесь. Материал — отдельная строка на сервере: его заводят и убирают
    сразу, потому что файл, ждущий кнопки «Сохранить», это загрузка, которая
    тихо не случилась. А картинка **часть текста**: её убирают, стирая
    разметку, и до сохранения она может вернуться нажатием Ctrl+Z. Поэтому
    вопрос «нужна ли ещё эта картинка» задаётся ровно один раз — когда текст
    сохранён, — и ответ на него даёт сам текст.

    Отсюда же следует, что стёртая руками разметка убирает картинку так же,
    как крестик на ней: другого источника правды нет и заводить его нельзя —
    два разошлись бы молча.

    Уборка безопасна, потому что перед каждой правкой плана снимается
    снимок, а снимок держит объект в бакете своей ссылкой (`PROTECT`).
    Отмена вернёт и текст, и картинку.
    """
    used = content.images_in(row)
    doomed = list(
        row.attachments.filter(inline=True).exclude(stored_file_id__in=used)
    )
    if doomed:
        Attachment.objects.filter(pk__in=[item.pk for item in doomed]).delete()
    return len(doomed)


def attachments_of(row) -> list[Attachment]:
    """The attachments of a plan node or a template row, in display order."""
    return list(row.attachments.select_related("stored_file"))


def next_position(**owner) -> int:
    """Сколько вложений у этого владельца уже есть — оно и будет позицией."""
    named = {name: value for name, value in owner.items() if value is not None}
    return Attachment.objects.filter(**named).count()


def has_file_attachments(row) -> bool:
    return row.attachments.filter(kind=KIND_FILE).exists()


def files_at_risk(plan_rows) -> int:
    """
    How many objects in the store would go if these plan rows were deleted.

    Only the ones losing their **last** reference: a file shared with a
    template or with another course survives, and warning about it would be a
    lie — the kind that teaches people to click through warnings.
    """
    doomed = Counter(
        Attachment.objects.filter(
            plan_row__in=plan_rows, stored_file__isnull=False
        ).values_list("stored_file_id", flat=True)
    )
    if not doomed:
        return 0

    total = dict(
        Attachment.objects.filter(stored_file_id__in=doomed)
        .values_list("stored_file_id")
        .annotate(references=Count("pk"))
    )

    return sum(1 for file_id, going in doomed.items() if total.get(file_id, 0) <= going)
