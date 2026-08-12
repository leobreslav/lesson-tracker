"""
Everything that knows about the object store, and nothing else does.

The bucket is private: there is no public URL for an object, and the only way
to reach one is a presigned link this module signs. Signing is local work —
no request leaves the process — so a download link is handed out even when R2
itself is having a bad day; what fails then is the browser's own fetch, not
the page that offered the link.

The rest of the project talks to `StoredFile.key` and never to boto3. Tests
swap `STORAGES["files"]` for an in-memory backend, which is why the two
non-S3 branches below exist: a plain Django storage has no bucket, so it
cannot presign and cannot be paged through.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import PurePosixPath
from urllib.parse import quote

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.files.storage import storages

logger = logging.getLogger(__name__)

# every object of ours lives under this prefix, so the cleanup command can
# tell our rubbish from whatever else the bucket may hold
KEY_PREFIX = "files"

# what may appear in a key: the real name rides in Content-Disposition
UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

CHUNK = 64 * 1024


class StorageUnavailable(Exception):
    """The object store did not answer. Not the page's fault, and not fatal."""


def backend():
    return storages["files"]


@contextmanager
def as_unavailable():
    """Turn any storage failure into one exception the views know about."""
    try:
        yield
    except (BotoCoreError, ClientError) as error:
        logger.warning("object storage failed: %s", error)
        raise StorageUnavailable(str(error)) from error


# --- names and keys ----------------------------------------------------------


# Cyrillic does not fold to ascii on its own — «Карточка» would come out
# empty and every key would end up named `file`. That is technically fine and
# operationally useless: the cleanup command prints keys, and a bucket full of
# `file.txt` cannot be read by a person.
CYRILLIC = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
)


def _ascii(text: str) -> str:
    lowered = text.translate(CYRILLIC) if text else text
    # the uppercase half, without a second table
    lowered = "".join(
        ch.lower().translate(CYRILLIC).upper() if ch.isupper() else ch
        for ch in lowered
    )
    folded = unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode()
    return UNSAFE.sub("_", folded).strip("_")


def sanitize(name: str) -> str:
    """
    A key-safe version of a file name.

    Cyrillic folds away to nothing, which is fine: the key is an address, not
    a label. The name a person typed is stored on the row and comes back in
    the download header — the extension is kept only so a key is readable in
    the bucket listing.
    """
    plain = PurePosixPath((name or "").replace("\\", "/")).name
    stem, _, suffix = plain.rpartition(".")
    if not stem:
        stem, suffix = plain, ""

    safe_stem = _ascii(stem)[:80] or "file"
    safe_suffix = _ascii(suffix)[:16]

    return f"{safe_stem}.{safe_suffix}" if safe_suffix else safe_stem


def build_key(school_id: int, original_name: str) -> str:
    """`files/<school>/<uuid>/<name>` — the uuid is what makes it unique."""
    return f"{KEY_PREFIX}/{school_id}/{uuid.uuid4()}/{sanitize(original_name)}"


def content_disposition(original_name: str) -> str:
    """Download as a file, under the name it was uploaded with."""
    return (
        f'attachment; filename="{sanitize(original_name)}"; '
        f"filename*=UTF-8''{quote(original_name)}"
    )


# --- reading an upload -------------------------------------------------------


def digest(upload) -> tuple[str, int]:
    """
    sha256 and size, read in chunks and rewound afterwards.

    Chunked because a 20 MB upload already lives in a temporary file rather
    than in memory, and reading it whole to hash it would undo that.
    """
    sha = hashlib.sha256()
    size = 0

    for chunk in upload.chunks(CHUNK):
        sha.update(chunk)
        size += len(chunk)

    upload.seek(0)
    return sha.hexdigest(), size


# --- the store itself --------------------------------------------------------


def save(key: str, upload) -> str:
    """Put an object there and return the key it actually got."""
    with as_unavailable():
        return backend().save(key, upload)


def delete(key: str) -> None:
    with as_unavailable():
        backend().delete(key)


def exists(key: str) -> bool:
    with as_unavailable():
        return backend().exists(key)


def download_url(stored_file) -> str:
    """
    A link that stops working in five minutes.

    R2 serves the object itself: proxying it through Django would tie up a
    gunicorn worker for the length of a download, and there are two of them.
    """
    store = backend()

    with as_unavailable():
        if not hasattr(store, "bucket"):
            # a plain backend (tests, a dev machine with no R2 keys)
            return store.url(stored_file.key)

        return store.url(
            stored_file.key,
            parameters={
                "ResponseContentDisposition": content_disposition(
                    stored_file.original_name
                ),
                "ResponseContentType": stored_file.content_type,
            },
            expire=settings.FILE_URL_TTL,
        )


def iter_keys(prefix: str = KEY_PREFIX + "/"):
    """Every object under the prefix. Used by the cleanup command only."""
    store = backend()

    with as_unavailable():
        if not hasattr(store, "bucket"):
            yield from _walk(store, prefix.rstrip("/"))
            return

        client = store.bucket.meta.client
        pages = client.get_paginator("list_objects_v2").paginate(
            Bucket=store.bucket.name, Prefix=prefix
        )
        for page in pages:
            for item in page.get("Contents", ()):
                yield item["Key"]


def _walk(store, path: str):
    """listdir recursion, for backends that have nothing better."""
    try:
        directories, names = store.listdir(path)
    except (FileNotFoundError, NotImplementedError):
        return

    for name in names:
        yield f"{path}/{name}" if path else name
    for directory in directories:
        yield from _walk(store, f"{path}/{directory}" if path else directory)
