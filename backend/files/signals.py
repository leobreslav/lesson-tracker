"""
The one place a file is ever removed from the bucket.

Nothing deletes an object directly. A teacher removes an attachment from their
lesson; if that was the last reference anywhere, the object goes too. While
somebody else still points at it, it stays — that is what makes a template's
files shareable rather than copied.

Two deliberate choices:

* the removal waits for the transaction to commit. Deleting inside it would
  mean a rollback puts the rows back while the bytes are already gone —
  a download that answers 404 forever. This way a rollback leaves a file with
  no references, which `cleanup_orphaned_files` finds and finishes off;
* if R2 refuses, the `StoredFile` row is kept on purpose. A row without
  references is a to-do item the cleanup command can act on; a row deleted
  while its object survives is rubbish nobody can name any more.

**Ссылок два вида, и держат объект обе.** Кроме вложений на него ссылается
журнал состояний плана (`PlanSnapshotFile`): пока снимок жив, объект должен
пережить удаление строки — иначе отмена вернула бы урок с вложением,
которое отвечает 404. Снимок истекает, ссылка уходит, и объект сносится
обычным порядком — либо тут же, если это была последняя, либо еженедельной
сверкой бакета с базой.
"""

import logging

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from . import storage
from .models import Attachment, StoredFile

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Attachment)
def drop_file_without_references(sender, instance, **kwargs):
    file_id = instance.stored_file_id
    if file_id is None:
        return

    transaction.on_commit(lambda: forget_file(file_id))


@receiver(post_delete, sender="plans.PlanSnapshotFile")
def drop_file_when_the_snapshot_expires(sender, instance, **kwargs):
    """Снимок истёк — его ссылка тоже была ссылкой."""
    file_id = instance.stored_file_id
    if file_id is None:
        return

    transaction.on_commit(lambda: forget_file(file_id))


def held_elsewhere(file_id: int) -> bool:
    """Ссылается ли на объект хоть кто-нибудь — вложение или снимок."""
    from plans.history import PlanSnapshotFile

    return (
        Attachment.objects.filter(stored_file_id=file_id).exists()
        or PlanSnapshotFile.objects.filter(stored_file_id=file_id).exists()
    )


def forget_file(file_id: int) -> bool:
    """Remove the object and its row, unless something still points at it."""
    if held_elsewhere(file_id):
        return False

    stored = StoredFile.objects.filter(pk=file_id).first()
    if stored is None:
        # already gone: two references dropped in the same breath
        return False

    try:
        storage.delete(stored.key)
    except storage.StorageUnavailable:
        logger.warning(
            "could not remove %s from storage; the row is kept for cleanup",
            stored.key,
        )
        return False

    StoredFile.objects.filter(pk=file_id).delete()
    return True
